import os
import logging
from fastapi import FastAPI, Depends, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

# 导入路由模块
from . import projects, analyze, functions, search, relations, files, reanalyze, classes, ai, sse
from .database import engine, SessionLocal
from .models import Base
from . import crud, search_service
from . import embedding_service

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Code Analyzer API", version="0.1.0")

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 数据库依赖
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# 根路径
@app.get("/", response_class=HTMLResponse)
async def read_root():
    return "<h1>Code Analyzer API Running</h1><p>访问 <a href='/docs'>/docs</a> 查看 API 文档。</p>"


# 启动事件
@app.on_event("startup")
async def startup_event():
    logger.info("🚀 Code Analyzer API 启动中...")
    try:
        # 自动创建表（如果不存在）
        Base.metadata.create_all(bind=engine)
        logger.info("✅ 数据库表已就绪")

        # 通过 Alembic 运行结构化迁移（替代裸 ALTER TABLE）
        try:
            from alembic.config import Config as AlembicConfig
            from alembic import command
            alembic_cfg = AlembicConfig(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
            command.upgrade(alembic_cfg, "head")
            logger.info("✅ Alembic 迁移已执行")
        except Exception as e:
            logger.warning(f"⚠️ Alembic 迁移执行出错: {e}")

        # 创建全文检索 GIN 索引（functions + classes）
        try:
            with engine.connect() as conn:
                conn.execute(text(search_service.get_search_index_sql()))
                conn.execute(text(search_service.get_class_search_index_sql()))
                conn.commit()
            logger.info("✅ 全文检索索引已就绪")
        except Exception as e:
            logger.warning(f"⚠️ 创建全文检索索引时出错: {e}")

        # 创建 pgvector 扩展 + 嵌入向量索引
        try:
            with engine.connect() as conn:
                conn.execute(text(embedding_service.get_extension_sql()))
                conn.execute(text(embedding_service.get_ivfflat_index_sql()))
                conn.commit()
            logger.info("✅ pgvector 扩展 + 嵌入索引已就绪")
        except Exception as e:
            logger.warning(f"⚠️ 创建 pgvector 扩展/索引时出错: {e}")

    except Exception as e:
        logger.error(f"❌ 数据库表初始化失败: {e}")


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "code-analyzer-api"}


# 测试数据库连接
@app.get("/api/test-db")
async def test_db(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        return {"status": "Database connected successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB error: {str(e)}")


# ========== 断点续传相关 API ==========

@app.get("/api/tasks/{task_id}/checkpoint")
async def get_task_checkpoint(task_id: int, db: Session = Depends(get_db)):
    """获取任务的检查点信息"""
    task = crud.get_task_by_id(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # 获取关联的项目信息
    project_name = None
    repo_url = None
    if task.project_id:
        project = crud.get_project(db, task.project_id)
        if project:
            project_name = project.name
            repo_url = project.repo_url

    return {
        "task_id": task.id,
        "project_id": task.project_id,
        "project_name": project_name,
        "repo_url": repo_url,
        "status": task.status,
        "progress_percent": task.progress_percent or 0,
        "current_step": task.current_step,
        "processed_files": task.processed_files or [],
        "total_files": task.total_files or 0,
        "last_processed_file": task.last_processed_file,
        "error_message": task.error_message,
        "created_at": task.created_at,
        "started_at": task.started_at,
        "finished_at": task.finished_at
    }


@app.post("/api/tasks/{task_id}/resume")
async def resume_task(task_id: int, db: Session = Depends(get_db)):
    """恢复中断的任务"""
    task = crud.get_task_by_id(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status not in ["failed", "pending"]:
        raise HTTPException(status_code=400, detail=f"Task status is {task.status}, cannot resume")

    # 获取项目信息
    if not task.project_id:
        raise HTTPException(status_code=400, detail="Task has no associated project")

    project = crud.get_project(db, task.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # 重新启动 Celery 任务（使用项目的当前模式）
    from .tasks import analyze_repo
    result = analyze_repo.delay(task.id, project.repo_url, project.name, project.analysis_mode or "ai")

    # 更新任务状态
    crud.update_task_status(db, task_id, "pending", current_step="queued_for_resume")

    return {
        "task_id": task.id,
        "status": "resumed",
        "celery_task_id": result.id,
        "message": f"Task {task_id} has been queued for resume"
    }


@app.get("/api/tasks/unfinished")
async def get_unfinished_tasks(db: Session = Depends(get_db)):
    """获取所有未完成的任务"""
    tasks = crud.get_unfinished_tasks(db)

    result = []
    for task in tasks:
        project_name = None
        if task.project_id:
            project = crud.get_project(db, task.project_id)
            project_name = project.name if project else None

        result.append({
            "task_id": task.id,
            "project_id": task.project_id,
            "project_name": project_name,
            "status": task.status,
            "progress_percent": task.progress_percent or 0,
            "current_step": task.current_step,
            "processed_files_count": len(task.processed_files or []),
            "total_files": task.total_files or 0,
            "error_message": task.error_message,
            "created_at": task.created_at
        })

    return {"tasks": result}


@app.delete("/api/tasks/{task_id}/checkpoint")
async def clear_task_checkpoint(task_id: int, db: Session = Depends(get_db)):
    """清除任务的检查点数据（任务完成后调用）"""
    task = crud.get_task_by_id(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    task.processed_files = []
    task.last_processed_file = None
    task.checkpoint_data = None
    db.commit()

    return {"message": f"Checkpoint data cleared for task {task_id}"}


# 注册业务路由（统一前缀 /api）
app.include_router(projects.router, prefix="/api", tags=["projects"])
app.include_router(analyze.router, prefix="/api", tags=["analyze"])
app.include_router(functions.router, prefix="/api", tags=["functions"])
app.include_router(search.router, prefix="/api", tags=["search"])
app.include_router(relations.router, prefix="/api", tags=["relations", "call-graph"])
app.include_router(files.router, prefix="/api", tags=["files"])
app.include_router(reanalyze.router, prefix="/api", tags=["reanalyze"])
app.include_router(classes.router, prefix="/api", tags=["classes"])
app.include_router(ai.router, prefix="/api", tags=["ai"])
app.include_router(sse.router, prefix="/api", tags=["sse"])


# 全局异常处理
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.error(f"全局异常: {exc}")
    return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})