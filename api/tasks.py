# api/tasks.py
import os
import hashlib
import tempfile
import shutil
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from git import Repo

from api.llm_service import generate_ai_metadata, generate_project_overview, generate_beginner_overview, generate_expert_overview, generate_explanation, generate_expert_analysis
from api import models, crud, report_generator
from api.parsers import detect_and_parse, detect_language, SUPPORTED_EXTENSIONS
from api.celery_app import celery_app
from api.config import config
from concurrent.futures import ThreadPoolExecutor, as_completed
from api.llm_service import generate_ai_metadata_batch, lookup_cached_metadata
from api.embedding_service import generate_function_embeddings_batch, is_enabled as embedding_enabled
from api.sse import publish_progress

# 数据库引擎和会话工厂（用于独立创建 session，避免依赖 FastAPI 的 get_db）
engine = create_engine(
    config.DATABASE_URL,
    pool_size=20,
    max_overflow=30,
    pool_pre_ping=True,
    pool_recycle=3600,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """独立的数据库会话生成器，用于 Celery 任务中"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------- 辅助函数：启动任务（非 Celery 任务） ----------
def start_analysis_task(repo_url: str, project_name: str = None, mode: str = "ai"):
    """创建数据库任务记录并启动 Celery 分析任务，返回 task_id"""
    db = next(get_db())
    # 提前查重：检查是否已存在相同 repo_url 的项目
    existing_project = db.query(models.Project).filter(
        models.Project.repo_url == repo_url
    ).first()
    project_id = existing_project.id if existing_project else None
    if existing_project:
        print(f"🔁 发现已有项目 (id={existing_project.id}, name={existing_project.name})，复用记录")
    task_record = crud.create_task(db, project_id=project_id)
    db.close()
    # 启动 Celery 任务
    result = analyze_repo.delay(task_record.id, repo_url, project_name, mode)
    return result.id


def get_existing_repo_path(project_id: int):
    """获取已存在的仓库路径"""
    return os.path.join(config.TEMP_DIR, f"repo_{project_id}")


def save_checkpoint(db, task_id: int, processed_files: list, last_file: str = None, total_files: int = None):
    """保存任务检查点"""
    task = db.query(models.AnalysisTask).filter(models.AnalysisTask.id == task_id).first()
    if task:
        if processed_files:
            task.processed_files = processed_files
        if last_file:
            task.last_processed_file = last_file
        if total_files is not None:
            task.total_files = total_files
        db.commit()


def load_checkpoint(db, task_id: int):
    """加载任务检查点"""
    task = db.query(models.AnalysisTask).filter(models.AnalysisTask.id == task_id).first()
    if task:
        return {
            "processed_files": task.processed_files or [],
            "last_processed_file": task.last_processed_file,
            "total_files": task.total_files or 0,
            "status": task.status,
            "current_step": task.current_step,
            "progress_percent": task.progress_percent
        }
    return None


def get_processed_files_from_db(db, project_id: int):
    """从数据库获取已处理的文件列表"""
    files = db.query(models.File).filter(models.File.project_id == project_id).all()
    return [f.file_path for f in files]


# ---------- Celery 任务：实际分析仓库 ----------
@celery_app.task(bind=True, name="analyze_repo", max_retries=3)
def analyze_repo(self, task_id: int, repo_url: str, project_name: str = None, mode: str = "ai"):
    """分析代码仓库的主任务（支持断点续传）"""
    db = next(get_db())
    temp_dir = None

    try:
        # 获取任务记录
        task = db.query(models.AnalysisTask).filter(models.AnalysisTask.id == task_id).first()
        if not task:
            raise ValueError(f"Task {task_id} not found")

        # 加载检查点
        checkpoint = load_checkpoint(db, task_id)
        processed_files = set(checkpoint["processed_files"]) if checkpoint["processed_files"] else set()
        last_processed = checkpoint.get("last_processed_file")
        is_resuming = len(processed_files) > 0 and task.status == "running"

        if is_resuming:
            print(f"🔄 恢复任务 {task_id}，已处理 {len(processed_files)} 个文件")
            self.update_state(state='PROGRESS', meta={
                'current_step': f'恢复任务，已处理 {len(processed_files)} 个文件',
                'progress': checkpoint.get("progress_percent", 0)
            })

        # 更新任务状态：克隆阶段，进度10%
        if not is_resuming or not task.project_id:
            crud.update_task_status(db, task_id, "running", current_step="cloning", progress_percent=10)
            self.update_state(state='PROGRESS', meta={'current_step': 'cloning', 'progress': 10})
            publish_progress(task_id, "cloning", 10, "cloning repository")

        # 获取或创建仓库目录（支持断点续传）
        existing_project = None
        if task.project_id:
            existing_project = crud.get_project(db, task.project_id)

        if existing_project and os.path.exists(get_existing_repo_path(existing_project.id)):
            # 使用已存在的仓库目录
            temp_dir = get_existing_repo_path(existing_project.id)
            print(f"📁 使用已存在的仓库目录: {temp_dir}")

            # 更新仓库（git pull）
            try:
                repo = Repo(temp_dir)
                repo.remotes.origin.pull()
                print("✅ 仓库已更新")
            except Exception as e:
                print(f"⚠️ 更新仓库失败: {e}，将使用现有版本")
        else:
            # 创建临时目录
            temp_dir = tempfile.mkdtemp(dir=config.TEMP_DIR)

            is_local_path = repo_url.startswith("/") or repo_url.startswith("~/")

            if is_local_path:
                # 本地路径：直接复制目录并初始化 git
                import glob as glob_mod
                resolved_path = os.path.expanduser(repo_url)
                print(f"📂 复制本地目录: {resolved_path}")

                # 复制所有内容到临时目录
                for item in os.listdir(resolved_path):
                    src = os.path.join(resolved_path, item)
                    dst = os.path.join(temp_dir, item)
                    if os.path.isdir(src):
                        shutil.copytree(src, dst, ignore=shutil.ignore_patterns('.git', '__pycache__', 'node_modules', 'venv', 'env', 'target', 'build', 'dist'))
                    else:
                        shutil.copy2(src, dst)

                # 初始化 git 仓库以获取 commit hash
                repo = Repo.init(temp_dir)
                repo.index.add('*')
                repo.index.commit("分析本地代码")
                print("✅ 本地目录复制完成")
            else:
                # 克隆远程仓库
                clone_url = repo_url
                if not clone_url.endswith(".git"):
                    clone_url = clone_url + ".git"

                # 支持私有仓库认证（通过 GITHUB_TOKEN 环境变量）
                github_token = os.environ.get("GITHUB_TOKEN", "")
                if github_token and "github.com" in clone_url and clone_url.startswith("https://"):
                    # 在 URL 中嵌入 token：https://x-access-token:{token}@github.com/...
                    clone_url = clone_url.replace("https://", f"https://x-access-token:{github_token}@")
                    print(f"🔑 使用 GITHUB_TOKEN 认证克隆")
                else:
                    # 可选：使用 GitHub 镜像加速
                    # if "github.com" in clone_url:
                    #     clone_url = clone_url.replace("https://github.com/", "https://ghproxy.com/https://github.com/")
                    pass

                print(f"📥 克隆仓库: {clone_url}")
                repo = Repo.clone_from(clone_url, temp_dir)
                print("✅ 仓库克隆完成")

        # 获取当前commit hash
        commit_hash = repo.head.commit.hexsha

        # 创建或更新项目记录
        project_name = project_name or repo_url.split("/")[-1].replace(".git", "")

        if task.project_id:
            project = crud.get_project(db, task.project_id)
            # 检查 commit 是否变化
            if project.last_analyzed_commit != commit_hash:
                print(f"📝 Commit 已更新: {project.last_analyzed_commit} -> {commit_hash}")
                # 清空已处理文件记录，因为代码已更新
                processed_files = set()
                task.processed_files = []
                db.commit()
        else:
            # 检查是否已存在相同 repo_url 的项目，避免重复
            existing = db.query(models.Project).filter(
                models.Project.repo_url == repo_url
            ).first()
            if existing:
                project = existing
                print(f"🔁 发现已有项目 (id={project.id})，复用记录")
            else:
                project = crud.create_project(db, name=project_name, repo_url=repo_url, language="python", analysis_mode=mode)
            task.project_id = project.id
            db.commit()

            # 将仓库目录移动到持久化位置
            persistent_repo_path = get_existing_repo_path(project.id)
            if temp_dir != persistent_repo_path:
                if os.path.exists(persistent_repo_path):
                    shutil.rmtree(persistent_repo_path)
                shutil.move(temp_dir, persistent_repo_path)
                temp_dir = persistent_repo_path

        # 更新项目commit
        project.last_analyzed_commit = commit_hash
        db.commit()

        # 更新进度：解析阶段，进度30%
        if not is_resuming or task.current_step != "parsing":
            crud.update_task_status(db, task_id, "running", current_step="parsing", progress_percent=30)
            self.update_state(state='PROGRESS', meta={'current_step': 'parsing', 'progress': 30})
            publish_progress(task_id, "parsing", 30, "parsing source files")

        # 遍历所有支持的文件
        supported_exts = tuple(SUPPORTED_EXTENSIONS.keys())
        source_files = []
        for root, dirs, files in os.walk(temp_dir):
            dirs[:] = [d for d in dirs if d not in [".git", "__pycache__", "venv", "env", "node_modules", "target", "build", "dist"]]
            for file in files:
                if file.endswith(supported_exts):
                    full_path = os.path.join(root, file)
                    rel_path = os.path.relpath(full_path, temp_dir)
                    source_files.append((full_path, rel_path))

        total_files = len(source_files)

        # 保存总文件数到检查点
        save_checkpoint(db, task_id, list(processed_files), total_files=total_files)

        # 从数据库获取已处理的文件（用于断点续传）
        db_processed_files = set(get_processed_files_from_db(db, project.id))
        processed_files.update(db_processed_files)

        print(f"📊 总文件数: {total_files}, 已处理: {len(processed_files)}")

        # 处理文件
        for idx, (full_path, rel_path) in enumerate(source_files):
            # 跳过已处理的文件
            if rel_path in processed_files:
                print(f"⏭️ 跳过已处理文件: {rel_path}")
                continue

            # 计算当前进度（30% ~ 90%）
            current_idx = len(processed_files) + idx
            progress = 30 + (current_idx / total_files) * 60
            self.update_state(state='PROGRESS', meta={
                'current_step': f'analyzing {rel_path}',
                'progress': progress
            })
            crud.update_task_status(db, task_id, "running", current_step=f'analyzing {rel_path}',
                                    progress_percent=int(progress))
            publish_progress(task_id, "analyzing", int(progress), current_step=f"analyzing {rel_path}")

            # 计算文件hash
            with open(full_path, "rb") as f:
                content = f.read()
                file_hash = hashlib.md5(content).hexdigest()
            size = len(content)

            # 检查是否已存在
            existing = crud.get_file_by_path(db, project.id, rel_path)
            if existing:
                if existing.file_hash == file_hash:
                    # 文件未变化，标记为已处理并继续
                    processed_files.add(rel_path)
                    save_checkpoint(db, task_id, list(processed_files), rel_path, total_files)
                    continue
                else:
                    # 文件已变化，删除旧记录
                    db.query(models.Function).filter(models.Function.file_id == existing.id).delete()
                    db.query(models.Class).filter(models.Class.file_id == existing.id).delete()
                    db.delete(existing)
                    db.commit()

            # 检测语言
            lang = detect_language(full_path) or "unknown"

            # 解析文件
            try:
                parse_result = detect_and_parse(full_path)
            except Exception as e:
                print(f"❌ 解析文件失败 {rel_path}: {e}")
                processed_files.add(rel_path)  # 标记为已处理（跳过）
                save_checkpoint(db, task_id, list(processed_files), rel_path, total_files)
                continue

            # 创建文件记录
            file_obj = crud.create_file(db, project.id, rel_path, file_hash, size, lang)

            # 写入文件依赖（解析到的 imports）
            if parse_result.get("imports"):
                file_obj.dependencies = {
                    "imports": [
                        {"source": imp["target"], "line": imp["line"]}
                        for imp in parse_result["imports"]
                    ]
                }
                db.commit()

            # ── Collect function work items ──
            func_work_items = []
            for func in parse_result["functions"]:
                try:
                    with open(full_path, 'r', encoding='utf-8') as f:
                        lines = f.readlines()
                        code_snippet = ''.join(lines[func["start_line"] - 1:func["end_line"]])

                    existing_func = db.query(models.Function).filter(
                        models.Function.file_id == file_obj.id,
                        models.Function.name == func["name"],
                        models.Function.start_line == func["start_line"]
                    ).first()

                    can_skip = False
                    if existing_func and existing_func.ai_purpose:
                        if project.analysis_mode == "beginner" and existing_func.explanation_simple:
                            print(f"⏭️ 跳过已分析函数(Beginner): {func['name']}")
                            can_skip = True
                        elif project.analysis_mode == "expert" and existing_func.expert_purpose:
                            print(f"⏭️ 跳过已分析函数(Expert): {func['name']}")
                            can_skip = True
                        elif project.analysis_mode == "ai":
                            print(f"⏭️ 跳过已分析函数(AI): {func['name']}")
                            can_skip = True

                    if can_skip:
                        continue

                    needs_ai = not (existing_func and existing_func.ai_purpose)
                    needs_beginner = project.analysis_mode == "beginner" and not (existing_func and existing_func.explanation_simple)
                    needs_expert = project.analysis_mode == "expert" and not (existing_func and existing_func.expert_purpose)

                    func_work_items.append({
                        "func": func,
                        "code_snippet": code_snippet,
                        "code_hash": hashlib.md5(code_snippet.encode('utf-8')).hexdigest(),
                        "existing_func": existing_func,
                        "lang": lang,
                        "needs_ai": needs_ai,
                        "needs_beginner": needs_beginner,
                        "needs_expert": needs_expert,
                    })
                except Exception as e:
                    print(f"❌ 准备函数 {func.get('name', 'unknown')} 失败: {e}")
                    continue

            # ── Check cache for LLM results before making API calls ──
            for w in func_work_items:
                if w["needs_ai"]:
                    cached = lookup_cached_metadata(db, w["code_hash"], "ai")
                    if cached:
                        w["cached_ai"] = cached
                        w["needs_ai"] = False
                        print(f"📦 缓存命中(AI): {w['func']['name']}")
                if w["needs_beginner"]:
                    cached = lookup_cached_metadata(db, w["code_hash"], "beginner")
                    if cached:
                        w["cached_beginner"] = cached
                        w["needs_beginner"] = False
                        print(f"📦 缓存命中(Beginner): {w['func']['name']}")
                if w["needs_expert"]:
                    cached = lookup_cached_metadata(db, w["code_hash"], "expert")
                    if cached:
                        w["cached_expert"] = cached
                        w["needs_expert"] = False
                        print(f"📦 缓存命中(Expert): {w['func']['name']}")

            # ── Batch process AI metadata in parallel ──
            ai_inputs = [(w["code_snippet"], "function", w["lang"]) for w in func_work_items if w["needs_ai"]]
            ai_outputs = generate_ai_metadata_batch(ai_inputs) if ai_inputs else []

            # ── Batch process beginner/expert content in parallel ──
            beginner_inputs = [(w["code_snippet"], "function", w["lang"]) for w in func_work_items if w["needs_beginner"]]
            expert_inputs = [(w["code_snippet"], "function", w["lang"]) for w in func_work_items if w["needs_expert"]]

            if beginner_inputs:
                with ThreadPoolExecutor(max_workers=5) as executor:
                    beginner_outputs = list(executor.map(lambda args: generate_explanation(*args), beginner_inputs))
            else:
                beginner_outputs = []

            if expert_inputs:
                with ThreadPoolExecutor(max_workers=5) as executor:
                    expert_outputs = list(executor.map(lambda args: generate_expert_analysis(*args), expert_inputs))
            else:
                expert_outputs = []

            ai_iter = iter(ai_outputs)
            beginner_iter = iter(beginner_outputs)
            expert_iter = iter(expert_outputs)

            # Helper to get result: check cache first, then fall back to batch LLM output
            def _get_ai_result(w: dict) -> dict | None:
                if "cached_ai" in w:
                    return w["cached_ai"]
                if w["needs_ai"]:
                    return next(ai_iter, {})
                return None

            def _get_beginner_result(w: dict) -> dict | None:
                if "cached_beginner" in w:
                    return w["cached_beginner"]
                if w["needs_beginner"]:
                    return next(beginner_iter, {})
                return None

            def _get_expert_result(w: dict) -> dict | None:
                if "cached_expert" in w:
                    return w["cached_expert"]
                if w["needs_expert"]:
                    return next(expert_iter, {})
                return None

            # ── Create/update DB records with parallel results ──
            for work_item in func_work_items:
                func = work_item["func"]
                code_snippet = work_item["code_snippet"]
                code_hash = work_item["code_hash"]
                existing_func = work_item["existing_func"]

                try:
                    ai_meta = _get_ai_result(work_item)

                    # Case 1: Update existing function
                    if existing_func and existing_func.ai_purpose:
                        print(f"🔄 补充{project.analysis_mode}内容: {func['name']}")
                        if ai_meta:
                            existing_func.ai_purpose = ai_meta.get("purpose")
                            existing_func.ai_inputs = ai_meta.get("inputs")
                            existing_func.ai_outputs = ai_meta.get("outputs")
                            existing_func.ai_side_effects = ai_meta.get("side_effects")
                            existing_func.return_type = ai_meta.get("outputs", {}).get("type") if ai_meta.get("outputs") else None
                            existing_func.code_snippet = code_snippet

                        beginner_result = _get_beginner_result(work_item)
                        if beginner_result:
                            existing_func.explanation_simple = beginner_result.get("simple")
                            existing_func.explanation_logic = beginner_result.get("logic")

                        expert_result = _get_expert_result(work_item)
                        if expert_result:
                            existing_func.expert_purpose = expert_result.get("purpose")
                            existing_func.expert_tech_details = expert_result.get("tech_details")
                            existing_func.expert_error_handling = expert_result.get("error_handling")
                            existing_func.expert_concurrency = expert_result.get("concurrency")
                            existing_func.expert_tradeoffs = expert_result.get("tradeoffs")

                        existing_func.code_hash = code_hash
                        db.commit()
                        continue

                    # Case 2: Create new function
                    ai_purpose = ai_meta.get("purpose") if ai_meta else None
                    ai_inputs_val = ai_meta.get("inputs") if ai_meta else None
                    ai_outputs_val = ai_meta.get("outputs") if ai_meta else None
                    ai_side_effects = ai_meta.get("side_effects") if ai_meta else None
                    return_type = ai_meta.get("outputs", {}).get("type") if ai_meta and ai_meta.get("outputs") else None

                    created_func = crud.create_function(
                        db, file_obj.id,
                        func["name"], func["signature"],
                        func["start_line"], func["end_line"],
                        func["docstring"],
                        code_snippet=code_snippet,
                        code_hash=code_hash,
                        ai_purpose=ai_purpose,
                        ai_inputs=ai_inputs_val,
                        ai_outputs=ai_outputs_val,
                        ai_side_effects=ai_side_effects,
                        return_type=return_type,
                        language=lang
                    )

                    beginner_result = _get_beginner_result(work_item)
                    if beginner_result:
                        try:
                            crud.update_function_explanation(
                                db, created_func.id,
                                beginner_result.get("simple"), beginner_result.get("logic")
                            )
                        except Exception as ex:
                            print(f"⚠️ 生成小白解释失败 {func['name']}: {ex}")

                    expert_result = _get_expert_result(work_item)
                    if expert_result:
                        try:
                            crud.update_function_expert(
                                db, created_func.id,
                                expert_purpose=expert_result.get("purpose"),
                                expert_tech_details=expert_result.get("tech_details"),
                                expert_error_handling=expert_result.get("error_handling"),
                                expert_concurrency=expert_result.get("concurrency"),
                                expert_tradeoffs=expert_result.get("tradeoffs"),
                            )
                        except Exception as ex:
                            print(f"⚠️ 生成专家分析失败 {func['name']}: {ex}")
                except Exception as e:
                    print(f"❌ 处理函数 {func.get('name', 'unknown')} 失败: {e}")
                    continue

            # ── Generate embeddings for newly created functions ──
            if embedding_enabled():
                pending = []
                for func_entry in parse_result.get("functions", []):
                    try:
                        db_func = db.query(models.Function).filter(
                            models.Function.file_id == file_obj.id,
                            models.Function.name == func_entry["name"],
                            models.Function.start_line == func_entry["start_line"]
                        ).first()
                        if db_func and db_func.embedding is None:
                            pending.append(db_func)
                    except Exception:
                        pass
                if pending:
                    func_data_list = [{
                        "name": f.name,
                        "signature": f.signature,
                        "docstring": f.docstring,
                        "code_snippet": f.code_snippet,
                        "ai_purpose": f.ai_purpose,
                    } for f in pending]
                    embeddings = generate_function_embeddings_batch(func_data_list)
                    for func_obj, emb in zip(pending, embeddings):
                        if emb is not None:
                            func_obj.embedding = emb
                    try:
                        db.commit()
                    except Exception:
                        db.rollback()

            # ── Collect class work items ──
            class_work_items = []
            for cls in parse_result["classes"]:
                try:
                    with open(full_path, 'r', encoding='utf-8') as f:
                        lines = f.readlines()
                        code_snippet = ''.join(lines[cls["start_line"] - 1:cls["end_line"]])

                    # Create function records for methods with code_snippet and language
                    for method in cls["methods"]:
                        method_snippet = ''.join(lines[method["start_line"] - 1:method["end_line"]])
                        crud.create_function(
                            db, file_obj.id, method["name"], method["signature"],
                            method["start_line"], method["end_line"], method["docstring"],
                            code_snippet=method_snippet, language=lang
                        )

                    existing_class = db.query(models.Class).filter(
                        models.Class.file_id == file_obj.id,
                        models.Class.name == cls["name"]
                    ).first()

                    can_skip = False
                    if existing_class and existing_class.ai_purpose:
                        if project.analysis_mode == "beginner" and existing_class.explanation_simple:
                            print(f"⏭️ 跳过已分析类(Beginner): {cls['name']}")
                            can_skip = True
                        elif project.analysis_mode == "expert" and existing_class.expert_purpose:
                            print(f"⏭️ 跳过已分析类(Expert): {cls['name']}")
                            can_skip = True
                        elif project.analysis_mode == "ai":
                            print(f"⏭️ 跳过已分析类(AI): {cls['name']}")
                            can_skip = True

                    if can_skip:
                        continue

                    needs_ai = not (existing_class and existing_class.ai_purpose)
                    needs_beginner = project.analysis_mode == "beginner" and not (existing_class and existing_class.explanation_simple)
                    needs_expert = project.analysis_mode == "expert" and not (existing_class and existing_class.expert_purpose)

                    class_work_items.append({
                        "cls": cls,
                        "code_snippet": code_snippet,
                        "existing_class": existing_class,
                        "lang": lang,
                        "needs_ai": needs_ai,
                        "needs_beginner": needs_beginner,
                        "needs_expert": needs_expert,
                    })
                except Exception as e:
                    print(f"❌ 准备类 {cls.get('name', 'unknown')} 失败: {e}")
                    continue

            # ── Batch process AI metadata in parallel ──
            ai_inputs = [(w["code_snippet"], "class", w["lang"]) for w in class_work_items if w["needs_ai"]]
            ai_outputs = generate_ai_metadata_batch(ai_inputs) if ai_inputs else []

            # ── Batch process beginner/expert content in parallel ──
            beginner_inputs = [(w["code_snippet"], "class", w["lang"]) for w in class_work_items if w["needs_beginner"]]
            expert_inputs = [(w["code_snippet"], "class", w["lang"]) for w in class_work_items if w["needs_expert"]]

            if beginner_inputs:
                with ThreadPoolExecutor(max_workers=5) as executor:
                    beginner_outputs = list(executor.map(lambda args: generate_explanation(*args), beginner_inputs))
            else:
                beginner_outputs = []

            if expert_inputs:
                with ThreadPoolExecutor(max_workers=5) as executor:
                    expert_outputs = list(executor.map(lambda args: generate_expert_analysis(*args), expert_inputs))
            else:
                expert_outputs = []

            ai_iter = iter(ai_outputs)
            beginner_iter = iter(beginner_outputs)
            expert_iter = iter(expert_outputs)

            # ── Create/update DB records with parallel results ──
            for work_item in class_work_items:
                cls = work_item["cls"]
                code_snippet = work_item["code_snippet"]
                existing_class = work_item["existing_class"]

                try:
                    if work_item["needs_ai"]:
                        ai_meta = next(ai_iter, {})
                    else:
                        ai_meta = None

                    # Case 1: Update existing class
                    if existing_class and existing_class.ai_purpose:
                        print(f"🔄 补充{project.analysis_mode}内容: {cls['name']}")
                        if ai_meta:
                            existing_class.ai_purpose = ai_meta.get("purpose")
                            existing_class.ai_interfaces = ai_meta.get("interfaces")
                            existing_class.code_snippet = code_snippet

                        if work_item["needs_beginner"]:
                            explanation = next(beginner_iter, {})
                            existing_class.explanation_simple = explanation.get("simple")
                            existing_class.explanation_architecture = explanation.get("logic")
                        elif work_item["needs_expert"]:
                            expert = next(expert_iter, {})
                            existing_class.expert_purpose = expert.get("purpose")
                            existing_class.expert_architecture = expert.get("architecture")
                            existing_class.expert_responsibilities = expert.get("responsibilities")
                            existing_class.expert_extension_points = expert.get("extension_points")

                        db.commit()
                        continue

                    # Case 2: Create new class
                    ai_purpose = ai_meta.get("purpose") if ai_meta else None
                    ai_interfaces = ai_meta.get("interfaces") if ai_meta else None

                    cls_obj = crud.create_class(
                        db, file_obj.id,
                        cls["name"], cls["start_line"], cls["end_line"], cls["docstring"],
                        code_snippet=code_snippet,
                        ai_purpose=ai_purpose,
                        ai_interfaces=ai_interfaces,
                    )

                    if work_item["needs_beginner"]:
                        try:
                            explanation = next(beginner_iter, {})
                            cls_obj.explanation_simple = explanation.get("simple")
                            cls_obj.explanation_architecture = explanation.get("logic")
                            db.commit()
                        except Exception as ex:
                            print(f"⚠️ 生成类小白解释失败 {cls['name']}: {ex}")
                    elif work_item["needs_expert"]:
                        try:
                            expert = next(expert_iter, {})
                            crud.update_class_expert(
                                db, cls_obj.id,
                                expert_purpose=expert.get("purpose"),
                                expert_architecture=expert.get("architecture"),
                                expert_responsibilities=expert.get("responsibilities"),
                                expert_extension_points=expert.get("extension_points"),
                            )
                        except Exception as ex:
                            print(f"⚠️ 生成类专家分析失败 {cls['name']}: {ex}")
                except Exception as e:
                    print(f"❌ 处理类 {cls.get('name', 'unknown')} 失败: {e}")
                    continue

            # ---- 存储 CALLS 调用关系 ----
            try:
                # 构建当前文件中函数名→ID的映射
                name_to_id = {}
                for f in db.query(models.Function).filter(
                    models.Function.file_id == file_obj.id
                ).all():
                    name_to_id[f.name] = f.id

                for call_entry in parse_result.get("calls", []):
                    source_id = name_to_id.get(call_entry["source"])
                    if not source_id:
                        continue
                    # 尽量在同一项目中查找目标函数
                    target_func = db.query(models.Function).filter(
                        models.Function.name == call_entry["target"]
                    ).join(models.File).filter(
                        models.File.project_id == project.id
                    ).first()

                    crud.create_relationship(
                        db, source_id, call_entry["target"],
                        target_func.file_id if target_func else None,
                        "CALLS", 5, call_entry.get("line")
                    )
            except Exception as e:
                print(f"❌ 存储调用关系失败: {e}")
                # 不中断主流程

            # ---- 存储 IMPORTS 导入关系 ----
            try:
                if parse_result.get("imports") and name_to_id:
                    first_func_id = list(name_to_id.values())[0]
                    for imp in parse_result["imports"]:
                        try:
                            crud.create_relationship(
                                db, first_func_id, imp["target"],
                                None, "IMPORTS", 3, imp.get("line")
                            )
                        except Exception:
                            pass  # 单个导入失败不中断
            except Exception as e:
                print(f"⚠️ 存储导入关系失败: {e}")

            # ---- 存储 EXTENDS 继承关系 ----
            try:
                for ext in parse_result.get("extends", []):
                    source_id = name_to_id.get(ext["class"])
                    if source_id:
                        try:
                            crud.create_relationship(
                                db, source_id, ext["parent"],
                                None, "EXTENDS", 5, ext.get("line")
                            )
                        except Exception:
                            pass
            except Exception as e:
                print(f"⚠️ 存储继承关系失败: {e}")

            # 保存检查点：标记当前文件为已处理
            processed_files.add(rel_path)
            save_checkpoint(db, task_id, list(processed_files), rel_path, total_files)
            print(f"✅ 已处理并保存进度: {rel_path} ({len(processed_files)}/{total_files})")

        # 所有文件解析完成，准备生成整体解读，进度85%
        crud.update_task_status(db, task_id, "running", current_step="generating_overview", progress_percent=85)
        self.update_state(state='PROGRESS', meta={'current_step': 'generating_overview', 'progress': 85})
        publish_progress(task_id, "generating_overview", 85, "generating project overview")

        # 检查是否已存在整体解读
        if not project.overview_analysis or is_resuming:
            # 收集项目摘要信息用于整体解读
            files_summary = []
            for file_obj in db.query(models.File).filter(models.File.project_id == project.id).all():
                functions = db.query(models.Function).filter(models.Function.file_id == file_obj.id).all()
                classes = db.query(models.Class).filter(models.Class.file_id == file_obj.id).all()

                func_names = [f.name for f in functions]
                class_names = [c.name for c in classes]
                doc_summary = ""
                if functions and functions[0].docstring:
                    doc_summary = functions[0].docstring[:200]
                elif classes and classes[0].docstring:
                    doc_summary = classes[0].docstring[:200]

                files_summary.append({
                    "path": file_obj.file_path,
                    "functions": func_names,
                    "classes": class_names,
                    "docstring_summary": doc_summary
                })

            # 调用 LLM 生成整体解读（根据模式选择对应风格的解读）
            if mode == "beginner":
                overview_text = generate_beginner_overview(project.name, files_summary)
            elif mode == "expert":
                overview_text = generate_expert_overview(project.name, files_summary)
            else:
                overview_text = generate_project_overview(project.name, files_summary)

            # 更新项目记录
            project.overview_analysis = overview_text
            project.overview_analysis_updated_at = datetime.now()
            db.commit()
        else:
            print("⏭️ 跳过整体解读生成（已存在）")

        # 生成报告，进度90%
        self.update_state(state='PROGRESS', meta={'current_step': 'generating_report', 'progress': 90})
        crud.update_task_status(db, task_id, "running", current_step="generating_report", progress_percent=90)
        publish_progress(task_id, "generating_report", 90, "generating project report")

        report_path = os.path.join(config.TEMP_DIR, f"report_{task_id}.md")
        report_generator.generate_project_report(db, project.id, report_path)

        # 任务完成，进度100%
        crud.update_task_status(db, task_id, "completed", progress_percent=100)
        publish_progress(task_id, "completed", 100, "analysis complete")

        # 清空检查点数据（任务已完成，不再需要）
        task.processed_files = []
        task.last_processed_file = None
        db.commit()

        print(f"🎉 任务 {task_id} 完成！")

        return {"task_id": task_id, "report_path": report_path, "status": "completed"}

    except Exception as e:
        error_msg = str(e)
        print(f"❌ 任务 {task_id} 失败: {error_msg}")

        # 保存检查点（失败时也保存进度）
        if 'processed_files' in locals():
            save_checkpoint(db, task_id, list(processed_files) if processed_files else [],
                            last_file=locals().get('rel_path'), total_files=locals().get('total_files'))

        crud.update_task_status(db, task_id, "failed", error_message=error_msg)
        publish_progress(task_id, "failed", 0, current_step=f"failed: {error_msg[:100]}")
        raise e
    finally:
        db.rollback()
        db.close()


@celery_app.task(bind=True, name="fill_project_mode_content", max_retries=2)
def fill_project_mode_content(self, project_id: int):
    """
    Lightweight task: fill mode-specific LLM content for a project without re-cloning.

    Detects the project's analysis_mode and generates missing LLM content
    for all existing functions/classes. AI metadata is always generated if missing.
    """
    db = SessionLocal()
    try:
        project = db.query(models.Project).filter(models.Project.id == project_id).first()
        if not project:
            print(f"❌ fill_project_mode_content: Project {project_id} not found")
            return {"status": "error", "message": "Project not found"}

        mode = project.analysis_mode or "ai"
        print(f"📝 fill_project_mode_content: project={project.name}, mode={mode}")

        processed_funcs = 0
        processed_classes = 0
        errors = 0

        # ── Functions ──
        funcs = (
            db.query(models.Function)
            .join(models.File)
            .filter(
                models.File.project_id == project_id,
                models.Function.code_snippet.isnot(None),
            )
            .all()
        )

        def _process_func(func, mode, project_name_for_log):
            """Process a single function in its own DB session (for parallel execution)."""
            db2 = SessionLocal()
            try:
                ref_func = db2.query(models.Function).filter(models.Function.id == func.id).first()
                if not ref_func:
                    db2.close()
                    return False

                file_obj = db2.query(models.File).filter(models.File.id == ref_func.file_id).first()
                lang = file_obj.language if file_obj else "python"

                # Always ensure AI metadata
                if not ref_func.ai_purpose:
                    ai_meta = generate_ai_metadata(ref_func.code_snippet, "function", lang)
                    ref_func.ai_purpose = ai_meta.get("purpose")
                    ref_func.ai_inputs = ai_meta.get("inputs")
                    ref_func.ai_outputs = ai_meta.get("outputs")
                    ref_func.ai_side_effects = ai_meta.get("side_effects")
                    outputs = ai_meta.get("outputs", {})
                    if outputs and isinstance(outputs, dict):
                        ref_func.return_type = outputs.get("type")

                # Mode-specific content
                if mode == "beginner" and not ref_func.explanation_simple:
                    result = generate_explanation(ref_func.code_snippet, "function", lang)
                    ref_func.explanation_simple = result.get("simple")
                    ref_func.explanation_logic = result.get("logic")
                elif mode == "expert" and not ref_func.expert_purpose:
                    result = generate_expert_analysis(ref_func.code_snippet, "function", lang)
                    ref_func.expert_purpose = result.get("purpose")
                    ref_func.expert_tech_details = result.get("tech_details")
                    ref_func.expert_error_handling = result.get("error_handling")
                    ref_func.expert_concurrency = result.get("concurrency")
                    ref_func.expert_tradeoffs = result.get("tradeoffs")

                db2.commit()
                db2.close()
                return True
            except Exception as e:
                db2.rollback()
                db2.close()
                return False

        total_funcs = len(funcs)
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(_process_func, func, mode, project.name): func for func in funcs}
            for i, future in enumerate(as_completed(futures), 1):
                if future.result():
                    processed_funcs += 1
                else:
                    errors += 1
                if i % 50 == 0 or i == total_funcs:
                    print(f"  📊 函数进度: {i}/{total_funcs} (错误: {errors})")

        # ── Classes ──
        classes = (
            db.query(models.Class)
            .join(models.File)
            .filter(
                models.File.project_id == project_id,
                models.Class.code_snippet.isnot(None),
            )
            .all()
        )

        def _process_class(cls_obj, mode, project_name_for_log):
            """Process a single class in its own DB session (for parallel execution)."""
            db2 = SessionLocal()
            try:
                ref_cls = db2.query(models.Class).filter(models.Class.id == cls_obj.id).first()
                if not ref_cls:
                    db2.close()
                    return False

                file_obj = db2.query(models.File).filter(models.File.id == ref_cls.file_id).first()
                lang = file_obj.language if file_obj else "python"

                # Always ensure AI metadata
                if not ref_cls.ai_purpose:
                    ai_meta = generate_ai_metadata(ref_cls.code_snippet, "class", lang)
                    ref_cls.ai_purpose = ai_meta.get("purpose")
                    ref_cls.ai_inputs = ai_meta.get("inputs")
                    ref_cls.ai_outputs = ai_meta.get("outputs")
                    ref_cls.ai_side_effects = ai_meta.get("side_effects")

                # Mode-specific content
                if mode == "beginner" and not ref_cls.explanation_simple:
                    result = generate_explanation(ref_cls.code_snippet, "class", lang)
                    ref_cls.explanation_simple = result.get("simple")
                    ref_cls.explanation_logic = result.get("logic")
                elif mode == "expert" and not ref_cls.expert_purpose:
                    result = generate_expert_analysis(ref_cls.code_snippet, "class", lang)
                    ref_cls.expert_purpose = result.get("purpose")
                    ref_cls.expert_architecture = result.get("architecture")
                    ref_cls.expert_responsibilities = result.get("responsibilities")
                    ref_cls.expert_extension_points = result.get("extension_points")

                db2.commit()
                db2.close()
                return True
            except Exception as e:
                db2.rollback()
                db2.close()
                return False

        total_classes = len(classes)
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(_process_class, cls, mode, project.name): cls for cls in classes}
            for i, future in enumerate(as_completed(futures), 1):
                if future.result():
                    processed_classes += 1
                else:
                    errors += 1
                if i % 50 == 0 or i == total_classes:
                    print(f"  📊 类进度: {i}/{total_classes} (错误: {errors})")

        print(f"✅ fill_project_mode_content done: {processed_funcs} funcs, {processed_classes} classes, {errors} errors")
        return {
            "status": "completed",
            "processed_funcs": processed_funcs,
            "processed_classes": processed_classes,
            "errors": errors,
        }

    except Exception as e:
        print(f"❌ fill_project_mode_content failed: {e}")
        db.rollback()
        raise e
    finally:
        db.close()


@celery_app.task(bind=True, name="fill_ai_metadata_bulk")
def fill_ai_metadata_bulk(self, project_ids: list[int], batch_size: int = 15, max_workers: int = 10):
    """
    Backfill AI metadata in bulk for multiple projects.

    Uses generate_ai_metadata_bulk() to process 10-15 functions per LLM call,
    with parallel ThreadPoolExecutor workers for much higher throughput
    than per-function processing.

    Args:
        project_ids: List of project IDs to backfill.
        batch_size: Functions per bulk LLM call (default 15).
        max_workers: Parallel bulk call workers (default 10).
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from api.llm_service import generate_ai_metadata_bulk

    db = SessionLocal()
    try:
        projects = db.query(models.Project).filter(
            models.Project.id.in_(project_ids)
        ).all()

        if not projects:
            return {"status": "error", "message": f"No projects found: {project_ids}"}

        total_ok = 0
        total_err = 0

        for proj in projects:
            from sqlalchemy import or_
            missing = (
                db.query(models.Function)
                .join(models.File)
                .filter(
                    models.File.project_id == proj.id,
                    or_(
                        models.Function.ai_purpose.is_(None),
                        models.Function.ai_purpose == "",
                    ),
                    models.Function.code_snippet.isnot(None),
                )
                .all()
            )

            if not missing:
                print(f"[{proj.name}] No missing AI metadata")
                continue

            print(f"[{proj.name}] Processing {len(missing)} functions "
                  f"(batch_size={batch_size}, workers={max_workers})...")
            processed = 0
            errors = 0

            # Build func-snippet pairs
            all_items = []
            for func in missing:
                file_obj = db.query(models.File).filter(
                    models.File.id == func.file_id
                ).first()
                lang = file_obj.language if file_obj else "python"
                all_items.append((func, (func.code_snippet, "function", lang)))

            # Process in chunks with periodic DB commit
            chunk_size = batch_size * max_workers * 4
            for chunk_start in range(0, len(all_items), chunk_size):
                chunk = all_items[chunk_start:chunk_start + chunk_size]

                # Group into sub-batches
                sub_batches = []
                for i in range(0, len(chunk), batch_size):
                    batch_items = chunk[i:i + batch_size]
                    funcs = [item[0] for item in batch_items]
                    snippets = [item[1] for item in batch_items]
                    sub_batches.append((funcs, snippets))

                # Process sub-batches in parallel
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    futures = {
                        executor.submit(_bulk_fill_worker, sb): sb
                        for sb in sub_batches
                    }
                    for future in as_completed(futures):
                        p, e = future.result()
                        processed += p
                        errors += e

                done = min(chunk_start + chunk_size, len(all_items))
                print(f"  [{proj.name}] {done}/{len(all_items)} - "
                      f"{processed} ok, {errors} err")

            total_ok += processed
            total_err += errors
            print(f"[{proj.name}] COMPLETE: {processed} ok, {errors} err")

        return {
            "status": "completed",
            "processed": total_ok,
            "errors": total_err,
        }

    except Exception as e:
        print(f"❌ fill_ai_metadata_bulk failed: {e}")
        raise e
    finally:
        db.close()


def _bulk_fill_worker(args):
    """Process a sub-batch of functions via bulk LLM.
    Runs in its own thread with its own DB session."""
    func_objects, snippets = args
    from api.database import SessionLocal
    from api import models
    from api.llm_service import generate_ai_metadata_bulk

    db = SessionLocal()
    try:
        results = generate_ai_metadata_bulk(snippets, batch_size=len(snippets))
        processed = 0
        errors = 0
        for func_obj, ai_meta in zip(func_objects, results):
            try:
                func = db.query(models.Function).filter(
                    models.Function.id == func_obj.id
                ).first()
                if func and ai_meta and ai_meta.get("purpose"):
                    func.ai_purpose = ai_meta.get("purpose")
                    func.ai_inputs = ai_meta.get("inputs")
                    func.ai_outputs = ai_meta.get("outputs")
                    func.ai_side_effects = ai_meta.get("side_effects")
                    outputs = ai_meta.get("outputs", {})
                    if outputs and isinstance(outputs, dict):
                        func.return_type = outputs.get("type")
                    processed += 1
                else:
                    errors += 1
            except Exception:
                errors += 1
        db.commit()
        return processed, errors
    except Exception:
        db.rollback()
        return 0, len(func_objects)
    finally:
        db.close()