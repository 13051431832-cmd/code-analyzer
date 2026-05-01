from sqlalchemy.orm import Session
from . import models
from sqlalchemy.sql import func
from datetime import datetime


# ========== 原有函数 ==========

def create_project(db: Session, name: str, repo_url: str = None, language: str = None, analysis_mode: str = "ai") -> models.Project:
    project = models.Project(name=name, repo_url=repo_url, language=language, analysis_mode=analysis_mode)
    db.add(project)
    db.commit()
    db.refresh(project)
    return project

def get_project(db: Session, project_id: int) -> models.Project:
    return db.query(models.Project).filter(models.Project.id == project_id).first()

def delete_project(db: Session, project_id: int) -> bool:
    """删除项目及其关联数据（CASCADE 会自动清理 files/functions/classes/relationships）"""
    project = db.query(models.Project).filter(models.Project.id == project_id).first()
    if not project:
        return False
    # 需手动清理 analysis_tasks（无 CASCADE）
    db.query(models.AnalysisTask).filter(models.AnalysisTask.project_id == project_id).delete()
    db.delete(project)
    db.commit()
    return True

def create_file(db: Session, project_id: int, file_path: str, file_hash: str, size_bytes: int, language: str) -> models.File:
    file = models.File(
        project_id=project_id,
        file_path=file_path,
        file_hash=file_hash,
        size_bytes=size_bytes,
        language=language
    )
    db.add(file)
    db.commit()
    db.refresh(file)
    return file

def create_function(db: Session, file_id: int, name: str, signature: str, start_line: int, end_line: int, docstring: str,
                    explanation_simple: str = None, explanation_logic: str = None, code_snippet: str = None,
                    code_hash: str = None, language: str = None,
                    ai_purpose: str = None, ai_inputs: list = None, ai_outputs: dict = None,
                    ai_side_effects: list = None, return_type: str = None, **kwargs) -> models.Function:
    func = models.Function(
        file_id=file_id,
        name=name,
        language=language,
        signature=signature,
        start_line=start_line,
        end_line=end_line,
        docstring=docstring,
        explanation_simple=explanation_simple,
        explanation_logic=explanation_logic,
        code_snippet=code_snippet,
        code_hash=code_hash,
        ai_purpose=ai_purpose,
        ai_inputs=ai_inputs,
        ai_outputs=ai_outputs,
        ai_side_effects=ai_side_effects,
        return_type=return_type,
        llm_description=kwargs.get("llm_description"),
        llm_issues=kwargs.get("llm_issues"),
        llm_processed=kwargs.get("llm_processed", False),
        embedding_id=kwargs.get("embedding_id")
    )
    db.add(func)
    db.commit()
    db.refresh(func)
    return func

def create_class(db: Session, file_id: int, name: str, start_line: int, end_line: int, docstring: str,
                 explanation_simple: str = None, explanation_architecture: str = None,
                 code_snippet: str = None,
                 ai_purpose: str = None, ai_interfaces: list = None) -> models.Class:
    cls = models.Class(
        file_id=file_id,
        name=name,
        start_line=start_line,
        end_line=end_line,
        docstring=docstring,
        explanation_simple=explanation_simple,
        explanation_architecture=explanation_architecture,
        code_snippet=code_snippet,
        ai_purpose=ai_purpose,
        ai_interfaces=ai_interfaces,
    )
    db.add(cls)
    db.commit()
    db.refresh(cls)
    return cls

