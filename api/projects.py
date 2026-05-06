from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Dict, Any, Optional
from . import crud, models, schemas, database

router = APIRouter()


@router.get("/projects", response_model=List[schemas.Project])
def get_projects(db: Session = Depends(database.get_db)):
    """获取所有项目列表"""
    return crud.get_projects(db)


@router.get("/projects/{project_id}/files")
def get_project_files(project_id: int, db: Session = Depends(database.get_db)):
    """获取项目的文件树（含函数列表）"""
    project = crud.get_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    files = crud.get_files_by_project(db, project_id)
    for file in files:
        file.functions = crud.get_functions_by_file(db, file.id)

    # 获取最新的分析任务状态
    latest_task = crud.get_latest_task_by_project(db, project_id)
    analysis_status = latest_task.status if latest_task else "idle"

    return {
        "id": project.id,
        "name": project.name,
        "analysis_mode": project.analysis_mode,
        "files": files,
        "analysis_status": analysis_status
    }


@router.get("/projects/{project_id}/progress")
def get_progress(project_id: int, db: Session = Depends(database.get_db)):
    """获取项目分析进度"""
    progress = crud.get_analysis_progress(db, project_id)
    if not progress:
        return {"status": "idle", "progress": 0, "current_step": ""}
    return progress


@router.get("/projects/{project_id}/overview")
def get_overview(project_id: int, db: Session = Depends(database.get_db)):
    """获取项目整体解读（Markdown）"""
    project = crud.get_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    overview = project.overview_analysis or "暂无整体解读，请等待项目分析完成。"
    return {"overview": overview}


@router.put("/projects/{project_id}/mode")
def set_project_mode(
    project_id: int,
    mode: str,
    full_reanalysis: bool = False,
    db: Session = Depends(database.get_db),
):
    """
    切换项目分析模式: beginner, expert, ai。

    默认使用轻量模式（仅重新生成 LLM 内容，不重新抓取仓库）。
    设置 full_reanalysis=true 进行完整重新分析（重新 clone + 解析 + 生成）。
    """
    if mode not in ("beginner", "expert", "ai"):
        raise HTTPException(status_code=400, detail="Invalid mode. Must be: beginner, expert, or ai")

    project = crud.get_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # 更新模式
    crud.update_project_mode(db, project_id, mode)

    if full_reanalysis:
        # 完整重新分析（clone + 解析 + 生成）
        from .tasks import analyze_repo
        task_record = crud.create_task(db, project_id=project_id)
        db.commit()
        result = analyze_repo.delay(task_record.id, project.repo_url, project.name, mode)
        return {
            "project_id": project_id,
            "analysis_mode": mode,
            "task_id": result.id,
            "full_reanalysis": True,
            "message": f"Mode changed to '{mode}', full re-analysis triggered",
        }
    else:
        # 轻量模式：仅重新生成 LLM 内容
        from .celery_app import celery_app as _celery
        _celery.send_task('fill_project_mode_content', args=[project_id])
        return {
            "project_id": project_id,
            "analysis_mode": mode,
            "full_reanalysis": False,
            "message": f"Mode changed to '{mode}', lightweight content regeneration triggered",
        }


@router.delete("/projects/{project_id}")
def delete_project(project_id: int, db: Session = Depends(database.get_db)):
    """删除项目及所有关联数据（文件、函数、类、关系）"""
    deleted = crud.delete_project(db, project_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"detail": f"Project {project_id} deleted"}


@router.get("/projects/stats")
def get_all_project_stats(
    db: Session = Depends(database.get_db),
):
    """Get aggregate stats for all projects: files, functions, classes, coverage."""
    projects = db.query(models.Project).all()

    project_list = []
    grand_total = {
        "projects": 0,
        "files": 0,
        "functions": 0,
        "classes": 0,
        "with_code_snippet": 0,
        "with_explanation": 0,
        "with_ai_purpose": 0,
        "relationships": 0,
    }

    for p in projects:
        files_q = db.query(models.File).filter(models.File.project_id == p.id)
        file_ids = [f.id for f in files_q.all()]

        funcs_q = db.query(models.Function).filter(models.Function.file_id.in_(file_ids)) if file_ids else db.query(models.Function).filter(models.Function.file_id.is_(None))
        classes_q = db.query(models.Class).filter(models.Class.file_id.in_(file_ids)) if file_ids else db.query(models.Class).filter(models.Class.file_id.is_(None))

        func_count = funcs_q.count()
        class_count = classes_q.count() if file_ids else 0
        file_count = files_q.count()

        with_snippet = funcs_q.filter(models.Function.code_snippet.isnot(None)).count() if file_ids else 0
        with_explain = funcs_q.filter(models.Function.explanation_simple.isnot(None)).count() if file_ids else 0
        with_ai_purpose = funcs_q.filter(
            models.Function.ai_purpose.isnot(None),
            models.Function.ai_purpose != ""
        ).count() if file_ids else 0

        if func_count > 0:
            snippet_pct = round(with_snippet / func_count * 100, 1)
            explain_pct = round(with_explain / func_count * 100, 1)
            ai_purpose_pct = round(with_ai_purpose / func_count * 100, 1)
        else:
            snippet_pct = 0.0
            explain_pct = 0.0
            ai_purpose_pct = 0.0

        project_list.append({
            "project_id": p.id,
            "name": p.name,
            "language": p.language,
            "files": file_count,
            "functions": func_count,
            "classes": class_count,
            "with_code_snippet": with_snippet,
            "with_explanation": with_explain,
            "with_ai_purpose": with_ai_purpose,
            "snippet_coverage_pct": snippet_pct,
            "explanation_coverage_pct": explain_pct,
            "ai_purpose_coverage_pct": ai_purpose_pct,
            "has_overview": p.overview_analysis is not None,
            "last_analyzed": str(p.updated_at or p.created_at) if p.updated_at or p.created_at else None,
        })

        grand_total["projects"] += 1
        grand_total["files"] += file_count
        grand_total["functions"] += func_count
        grand_total["classes"] += class_count
        grand_total["with_code_snippet"] += with_snippet
        grand_total["with_explanation"] += with_explain
        grand_total["with_ai_purpose"] += with_ai_purpose

    from sqlalchemy import func as safunc
    grand_total["relationships"] = db.query(safunc.count(models.FunctionRelationship.id)).scalar() or 0

    if grand_total["functions"] > 0:
        grand_total["snippet_coverage_pct"] = round(grand_total["with_code_snippet"] / grand_total["functions"] * 100, 1)
        grand_total["explanation_coverage_pct"] = round(grand_total["with_explanation"] / grand_total["functions"] * 100, 1)
        grand_total["ai_purpose_coverage_pct"] = round(grand_total["with_ai_purpose"] / grand_total["functions"] * 100, 1)
    else:
        grand_total["snippet_coverage_pct"] = 0.0
        grand_total["explanation_coverage_pct"] = 0.0
        grand_total["ai_purpose_coverage_pct"] = 0.0

    return {
        "summary": grand_total,
        "projects": project_list,
    }