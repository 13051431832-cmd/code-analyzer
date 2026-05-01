from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any
import uuid
from . import tasks
from .celery_app import celery_app

import os
from fastapi.responses import FileResponse
from .config import config
from . import database, crud

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session

router = APIRouter()

class AnalyzeRequest(BaseModel):
    repo_url: str
    name: Optional[str] = None
    mode: Optional[str] = "ai"  # "beginner" | "expert" | "ai"

@router.post("/analyze")
def start_analysis(request: AnalyzeRequest):
    """启动代码分析任务（Celery 异步）"""
    try:
        # 假设 tasks 模块中有一个 start_analysis_task 函数
        # 如果还没有实现，请先实现 tasks.start_analysis_task
        task_id = tasks.start_analysis_task(request.repo_url, request.name, request.mode)
        return {"task_id": task_id}
    except AttributeError:
        # 临时模拟：生成一个随机 task_id（实际应调用 Celery 任务）
        task_id = str(uuid.uuid4())
        # 这里可以记录到数据库或缓存
        return {"task_id": task_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start analysis: {str(e)}")

@router.get("/analyze/{task_id}/status")
def get_task_status(task_id: str):
    """查询 Celery 任务状态"""
    from celery.result import AsyncResult
    result = AsyncResult(task_id, app=celery_app)
    if result.state == "PENDING":
        return {"status": "pending", "progress": 0}
    elif result.state == "STARTED":
        info = result.info or {}
        return {
            "status": "running",
            "progress": info.get("progress", 0),
            "current_step": info.get("current_step", "分析中...")
        }
    elif result.state == "SUCCESS":
        return {
            "status": "completed",
            "result": result.result,
            "progress": 100
        }
    elif result.state == "FAILURE":
        return {
            "status": "failed",
            "error_message": str(result.info),
            "progress": 0
        }
    else:
        return {"status": result.state, "progress": 0}


@router.get("/analyze/{task_id}/report")
def get_report(task_id: int, db: Session = Depends(database.get_db)):
    """下载分析报告（Markdown 文件）"""
    # 1. 检查任务是否存在
    task = crud.get_task_by_id(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # 2. 检查任务是否已完成
    if task.status != "completed":
        raise HTTPException(status_code=400, detail="Report not ready, task not completed")

    # 3. 构造报告文件路径
    report_path = os.path.join(config.TEMP_DIR, f"report_{task_id}.md")
    if not os.path.exists(report_path):
        raise HTTPException(status_code=404, detail="Report file not found")

    # 4. 返回文件（自动下载）
    return FileResponse(
        report_path,
        media_type="text/markdown",
        filename=f"report_{task_id}.md"
    )