def create_task(db: Session, project_id: int = None) -> models.AnalysisTask:
    """创建分析任务记录，支持断点续传字段初始化"""
    task = models.AnalysisTask(
        project_id=project_id,
        status="pending",
        processed_files=[],      # 初始化已处理文件列表
        total_files=0,           # 初始化总文件数
        progress_percent=0       # 初始化进度
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task

def update_task_status(db: Session, task_id: int, status: str, current_step: str = None,
                       error_message: str = None, progress_percent: int = None):
    task = db.query(models.AnalysisTask).filter(models.AnalysisTask.id == task_id).first()
    if task:
        task.status = status
        if current_step:
            task.current_step = current_step
        if error_message:
            task.error_message = error_message
        if progress_percent is not None:
            task.progress_percent = progress_percent
        if status == "running" and not task.started_at:
            task.started_at = func.now()
        if status in ("completed", "failed"):
            task.finished_at = func.now()
        db.commit()

def get_file_by_path(db: Session, project_id: int, file_path: str) -> models.File:
    return db.query(models.File).filter(
        models.File.project_id == project_id,
        models.File.file_path == file_path
    ).first()

def get_function_by_id(db: Session, function_id: int) -> models.Function:
    """根据ID获取函数"""
    return db.query(models.Function).filter(models.Function.id == function_id).first()

def update_function_explanation(db: Session, function_id: int,
                                explanation_simple: str = None,
                                explanation_logic: str = None) -> models.Function:
    """更新函数的AI解释"""
    func = db.query(models.Function).filter(models.Function.id == function_id).first()
    if func:
        if explanation_simple:
            func.explanation_simple = explanation_simple
        if explanation_logic:
            func.explanation_logic = explanation_logic
        db.commit()
        db.refresh(func)
    return func


# ========== 新增函数（供路由使用） ==========

def get_projects(db: Session, skip: int = 0, limit: int = 100):
    """获取所有项目列表"""
    return db.query(models.Project).offset(skip).limit(limit).all()

def get_files_by_project(db: Session, project_id: int):
    """获取项目下的所有文件（不包含函数）"""
    return db.query(models.File).filter(models.File.project_id == project_id).all()

def get_functions_by_file(db: Session, file_id: int):
    """获取某个文件下的所有函数"""
    return db.query(models.Function).filter(models.Function.file_id == file_id).all()

def get_analysis_progress(db: Session, project_id: int):
    """获取项目的最新分析任务进度"""
    task = db.query(models.AnalysisTask).filter(
        models.AnalysisTask.project_id == project_id
    ).order_by(models.AnalysisTask.id.desc()).first()
    if not task:
        return None
    return {
        "status": task.status,
        "progress": task.progress_percent or 0,
        "current_step": task.current_step or "",
        "error_message": task.error_message
    }

def update_project_mode(db: Session, project_id: int, mode: str) -> models.Project:
    """切换项目的分析模式"""
    project = db.query(models.Project).filter(models.Project.id == project_id).first()
    if project:
        project.analysis_mode = mode
        db.commit()
        db.refresh(project)
    return project


def get_project_overview(db: Session, project_id: int) -> str:
    """获取项目整体解读（Markdown）"""
    project = db.query(models.Project).filter(models.Project.id == project_id).first()
    if project and project.overview_analysis:
        return project.overview_analysis
    return "暂无整体解读，请等待项目分析完成。"

def update_function_expert(db: Session, function_id: int,
                           expert_purpose: str = None,
                           expert_tech_details: str = None,
                           expert_error_handling: str = None,
                           expert_concurrency: str = None,
                           expert_tradeoffs: str = None) -> models.Function:
    """更新函数的专家模式分析字段"""
    func = db.query(models.Function).filter(models.Function.id == function_id).first()
    if func:
        if expert_purpose is not None:
            func.expert_purpose = expert_purpose
        if expert_tech_details is not None:
            func.expert_tech_details = expert_tech_details
        if expert_error_handling is not None:
            func.expert_error_handling = expert_error_handling
        if expert_concurrency is not None:
            func.expert_concurrency = expert_concurrency
        if expert_tradeoffs is not None:
            func.expert_tradeoffs = expert_tradeoffs
        db.commit()
        db.refresh(func)
    return func


def update_class_expert(db: Session, class_id: int,
                        expert_purpose: str = None,
                        expert_architecture: str = None,
                        expert_responsibilities: str = None,
                        expert_extension_points: str = None) -> models.Class:
    """更新类的专家模式分析字段"""
    cls = db.query(models.Class).filter(models.Class.id == class_id).first()
    if cls:
        if expert_purpose is not None:
            cls.expert_purpose = expert_purpose
        if expert_architecture is not None:
            cls.expert_architecture = expert_architecture
        if expert_responsibilities is not None:
            cls.expert_responsibilities = expert_responsibilities
        if expert_extension_points is not None:
            cls.expert_extension_points = expert_extension_points
        db.commit()
        db.refresh(cls)
    return cls


def get_latest_task_by_project(db: Session, project_id: int):
    """获取项目最新的分析任务"""
    return db.query(models.AnalysisTask).filter(
        models.AnalysisTask.project_id == project_id
    ).order_by(models.AnalysisTask.id.desc()).first()

def get_task_by_id(db: Session, task_id: int):
    """根据ID获取任务"""
    return db.query(models.AnalysisTask).filter(models.AnalysisTask.id == task_id).first()

def update_task_checkpoint(db: Session, task_id: int, processed_files: list = None,
                           last_file: str = None, total_files: int = None,
                           checkpoint_data: dict = None):
    """更新任务的检查点信息"""
    task = db.query(models.AnalysisTask).filter(models.AnalysisTask.id == task_id).first()
    if task:
        if processed_files is not None:
            task.processed_files = processed_files
        if last_file is not None:
            task.last_processed_file = last_file
        if total_files is not None:
            task.total_files = total_files
        if checkpoint_data is not None:
            task.checkpoint_data = checkpoint_data
        db.commit()
        db.refresh(task)
    return task

def get_unfinished_tasks(db: Session):
    """获取所有未完成的任务（用于断点续传恢复）"""
    return db.query(models.AnalysisTask).filter(
        models.AnalysisTask.status.in_(["pending", "running", "failed"])
    ).order_by(models.AnalysisTask.created_at.desc()).all()


# ========== 函数关系（调用图）相关函数 ==========

def create_relationship(db: Session, source_function_id: int, target_function_name: str,
                        target_file_id: int = None, relationship_type: str = "CALLS",
                        confidence: int = 5, context_line: int = None) -> models.FunctionRelationship:
    """创建函数间关系"""
    rel = models.FunctionRelationship(
        source_function_id=source_function_id,
        target_function_name=target_function_name,
        target_file_id=target_file_id,
        relationship_type=relationship_type,
        confidence=confidence,
        context_line=context_line,
    )
    db.add(rel)
    db.commit()
    db.refresh(rel)
    return rel


def get_callers(db: Session, function_id: int, limit: int = 20) -> list[dict]:
    """查询调用此函数的所有函数（调用者）"""
    func = db.query(models.Function).filter(models.Function.id == function_id).first()
    if not func:
        return []

    # 找到所有 relationship_type='CALLS' 且 target_function_name=func.name 的关系
    rows = (
        db.query(models.FunctionRelationship, models.Function)
        .join(models.Function, models.Function.id == models.FunctionRelationship.source_function_id)
        .filter(
            models.FunctionRelationship.target_function_name == func.name,
            models.FunctionRelationship.relationship_type == "CALLS",
        )
        .limit(limit)
        .all()
    )

    return [
        {
            "function_id": f.id,
            "name": f.name,
            "signature": f.signature,
            "file_path": db.query(models.File).filter(models.File.id == f.file_id).value(models.File.file_path),
            "context_line": rel.context_line,
            "confidence": rel.confidence,
        }
        for rel, f in rows
    ]


def get_callees(db: Session, function_id: int, limit: int = 20) -> list[dict]:
    """查询此函数调用了哪些函数（被调用者）"""
    rows = (
        db.query(models.FunctionRelationship)
        .filter(
            models.FunctionRelationship.source_function_id == function_id,
            models.FunctionRelationship.relationship_type == "CALLS",
        )
        .limit(limit)
        .all()
    )

    results = []
    for rel in rows:
        target_func = db.query(models.Function).filter(
            models.Function.name == rel.target_function_name,
        ).first()
        results.append({
            "name": rel.target_function_name,
            "file_id": rel.target_file_id,
            "context_line": rel.context_line,
            "confidence": rel.confidence,
            "target_function_id": target_func.id if target_func else None,
            "signature": target_func.signature if target_func else None,
        })
    return results


def get_impact_chain(db: Session, function_id: int, direction: str = "upstream",
                     max_depth: int = 3) -> dict:
    """BFS 遍历影响链，返回 nodes + edges

    direction='upstream': 查找谁调用了此函数（修改此函数会影响谁）
    direction='downstream': 查找此函数调用了谁（此函数依赖谁）
    """
    from collections import deque

    func = db.query(models.Function).filter(models.Function.id == function_id).first()
    if not func:
        return {"nodes": [], "edges": [], "depth": 0}

    func_name_map = {function_id: {"id": func.id, "name": func.name, "file_id": func.file_id}}
    visited = {function_id}
    nodes = [{"id": func.id, "name": func.name, "file_id": func.file_id, "depth": 0}]
    edges = []
    queue = deque([(function_id, 0)])

    while queue:
        current_id, current_depth = queue.popleft()
        if current_depth >= max_depth:
            continue

        if direction == "upstream":
            # 查找调用 current_id 的函数
            current_func = db.query(models.Function).filter(models.Function.id == current_id).first()
            if not current_func:
                continue
            related = (
                db.query(models.FunctionRelationship)
                .filter(
                    models.FunctionRelationship.target_function_name == current_func.name,
                    models.FunctionRelationship.relationship_type == "CALLS",
                )
                .all()
            )
            for rel in related:
                if rel.source_function_id not in visited:
                    visited.add(rel.source_function_id)
                    src_func = db.query(models.Function).filter(models.Function.id == rel.source_function_id).first()
                    if src_func:
                        func_name_map[rel.source_function_id] = {"id": src_func.id, "name": src_func.name, "file_id": src_func.file_id}
                        nodes.append({"id": src_func.id, "name": src_func.name, "file_id": src_func.file_id, "depth": current_depth + 1})
                        edges.append({"from": rel.source_function_id, "to": current_id, "line": rel.context_line})
                        queue.append((rel.source_function_id, current_depth + 1))
        else:  # downstream
            related = (
                db.query(models.FunctionRelationship)
                .filter(
                    models.FunctionRelationship.source_function_id == current_id,
                    models.FunctionRelationship.relationship_type == "CALLS",
                )
                .all()
            )
            for rel in related:
                target_func = db.query(models.Function).filter(
                    models.Function.name == rel.target_function_name,
                ).first()
                if target_func and target_func.id not in visited:
                    visited.add(target_func.id)
                    nodes.append({"id": target_func.id, "name": target_func.name, "file_id": target_func.file_id, "depth": current_depth + 1})
                    edges.append({"from": current_id, "to": target_func.id, "line": rel.context_line})
                    queue.append((target_func.id, current_depth + 1))

    return {"nodes": nodes, "edges": edges, "depth": max_depth}


def get_relationship_stats(db: Session) -> dict:
    """获取关系统计"""
    rows = (
        db.query(
            models.FunctionRelationship.relationship_type,
            func.count(models.FunctionRelationship.id).label("count"),
        )
        .group_by(models.FunctionRelationship.relationship_type)
        .all()
    )
    return {row.relationship_type: row.count for row in rows}


def get_function_by_name(db: Session, name: str, project_id: int = None) -> models.Function | None:
    """按名字和项目查找函数"""
    q = db.query(models.Function).join(models.File).filter(models.Function.name == name)
    if project_id is not None:
        q = q.filter(models.File.project_id == project_id)
    return q.first()


def get_relationship_counts(db: Session, func_ids: list[int]) -> dict[int, dict]:
    """Get caller_count and callee_count for a list of function IDs."""
    from sqlalchemy import func as safunc

    if not func_ids:
        return {}

    # Caller count: count relationships where this function is the target
    func_names = (
        db.query(models.Function.name)
        .filter(models.Function.id.in_(func_ids))
        .all()
    )
    name_list = [row[0] for row in func_names]

    caller_counts = dict(
        db.query(
            models.FunctionRelationship.target_function_name,
            safunc.count(models.FunctionRelationship.id),
        )
        .filter(
            models.FunctionRelationship.target_function_name.in_(name_list),
            models.FunctionRelationship.relationship_type == "CALLS",
        )
        .group_by(models.FunctionRelationship.target_function_name)
        .all()
    )

    # Callee count: count relationships where this function is the source
    callee_counts = dict(
        db.query(
            models.FunctionRelationship.source_function_id,
            safunc.count(models.FunctionRelationship.id),
        )
        .filter(
            models.FunctionRelationship.source_function_id.in_(func_ids),
            models.FunctionRelationship.relationship_type == "CALLS",
        )
        .group_by(models.FunctionRelationship.source_function_id)
        .all()
    )

    result = {}
    for fid in func_ids:
        func = db.query(models.Function).filter(models.Function.id == fid).first()
        callers = caller_counts.get(func.name, 0) if func else 0
        callees = callee_counts.get(fid, 0)
        result[fid] = {"callers": callers, "callees": callees}

    return result