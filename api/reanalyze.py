"""
Re-analysis and batch update endpoints.

Provides:
- Fill missing code_snippets from source files (no AI cost)
- Batch regenerate AI metadata for functions/classes
- Batch fill missing project overviews

AI-only mode: no human-oriented explanation generation.
"""

import os
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session

from . import crud, models
from .database import get_db
from .llm_service import generate_ai_metadata, generate_explanation, generate_expert_analysis

logger = logging.getLogger(__name__)

router = APIRouter()

# ── Helpers ──────────────────────────────────────────────


def _try_cross_project_fill(
    db: Session,
    project: models.Project,
    func_name: str,
    file_path: str,
    start_line: int,
) -> str | None:
    """
    当文件在磁盘上找不到时，尝试从同 repo_url 的其他项目中复制 code_snippet。
    匹配条件：函数名相同 + 文件路径相同。
    """
    if not project.repo_url:
        return None
    siblings = db.query(models.Project).filter(
        models.Project.repo_url == project.repo_url,
        models.Project.id != project.id,
    ).all()
    for sibling in siblings:
        sibling_file = db.query(models.File).filter(
            models.File.project_id == sibling.id,
            models.File.file_path == file_path,
        ).first()
        if not sibling_file:
            continue
        sibling_func = db.query(models.Function).filter(
            models.Function.file_id == sibling_file.id,
            models.Function.name == func_name,
            models.Function.code_snippet.isnot(None),
            models.Function.start_line == start_line,
        ).first()
        if sibling_func and sibling_func.code_snippet:
            return sibling_func.code_snippet
    return None


def _try_cross_project_fill_class(
    db: Session,
    project: models.Project,
    class_name: str,
    file_path: str,
    start_line: int,
) -> str | None:
    """
    类版本的跨项目复制。匹配条件：类名相同 + 文件路径相同。
    """
    if not project.repo_url:
        return None
    siblings = db.query(models.Project).filter(
        models.Project.repo_url == project.repo_url,
        models.Project.id != project.id,
    ).all()
    for sibling in siblings:
        sibling_file = db.query(models.File).filter(
            models.File.project_id == sibling.id,
            models.File.file_path == file_path,
        ).first()
        if not sibling_file:
            continue
        sibling_class = db.query(models.Class).filter(
            models.Class.file_id == sibling_file.id,
            models.Class.name == class_name,
            models.Class.code_snippet.isnot(None),
            models.Class.start_line == start_line,
        ).first()
        if sibling_class and sibling_class.code_snippet:
            return sibling_class.code_snippet
    return None


def _get_repo_root(project: models.Project) -> str | None:
    """
    Determine the source repository root directory for a project.
    Returns None if the source is not accessible.
    """
    url = project.repo_url or ""

    # Local paths that are absolute
    if url.startswith("/"):
        if os.path.isdir(url):
            return url
        return None

    # GitHub URLs — repo might be cloned in a known location
    if "github.com" in url:
        # Check repo_{id} in TEMP_DIR first (most common for recently analyzed projects)
        from .config import config as app_config
        repo_in_temp = os.path.join(app_config.TEMP_DIR, f"repo_{project.id}")
        if os.path.isdir(repo_in_temp):
            return repo_in_temp

        # Check /king_analysis/ dirs by project name
        repo_name = project.name.replace("-main", "").replace("_main", "")
        candidates = [
            f"/king_analysis/{project.name}/{project.name}",
            f"/king_analysis/{project.name}",
            f"/king_analysis/{repo_name}-main/{repo_name}-main",
            f"/king_analysis/{repo_name}-main",
            f"/king_analysis/{repo_name}",
        ]
        for c in candidates:
            if os.path.isdir(c):
                return c
        return None

    # Mounted volumes
    if url.startswith("/host_downloads/") and os.path.isdir(url):
        return url
    if url.startswith("/app/temp/") and os.path.isdir(url):
        return url

    return None


def _extract_code_snippet(repo_root: str, file_path: str, start_line: int, end_line: int) -> str | None:
    """Read source file and extract function code by line numbers."""
    full_path = os.path.join(repo_root, file_path)
    if not os.path.isfile(full_path):
        return None
    try:
        with open(full_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        snippet = "".join(lines[start_line - 1 : end_line])
        return snippet
    except Exception as e:
        logger.warning(f"Failed to read {full_path}: {e}")
        return None


# ── API Endpoints ────────────────────────────────────────


@router.post("/reanalyze/project/{project_id}/fill-code-snippets")
def fill_missing_code_snippets(
    project_id: int,
    dry_run: bool = False,
    db: Session = Depends(get_db),
):
    """
    Fill missing code_snippets for functions in a project.

    Reads source files from the cloned repo directory and extracts
    function code by line number. This uses ZERO AI API calls.

    Set dry_run=true to see what would be done without modifying anything.
    """
    project = crud.get_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    repo_root = _get_repo_root(project)
    if not repo_root:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot locate source repository for project '{project.name}' (repo_url={project.repo_url})",
        )

    # Find functions missing code_snippet
    files = crud.get_files_by_project(db, project_id)

    total_filled = 0
    total_skipped_no_file = 0
    total_skipped_already = 0
    total_errors = 0
    results = []

    for file_obj in files:
        functions = db.query(models.Function).filter(
            models.Function.file_id == file_obj.id,
            models.Function.code_snippet.is_(None),
        ).all()

        if not functions:
            continue

        for func in functions:
            if not func.start_line or not func.end_line:
                total_skipped_no_file += 1
                continue

            snippet = _extract_code_snippet(
                repo_root, file_obj.file_path,
                func.start_line, func.end_line,
            )

            cross_project = False
            if snippet is None:
                # 跨项目回退：从同 repo_url 的其他项目中复制 snippet
                snippet = _try_cross_project_fill(
                    db, project, func.name,
                    file_obj.file_path, func.start_line,
                )
                if snippet is not None:
                    cross_project = True
                else:
                    total_skipped_no_file += 1
                    results.append({
                        "function_id": func.id,
                        "name": func.name,
                        "file_path": file_obj.file_path,
                        "status": "skipped",
                        "reason": f"source file not found at {repo_root}/{file_obj.file_path}",
                    })
                    continue

            if not dry_run:
                try:
                    func.code_snippet = snippet
                    db.commit()
                    total_filled += 1
                    fill_status = "cross-project" if cross_project else "filled"
                    results.append({
                        "function_id": func.id,
                        "name": func.name,
                        "file_path": file_obj.file_path,
                        "status": fill_status,
                        "lines": func.end_line - func.start_line + 1,
                    })
                except Exception as e:
                    db.rollback()
                    total_errors += 1
                    results.append({
                        "function_id": func.id,
                        "name": func.name,
                        "file_path": file_obj.file_path,
                        "status": "error",
                        "reason": str(e),
                    })
            else:
                total_filled += 1
                results.append({
                    "function_id": func.id,
                    "name": func.name,
                    "file_path": file_obj.file_path,
                    "status": "would_fill",
                    "lines": func.end_line - func.start_line + 1,
                })

    return {
        "project_id": project_id,
        "project_name": project.name,
        "repo_root": repo_root,
        "dry_run": dry_run,
        "summary": {
            "filled": total_filled,
            "skipped_source_not_found": total_skipped_no_file,
            "errors": total_errors,
        },
        "results": results[:100],  # Limit results to avoid huge response
        "total_results": len(results),
    }


@router.get("/reanalyze/missing-summary")
def missing_analysis_summary(
    mode: str = None,
    db: Session = Depends(get_db),
):
    """
    Summary of all missing analysis content across projects.

    Shows what needs to be filled across all three modes (ai/beginner/expert).
    Optionally filter by mode to see gaps for a specific mode only.
    """
    projects = db.query(models.Project).all()

    report = []
    for project in projects:
        base = db.query(models.Function).join(models.File).filter(
            models.File.project_id == project.id,
        )

        # Code snippets
        missing_code = base.filter(models.Function.code_snippet.is_(None)).count()

        # AI metadata
        missing_ai = base.filter(models.Function.ai_purpose.is_(None)).count()

        # Beginner explanations (functions with ai_purpose but no explanation_simple)
        missing_beginner = base.filter(
            models.Function.ai_purpose.isnot(None),
            models.Function.explanation_simple.is_(None),
        ).count()

        # Expert analyses (functions with ai_purpose but no expert_purpose)
        missing_expert = base.filter(
            models.Function.ai_purpose.isnot(None),
            models.Function.expert_purpose.is_(None),
        ).count()

        # Class-level
        cbase = db.query(models.Class).join(models.File).filter(
            models.File.project_id == project.id,
        )

        missing_class_code = cbase.filter(models.Class.code_snippet.is_(None)).count()
        missing_class_ai = cbase.filter(models.Class.ai_purpose.is_(None)).count()

        missing_class_beginner = cbase.filter(
            models.Class.ai_purpose.isnot(None),
            models.Class.explanation_simple.is_(None),
        ).count()

        missing_class_expert = cbase.filter(
            models.Class.ai_purpose.isnot(None),
            models.Class.expert_purpose.is_(None),
        ).count()

        repo_root = _get_repo_root(project)

        report.append({
            "project_id": project.id,
            "project_name": project.name,
            "analysis_mode": project.analysis_mode,
            "repo_url": project.repo_url,
            "repo_accessible": repo_root is not None,
            "repo_path": repo_root,
            "missing_code_snippets": missing_code,
            "missing_ai_metadata": missing_ai,
            "missing_beginner_explanations": missing_beginner,
            "missing_expert_analyses": missing_expert,
            "missing_class_code_snippets": missing_class_code,
            "missing_class_ai_metadata": missing_class_ai,
            "missing_class_beginner_explanations": missing_class_beginner,
            "missing_class_expert_analyses": missing_class_expert,
        })

    # Filter by mode if requested
    if mode:
        mode_field_map = {
            "beginner": "missing_beginner_explanations",
            "expert": "missing_expert_analyses",
            "ai": "missing_ai_metadata",
        }
        field = mode_field_map.get(mode, "missing_ai_metadata")
        report = [r for r in report if r.get(field, 0) > 0 or r["missing_code_snippets"] > 0]

    total_missing_code = sum(r["missing_code_snippets"] for r in report)
    total_missing_ai = sum(r["missing_ai_metadata"] for r in report)
    total_missing_beginner = sum(r["missing_beginner_explanations"] for r in report)
    total_missing_expert = sum(r["missing_expert_analyses"] for r in report)
    total_missing_class_code = sum(r["missing_class_code_snippets"] for r in report)
    total_missing_class_ai = sum(r["missing_class_ai_metadata"] for r in report)
    total_missing_class_beginner = sum(r["missing_class_beginner_explanations"] for r in report)
    total_missing_class_expert = sum(r["missing_class_expert_analyses"] for r in report)
    accessible_projects = sum(1 for r in report if r["repo_accessible"])

    return {
        "summary": {
            "total_projects": len(report),
            "accessible_projects": accessible_projects,
            "total_missing_code_snippets": total_missing_code,
            "total_missing_ai_metadata": total_missing_ai,
            "total_missing_beginner_explanations": total_missing_beginner,
            "total_missing_expert_analyses": total_missing_expert,
            "total_missing_class_code_snippets": total_missing_class_code,
            "total_missing_class_ai_metadata": total_missing_class_ai,
            "total_missing_class_beginner_explanations": total_missing_class_beginner,
            "total_missing_class_expert_analyses": total_missing_class_expert,
        },
        "projects": report,
    }


@router.post("/reanalyze/project/{project_id}/regenerate-ai-metadata")
def regenerate_project_ai_metadata(
    project_id: int,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    """
    Regenerate AI-oriented metadata (ai_purpose, ai_inputs, ai_outputs, ai_side_effects)
    for functions that are missing it. Uses LLM API (AI cost applies).
    """
    project = crud.get_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    from .llm_service import generate_ai_metadata

    missing_funcs = (
        db.query(models.Function)
        .join(models.File)
        .filter(
            models.File.project_id == project_id,
            models.Function.ai_purpose.is_(None),
            models.Function.code_snippet.isnot(None),
        )
        .limit(limit)
        .all()
    )

    if not missing_funcs:
        return {
            "project_id": project_id,
            "project_name": project.name,
            "message": "No functions missing AI metadata (with code_snippet available)",
            "processed": 0,
        }

    processed = 0
    errors = 0
    results = []

    for func in missing_funcs:
        try:
            file_obj = db.query(models.File).filter(models.File.id == func.file_id).first()
            lang = file_obj.language if file_obj else "python"

            ai_meta = generate_ai_metadata(func.code_snippet, "function", lang)

            func.ai_purpose = ai_meta.get("purpose")
            func.ai_inputs = ai_meta.get("inputs")
            func.ai_outputs = ai_meta.get("outputs")
            func.ai_side_effects = ai_meta.get("side_effects")

            # Extract return_type from outputs
            outputs = ai_meta.get("outputs", {})
            if outputs and isinstance(outputs, dict):
                func.return_type = outputs.get("type")

            db.commit()
            processed += 1
            results.append({
                "function_id": func.id,
                "name": func.name,
                "status": "regenerated",
            })
        except Exception as e:
            db.rollback()
            errors += 1
            results.append({
                "function_id": func.id,
                "name": func.name,
                "status": "error",
                "reason": str(e),
            })

    return {
        "project_id": project_id,
        "project_name": project.name,
        "summary": {
            "processed": processed,
            "errors": errors,
        },
        "results": results,
    }


@router.post("/reanalyze/regenerate-overview/{project_id}")
def regenerate_project_overview(
    project_id: int,
    mode: str = None,
    db: Session = Depends(get_db),
):
    """
    Regenerate the project-level architecture overview.
    Uses the LLM API (AI cost applies).

    Parameters:
    - mode: "beginner", "expert", "ai", or None (uses project's current mode)
    """
    project = crud.get_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Determine mode
    overview_mode = mode or project.analysis_mode or "ai"
    if overview_mode not in ("beginner", "expert", "ai"):
        raise HTTPException(status_code=400, detail="mode must be 'beginner', 'expert', or 'ai'")

    from .llm_service import generate_project_overview, generate_beginner_overview, generate_expert_overview

    # Collect project file summaries
    files_summary = []
    for file_obj in db.query(models.File).filter(models.File.project_id == project.id).all():
        functions = db.query(models.Function).filter(
            models.Function.file_id == file_obj.id
        ).all()
        classes = db.query(models.Class).filter(
            models.Class.file_id == file_obj.id
        ).all()

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
            "docstring_summary": doc_summary,
        })

    try:
        if overview_mode == "beginner":
            overview_text = generate_beginner_overview(project.name, files_summary)
        elif overview_mode == "expert":
            overview_text = generate_expert_overview(project.name, files_summary)
        else:
            overview_text = generate_project_overview(project.name, files_summary)
        project.overview_analysis = overview_text
        db.commit()

        return {
            "project_id": project_id,
            "project_name": project.name,
            "status": "regenerated",
            "mode": overview_mode,
            "overview_length": len(overview_text),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Overview generation failed: {str(e)}")


@router.post("/reanalyze/fill-all-code-snippets")
def fill_all_missing_code_snippets(
    dry_run: bool = False,
    db: Session = Depends(get_db),
):
    """
    Fill missing code_snippets for ALL projects that have accessible source repos.
    Zero AI cost — reads code directly from source files.

    Use dry_run=true to see what would be done.
    """
    projects = db.query(models.Project).all()
    total_filled = 0
    project_results = []

    for project in projects:
        repo_root = _get_repo_root(project)
        if not repo_root:
            project_results.append({
                "project_id": project.id,
                "project_name": project.name,
                "status": "skipped",
                "reason": "source repo not accessible",
            })
            continue

        # Count missing
        missing = db.query(models.Function).join(models.File).filter(
            models.File.project_id == project.id,
            models.Function.code_snippet.is_(None),
        ).count()

        if missing == 0:
            project_results.append({
                "project_id": project.id,
                "project_name": project.name,
                "status": "skipped",
                "reason": "no missing code_snippets",
            })
            continue

        # Dry run or actual
        if dry_run:
            project_results.append({
                "project_id": project.id,
                "project_name": project.name,
                "status": "would_process",
                "missing_count": missing,
                "repo_path": repo_root,
            })
            total_filled += missing
        else:
            # Reuse the per-project logic
            result = _fill_project_snippets(db, project)
            project_results.append({
                "project_id": project.id,
                "project_name": project.name,
                "status": "processed",
                "filled": result["filled"],
                "skipped": result["skipped"],
                "errors": result["errors"],
            })
            total_filled += result["filled"]

    return {
        "dry_run": dry_run,
        "summary": {
            "total_projects_processed": len(project_results),
            "total_filled": total_filled,
        },
        "projects": project_results,
    }


@router.post("/reanalyze/fill-all-ai-metadata")
def fill_all_missing_ai_metadata(
    limit_per_project: int = 100,
    db: Session = Depends(get_db),
):
    """
    Batch regenerate AI metadata for ALL projects.
    Processes up to `limit_per_project` functions per project.
    Uses parallel ThreadPoolExecutor for LLM calls.
    """
    projects_list = db.query(models.Project).all()
    total_processed = 0
    total_errors = 0
    project_results = []

    for project in projects_list:
        missing_funcs = (
            db.query(models.Function)
            .join(models.File)
            .filter(
                models.File.project_id == project.id,
                models.Function.ai_purpose.is_(None),
                models.Function.code_snippet.isnot(None),
            )
            .limit(limit_per_project)
            .all()
        )

        if not missing_funcs:
            project_results.append({
                "project_id": project.id,
                "project_name": project.name,
                "status": "skipped",
                "reason": "no missing AI metadata (with code_snippet available)",
            })
            continue

        result = _process_funcs_parallel(db, missing_funcs, "ai", max_workers=5)

        project_results.append({
            "project_id": project.id,
            "project_name": project.name,
            "status": "processed",
            "processed": result["processed"],
            "errors": result["errors"],
            "remaining": max(0, len(missing_funcs) - result["processed"]),
        })
        total_processed += result["processed"]
        total_errors += result["errors"]

    return {
        "summary": {
            "total_processed": total_processed,
            "total_errors": total_errors,
            "projects_affected": sum(1 for r in project_results if r["status"] == "processed"),
        },
        "projects": project_results,
    }


def _fill_project_snippets(db: Session, project: models.Project) -> dict:
    """Internal helper to fill code_snippets for a single project."""
    repo_root = _get_repo_root(project)
    if not repo_root:
        return {"filled": 0, "skipped": 0, "errors": 0}

    files = crud.get_files_by_project(db, project.id)
    filled = 0
    skipped = 0
    errors = 0

    for file_obj in files:
        functions = db.query(models.Function).filter(
            models.Function.file_id == file_obj.id,
            models.Function.code_snippet.is_(None),
        ).all()

        for func in functions:
            if not func.start_line or not func.end_line:
                skipped += 1
                continue

            snippet = _extract_code_snippet(
                repo_root, file_obj.file_path,
                func.start_line, func.end_line,
            )

            if snippet is None:
                skipped += 1
                continue

            try:
                func.code_snippet = snippet
                db.commit()
                filled += 1
            except Exception:
                db.rollback()
                errors += 1

    return {"filled": filled, "skipped": skipped, "errors": errors}


# ── Class-level code_snippet filling ──────────────────────


@router.post("/reanalyze/project/{project_id}/fill-class-snippets")
def fill_missing_class_code_snippets(
    project_id: int,
    dry_run: bool = False,
    db: Session = Depends(get_db),
):
    """
    Fill missing code_snippets for classes in a project.
    Zero AI cost — reads code directly from source files.
    """
    project = crud.get_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    repo_root = _get_repo_root(project)
    if not repo_root:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot locate source repository for project '{project.name}'",
        )

    classes = (
        db.query(models.Class)
        .join(models.File)
        .filter(models.File.project_id == project_id)
        .all()
    )

    total_filled = 0
    total_skipped = 0
    total_errors = 0
    results = []

    for cls in classes:
        if cls.code_snippet is not None and not dry_run:
            continue  # Already has snippet

        file_obj = db.query(models.File).filter(models.File.id == cls.file_id).first()
        if not file_obj:
            continue

        snippet = _extract_code_snippet(
            repo_root, file_obj.file_path,
            cls.start_line, cls.end_line,
        )

        cross_project = False
        if snippet is None:
            # 跨项目回退
            snippet = _try_cross_project_fill_class(
                db, project, cls.name,
                file_obj.file_path, cls.start_line,
            )
            if snippet is not None:
                cross_project = True
            else:
                total_skipped += 1
                results.append({
                    "class_id": cls.id,
                    "name": cls.name,
                    "status": "skipped",
                    "reason": f"source file not found at {repo_root}/{file_obj.file_path}",
                })
                continue

        if not dry_run:
            try:
                cls.code_snippet = snippet
                db.commit()
                total_filled += 1
                fill_status = "cross-project" if cross_project else "filled"
                results.append({
                    "class_id": cls.id,
                    "name": cls.name,
                    "file_path": file_obj.file_path,
                    "status": fill_status,
                    "lines": cls.end_line - cls.start_line + 1,
                })
            except Exception as e:
                db.rollback()
                total_errors += 1
                results.append({
                    "class_id": cls.id,
                    "name": cls.name,
                    "status": "error",
                    "reason": str(e),
                })
        else:
            total_filled += 1
            results.append({
                "class_id": cls.id,
                "name": cls.name,
                "file_path": file_obj.file_path,
                "status": "would_fill",
                "lines": cls.end_line - cls.start_line + 1,
            })

    return {
        "project_id": project_id,
        "project_name": project.name,
        "repo_root": repo_root,
        "dry_run": dry_run,
        "summary": {
            "filled": total_filled,
            "skipped": total_skipped,
            "errors": total_errors,
        },
        "results": results[:100],
        "total_results": len(results),
    }


@router.post("/reanalyze/fill-all-class-snippets")
def fill_all_missing_class_snippets(
    dry_run: bool = False,
    db: Session = Depends(get_db),
):
    """Fill missing class code_snippets for ALL accessible projects. Zero AI cost."""
    projects_list = db.query(models.Project).all()
    total_filled = 0
    project_results = []

    for project in projects_list:
        repo_root = _get_repo_root(project)
        if not repo_root:
            project_results.append({
                "project_id": project.id,
                "project_name": project.name,
                "status": "skipped",
                "reason": "source repo not accessible",
            })
            continue

        missing = (
            db.query(models.Class)
            .join(models.File)
            .filter(
                models.File.project_id == project.id,
                models.Class.code_snippet.is_(None),
            )
            .count()
        )

        if missing == 0:
            project_results.append({
                "project_id": project.id,
                "project_name": project.name,
                "status": "skipped",
                "reason": "no missing class code_snippets",
            })
            continue

        if dry_run:
            project_results.append({
                "project_id": project.id,
                "project_name": project.name,
                "status": "would_process",
                "missing_count": missing,
                "repo_path": repo_root,
            })
            total_filled += missing
        else:
            result = _fill_project_class_snippets(db, project)
            project_results.append({
                "project_id": project.id,
                "project_name": project.name,
                "status": "processed",
                "filled": result["filled"],
                "skipped": result["skipped"],
                "errors": result["errors"],
            })
            total_filled += result["filled"]

    return {
        "dry_run": dry_run,
        "summary": {
            "total_projects_processed": len(project_results),
            "total_filled": total_filled,
        },
        "projects": project_results,
    }


def _fill_project_class_snippets(db: Session, project: models.Project) -> dict:
    """Internal helper to fill class code_snippets for a single project."""
    repo_root = _get_repo_root(project)
    if not repo_root:
        return {"filled": 0, "skipped": 0, "errors": 0}

    filled = 0
    skipped = 0
    errors = 0

    classes = (
        db.query(models.Class)
        .join(models.File)
        .filter(
            models.File.project_id == project.id,
            models.Class.code_snippet.is_(None),
        )
        .all()
    )

    for cls in classes:
        file_obj = db.query(models.File).filter(models.File.id == cls.file_id).first()
        if not file_obj:
            skipped += 1
            continue

        snippet = _extract_code_snippet(
            repo_root, file_obj.file_path,
            cls.start_line, cls.end_line,
        )

        if snippet is None:
            skipped += 1
            continue

        try:
            cls.code_snippet = snippet
            db.commit()
            filled += 1
        except Exception:
            db.rollback()
            errors += 1

    return {"filled": filled, "skipped": skipped, "errors": errors}


def _process_funcs_parallel(
    db: Session,
    funcs: list,
    mode: str,
    max_workers: int = 5,
    batch_commit: int = 50
) -> dict:
    """
    Process a list of functions in parallel using ThreadPoolExecutor.

    Each thread creates its own DB session. Results are batched.

    Returns: {"processed": int, "errors": int}
    """
    if not funcs:
        return {"processed": 0, "errors": 0}

    processed = 0
    errors = 0

    def _process_one(func_data):
        """Process a single function in its own thread + session."""
        func_id, code_snippet, lang, func_mode = func_data
        from api.database import SessionLocal
        from api import models
        fs = SessionLocal()
        try:
            func_obj = fs.query(models.Function).filter(models.Function.id == func_id).first()
            if not func_obj:
                fs.close()
                return "error"

            if func_mode == "beginner":
                from api.llm_service import generate_explanation
                result = generate_explanation(code_snippet, "function", lang)
                func_obj.explanation_simple = result.get("simple")
                func_obj.explanation_logic = result.get("logic")
            elif func_mode == "expert":
                from api.llm_service import generate_expert_analysis
                result = generate_expert_analysis(code_snippet, "function", lang)
                func_obj.expert_purpose = result.get("purpose")
                func_obj.expert_tech_details = result.get("tech_details")
                func_obj.expert_error_handling = result.get("error_handling")
                func_obj.expert_concurrency = result.get("concurrency")
                func_obj.expert_tradeoffs = result.get("tradeoffs")
            else:  # ai
                from api.llm_service import generate_ai_metadata
                ai_meta = generate_ai_metadata(code_snippet, "function", lang)
                func_obj.ai_purpose = ai_meta.get("purpose")
                func_obj.ai_inputs = ai_meta.get("inputs")
                func_obj.ai_outputs = ai_meta.get("outputs")
                func_obj.ai_side_effects = ai_meta.get("side_effects")
                outputs = ai_meta.get("outputs", {})
                if outputs and isinstance(outputs, dict):
                    func_obj.return_type = outputs.get("type")

            fs.commit()
            fs.close()
            return "ok"
        except Exception as e:
            fs.rollback()
            fs.close()
            return f"error: {e}"

    # Prepare data for threads
    func_data_list = []
    for func in funcs:
        file_obj = db.query(models.File).filter(models.File.id == func.file_id).first()
        lang = file_obj.language if file_obj else "python"
        func_data_list.append((func.id, func.code_snippet, lang, mode))

    # Process in parallel
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_process_one, fd): fd for fd in func_data_list}
        done_count = 0
        for future in as_completed(futures):
            result = future.result()
            if result == "ok":
                processed += 1
            else:
                errors += 1
            done_count += 1
            if done_count % batch_commit == 0 or done_count == len(funcs):
                print(f"  \u23f3 {mode} mode: {done_count}/{len(funcs)} functions processed ({processed} ok, {errors} errors)")

    return {"processed": processed, "errors": errors}


def _process_classes_parallel(
    db: Session,
    classes: list,
    mode: str,
    max_workers: int = 5,
    batch_commit: int = 50
) -> dict:
    """Same pattern but for classes."""
    if not classes:
        return {"processed": 0, "errors": 0}

    processed = 0
    errors = 0

    def _process_one(cls_data):
        cls_id, code_snippet, lang, cls_mode = cls_data
        from api.database import SessionLocal
        from api import models
        fs = SessionLocal()
        try:
            cls_obj = fs.query(models.Class).filter(models.Class.id == cls_id).first()
            if not cls_obj:
                fs.close()
                return "error"

            if cls_mode == "beginner":
                from api.llm_service import generate_explanation
                result = generate_explanation(code_snippet, "class", lang)
                cls_obj.explanation_simple = result.get("simple")
                cls_obj.explanation_logic = result.get("logic")
            elif cls_mode == "expert":
                from api.llm_service import generate_expert_analysis
                result = generate_expert_analysis(code_snippet, "class", lang)
                cls_obj.expert_purpose = result.get("purpose")
                cls_obj.expert_architecture = result.get("architecture")
                cls_obj.expert_responsibilities = result.get("responsibilities")
                cls_obj.expert_extension_points = result.get("extension_points")
            else:
                from api.llm_service import generate_ai_metadata
                ai_meta = generate_ai_metadata(code_snippet, "class", lang)
                cls_obj.ai_purpose = ai_meta.get("purpose")
                cls_obj.ai_interfaces = ai_meta.get("interfaces")

            fs.commit()
            fs.close()
            return "ok"
        except Exception as e:
            fs.rollback()
            fs.close()
            return f"error: {e}"

    cls_data_list = []
    for cls in classes:
        file_obj = db.query(models.File).filter(models.File.id == cls.file_id).first()
        lang = file_obj.language if file_obj else "python"
        cls_data_list.append((cls.id, cls.code_snippet, lang, mode))

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_process_one, cd): cd for cd in cls_data_list}
        done_count = 0
        for future in as_completed(futures):
            result = future.result()
            if result == "ok":
                processed += 1
            else:
                errors += 1
            done_count += 1
            if done_count % batch_commit == 0 or done_count == len(classes):
                print(f"  \u23f3 {mode} classes: {done_count}/{len(classes)} processed ({processed} ok, {errors} errors)")

    return {"processed": processed, "errors": errors}


# ── Mode-aware batch endpoints ─────────────────────────────


def _generate_for_function(db: Session, func, mode: str) -> bool:
    """Generate LLM content for a single function based on mode. Returns True on success."""
    from .llm_service import generate_explanation, generate_expert_analysis, generate_ai_metadata

    if not func.code_snippet:
        return False

    file_obj = db.query(models.File).filter(models.File.id == func.file_id).first()
    lang = file_obj.language if file_obj else "python"

    try:
        if mode == "beginner":
            result = generate_explanation(func.code_snippet, "function", lang)
            func.explanation_simple = result.get("simple")
            func.explanation_logic = result.get("logic")
        elif mode == "expert":
            result = generate_expert_analysis(func.code_snippet, "function", lang)
            func.expert_purpose = result.get("purpose")
            func.expert_tech_details = result.get("tech_details")
            func.expert_error_handling = result.get("error_handling")
            func.expert_concurrency = result.get("concurrency")
            func.expert_tradeoffs = result.get("tradeoffs")
        else:  # ai
            result = generate_ai_metadata(func.code_snippet, "function", lang)
            func.ai_purpose = result.get("purpose")
            func.ai_inputs = result.get("inputs")
            func.ai_outputs = result.get("outputs")
            func.ai_side_effects = result.get("side_effects")
            outputs = result.get("outputs", {})
            if outputs and isinstance(outputs, dict):
                func.return_type = outputs.get("type")
        db.commit()
        return True
    except Exception as e:
        db.rollback()
        logger.warning(f"Failed to generate {mode} content for function {func.id} ({func.name}): {e}")
        return False


def _generate_for_class(db: Session, cls, mode: str) -> bool:
    """Generate LLM content for a single class based on mode. Returns True on success."""
    from .llm_service import generate_explanation, generate_expert_analysis, generate_ai_metadata

    if not cls.code_snippet:
        return False

    file_obj = db.query(models.File).filter(models.File.id == cls.file_id).first()
    lang = file_obj.language if file_obj else "python"

    try:
        if mode == "beginner":
            result = generate_explanation(cls.code_snippet, "class", lang)
            cls.explanation_simple = result.get("simple")
            cls.explanation_logic = result.get("logic")
        elif mode == "expert":
            result = generate_expert_analysis(cls.code_snippet, "class", lang)
            cls.expert_purpose = result.get("purpose")
            cls.expert_architecture = result.get("architecture")
            cls.expert_responsibilities = result.get("responsibilities")
            cls.expert_extension_points = result.get("extension_points")
        else:  # ai
            result = generate_ai_metadata(cls.code_snippet, "class", lang)
            cls.ai_purpose = result.get("purpose")
            cls.ai_inputs = result.get("inputs")
            cls.ai_outputs = result.get("outputs")
            cls.ai_side_effects = result.get("side_effects")
        db.commit()
        return True
    except Exception as e:
        db.rollback()
        logger.warning(f"Failed to generate {mode} content for class {cls.id} ({cls.name}): {e}")
        return False


@router.post("/reanalyze/project/{project_id}/fill-mode-content")
def fill_missing_mode_content(
    project_id: int,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    """
    Fill missing content for the project's current analysis_mode.

    Detects the project's analysis_mode (beginner/expert/ai) and generates
    only the missing content for that mode. AI metadata is always generated
    if missing, regardless of mode.

    Uses the LLM API. Call repeatedly to process all.
    """
    project = crud.get_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    mode = project.analysis_mode or "ai"

    # Always ensure AI metadata is filled if missing
    from .llm_service import generate_ai_metadata

    results = {
        "ai_functions_processed": 0,
        "mode_functions_processed": 0,
        "ai_classes_processed": 0,
        "mode_classes_processed": 0,
        "errors": 0,
    }

    # 1. Fill missing AI metadata for functions - parallel
    ai_missing_funcs = (
        db.query(models.Function)
        .join(models.File)
        .filter(
            models.File.project_id == project_id,
            models.Function.ai_purpose.is_(None),
            models.Function.code_snippet.isnot(None),
        )
        .limit(limit)
        .all()
    )
    if ai_missing_funcs:
        ai_result = _process_funcs_parallel(db, ai_missing_funcs, "ai")
        results["ai_functions_processed"] = ai_result["processed"]
        results["errors"] += ai_result["errors"]

    # 2. Fill missing AI metadata for classes - parallel
    ai_missing_classes = (
        db.query(models.Class)
        .join(models.File)
        .filter(
            models.File.project_id == project_id,
            models.Class.ai_purpose.is_(None),
            models.Class.code_snippet.isnot(None),
        )
        .limit(limit)
        .all()
    )
    if ai_missing_classes:
        ai_cls_result = _process_classes_parallel(db, ai_missing_classes, "ai")
        results["ai_classes_processed"] = ai_cls_result["processed"]
        results["errors"] += ai_cls_result["errors"]

    # 3. Fill missing mode-specific content (if not ai mode) - parallel
    if mode != "ai":
        mode_field = "expert_purpose" if mode == "expert" else "explanation_simple"

        mode_missing_funcs = (
            db.query(models.Function)
            .join(models.File)
            .filter(
                models.File.project_id == project_id,
                getattr(models.Function, mode_field).is_(None),
                models.Function.code_snippet.isnot(None),
            )
            .limit(limit)
            .all()
        )
        if mode_missing_funcs:
            mode_result = _process_funcs_parallel(db, mode_missing_funcs, mode)
            results["mode_functions_processed"] = mode_result["processed"]
            results["errors"] += mode_result["errors"]

        class_mode_field = "expert_purpose" if mode == "expert" else "explanation_simple"

        mode_missing_classes = (
            db.query(models.Class)
            .join(models.File)
            .filter(
                models.File.project_id == project_id,
                getattr(models.Class, class_mode_field).is_(None),
                models.Class.code_snippet.isnot(None),
            )
            .limit(limit)
            .all()
        )
        if mode_missing_classes:
            mode_cls_result = _process_classes_parallel(db, mode_missing_classes, mode)
            results["mode_classes_processed"] = mode_cls_result["processed"]
            results["errors"] += mode_cls_result["errors"]

    return {
        "project_id": project_id,
        "project_name": project.name,
        "analysis_mode": mode,
        "summary": results,
    }


@router.post("/reanalyze/project/{project_id}/switch-mode")
def switch_project_analysis_mode(
    project_id: int,
    new_mode: str,
    db: Session = Depends(get_db),
):
    """
    Switch a project's analysis mode and regenerate content.

    Parameters:
    - new_mode: "beginner", "expert", or "ai"

    This changes the project's analysis_mode and immediately starts
    filling content for the new mode. AI metadata is always preserved
    and filled if missing.
    """
    if new_mode not in ("beginner", "expert", "ai"):
        raise HTTPException(status_code=400, detail="mode must be 'beginner', 'expert', or 'ai'")

    project = crud.get_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Switch mode
    old_mode = project.analysis_mode
    project.analysis_mode = new_mode
    db.commit()

    # Regenerate content for the new mode (AI always fills too)
    from .celery_app import celery_app as _celery
    _celery.send_task('fill_project_mode_content', args=[project_id])

    return {
        "project_id": project_id,
        "project_name": project.name,
        "old_mode": old_mode,
        "new_mode": new_mode,
        "message": "Mode switched. Background task started to regenerate content.",
    }


@router.post("/reanalyze/project/{project_id}/regenerate-all-by-mode")
def regenerate_all_by_current_mode(
    project_id: int,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    """
    Regenerate content for ALL functions/classes based on the project's
    current analysis_mode, regardless of whether they already have content.

    Useful after tweaking LLM prompts for a mode.
    Uses the LLM API. Call repeatedly to process all.
    """
    project = crud.get_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    mode = project.analysis_mode or "ai"

    results = {
        "functions_processed": 0,
        "classes_processed": 0,
        "errors": 0,
    }

    # Functions with code_snippet - parallel
    funcs = (
        db.query(models.Function)
        .join(models.File)
        .filter(
            models.File.project_id == project_id,
            models.Function.code_snippet.isnot(None),
        )
        .limit(limit)
        .all()
    )
    if funcs:
        func_result = _process_funcs_parallel(db, funcs, mode)
        results["functions_processed"] = func_result["processed"]
        results["errors"] += func_result["errors"]

    # Classes with code_snippet - parallel
    classes = (
        db.query(models.Class)
        .join(models.File)
        .filter(
            models.File.project_id == project_id,
            models.Class.code_snippet.isnot(None),
        )
        .limit(limit)
        .all()
    )
    if classes:
        cls_result = _process_classes_parallel(db, classes, mode)
        results["classes_processed"] = cls_result["processed"]
        results["errors"] += cls_result["errors"]

    return {
        "project_id": project_id,
        "project_name": project.name,
        "analysis_mode": mode,
        "summary": results,
    }


@router.post("/reanalyze/batch-migrate-mode")
def batch_migrate_project_modes(
    target_mode: str,
    limit_per_project: int = 50,
    db: Session = Depends(get_db),
):
    """
    Batch-migrate ALL existing projects to a target mode.

    For each project:
    1. Switches analysis_mode to target_mode
    2. Triggers `fill_project_mode_content` Celery task to generate
       content for the new mode

    Parameters:
    - target_mode: "beginner", "expert", or "ai"
    - limit_per_project: max functions to process per project (default 50)

    Use this to migrate all 25 existing (ai-mode) projects to a different mode.
    Call repeatedly to process more.
    """
    if target_mode not in ("beginner", "expert", "ai"):
        raise HTTPException(status_code=400, detail="mode must be 'beginner', 'expert', or 'ai'")

    from .celery_app import celery_app as _celery

    projects = db.query(models.Project).all()
    results = []
    triggered = 0

    for project in projects:
        old_mode = project.analysis_mode

        # Check if there's anything to fill
        base = (
            db.query(models.Function)
            .join(models.File)
            .filter(
                models.File.project_id == project.id,
                models.Function.code_snippet.isnot(None),
            )
        )

        if target_mode == "beginner":
            missing = base.filter(models.Function.explanation_simple.is_(None)).count()
        elif target_mode == "expert":
            missing = base.filter(models.Function.expert_purpose.is_(None)).count()
        else:
            missing = base.filter(models.Function.ai_purpose.is_(None)).count()

        if missing == 0 and project.analysis_mode == target_mode:
            results.append({
                "project_id": project.id,
                "project_name": project.name,
                "old_mode": old_mode,
                "status": "skipped",
                "reason": "already up to date",
            })
            continue

        # Switch mode
        project.analysis_mode = target_mode
        db.commit()

        # Trigger lightweight fill
        _celery.send_task('fill_project_mode_content', args=[project.id])
        triggered += 1
        results.append({
            "project_id": project.id,
            "project_name": project.name,
            "old_mode": old_mode,
            "new_mode": target_mode,
            "status": "migrating",
            "missing_count": missing,
        })

    return {
        "target_mode": target_mode,
        "projects_triggered": triggered,
        "total_projects": len(projects),
        "results": results,
    }


# ── Reparse endpoint (apply improved parsers retroactively) ──


@router.post("/reanalyze/project/{project_id}/reparse")
def reparse_project_files(
    project_id: int,
    db: Session = Depends(get_db),
):
    """
    Re-parse all files in a project using the latest parsers (tree-sitter for JS/TS,
    improved regex for Go/Java/Rust, AST for Python).

    Preserves AI metadata by matching on code_hash. Zero AI cost — only parsing.
    Creates IMPORTS/EXTENDS relationships that older analyses might be missing.
    """
    import hashlib
    from api.parsers import detect_and_parse

    project = crud.get_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    repo_root = _get_repo_root(project)
    if not repo_root:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot locate source repository for project '{project.name}'",
        )

    files = crud.get_files_by_project(db, project_id)
    parsed = 0
    skipped = 0
    errors = 0
    funcs_created = 0
    funcs_preserved = 0
    imp_ext_created = 0
    file_results = []

    for file_obj in files:
        full_path = os.path.join(repo_root, file_obj.file_path)
        if not os.path.isfile(full_path):
            file_results.append({
                "file_path": file_obj.file_path,
                "status": "skipped",
                "reason": "source file not found",
            })
            skipped += 1
            continue

        try:
            # 1. Compute new file_hash
            with open(full_path, "rb") as f:
                new_file_hash = hashlib.md5(f.read()).hexdigest()

            # 2. Re-parse with the latest parsers
            parse_result = detect_and_parse(full_path)

            # 3. Compute code_hash for each function and check for preserved AI metadata
            with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()

            # Build lookup: old functions by (name, start_line) -> Function
            old_funcs = {}
            for f_old in (
                db.query(models.Function)
                .filter(models.Function.file_id == file_obj.id)
                .all()
            ):
                old_funcs[(f_old.name, f_old.start_line)] = f_old

            # 4. Delete OLD function/class/relationship records
            old_func_ids = [f.id for f in old_funcs.values()]
            if old_func_ids:
                db.query(models.FunctionRelationship).filter(
                    models.FunctionRelationship.source_function_id.in_(old_func_ids)
                ).delete(synchronize_session=False)
            db.query(models.Function).filter(
                models.Function.file_id == file_obj.id
            ).delete(synchronize_session=False)
            db.query(models.Class).filter(
                models.Class.file_id == file_obj.id
            ).delete(synchronize_session=False)

            # 5. Create new file record (if hash changed)
            if new_file_hash != file_obj.file_hash:
                file_obj.file_hash = new_file_hash
                file_obj.size_bytes = os.path.getsize(full_path)
                db.flush()

            # 6. Create new function records, preserving AI metadata
            name_to_id = {}
            for func in parse_result.get("functions", []):
                code_snippet = "".join(lines[func["start_line"] - 1 : func["end_line"]])
                code_hash = hashlib.md5(code_snippet.encode("utf-8")).hexdigest()

                # Check if we have an old function to preserve AI metadata from
                preserved_meta = {}
                old_match = old_funcs.get((func["name"], func["start_line"]))
                if old_match and old_match.code_hash == code_hash:
                    # Exact match — preserve all AI metadata
                    preserved_meta = {
                        "ai_purpose": old_match.ai_purpose,
                        "ai_inputs": old_match.ai_inputs,
                        "ai_outputs": old_match.ai_outputs,
                        "ai_side_effects": old_match.ai_side_effects,
                        "return_type": old_match.return_type,
                        "explanation_simple": old_match.explanation_simple,
                        "explanation_logic": old_match.explanation_logic,
                        "expert_purpose": old_match.expert_purpose,
                        "expert_tech_details": old_match.expert_tech_details,
                        "expert_error_handling": old_match.expert_error_handling,
                        "expert_concurrency": old_match.expert_concurrency,
                        "expert_tradeoffs": old_match.expert_tradeoffs,
                        "code_hash": code_hash,
                    }
                    funcs_preserved += 1
                else:
                    # No exact match — check if any function with same code_hash exists
                    cached = db.query(models.Function).filter(
                        models.Function.code_hash == code_hash,
                        models.Function.ai_purpose.isnot(None),
                    ).first()
                    if cached:
                        preserved_meta = {
                            "ai_purpose": cached.ai_purpose,
                            "ai_inputs": cached.ai_inputs,
                            "ai_outputs": cached.ai_outputs,
                            "ai_side_effects": cached.ai_side_effects,
                            "return_type": cached.return_type,
                            "code_hash": code_hash,
                        }
                        funcs_preserved += 1
                    else:
                        preserved_meta = {"code_hash": code_hash}

                # Also check code_hash for beginner/expert metadata
                if not preserved_meta.get("explanation_simple"):
                    cached_beginner = db.query(models.Function).filter(
                        models.Function.code_hash == code_hash,
                        models.Function.explanation_simple.isnot(None),
                    ).first()
                    if cached_beginner:
                        preserved_meta["explanation_simple"] = cached_beginner.explanation_simple
                        preserved_meta["explanation_logic"] = cached_beginner.explanation_logic

                if not preserved_meta.get("expert_purpose"):
                    cached_expert = db.query(models.Function).filter(
                        models.Function.code_hash == code_hash,
                        models.Function.expert_purpose.isnot(None),
                    ).first()
                    if cached_expert:
                        preserved_meta["expert_purpose"] = cached_expert.expert_purpose
                        preserved_meta["expert_tech_details"] = cached_expert.expert_tech_details
                        preserved_meta["expert_error_handling"] = cached_expert.expert_error_handling
                        preserved_meta["expert_concurrency"] = cached_expert.expert_concurrency
                        preserved_meta["expert_tradeoffs"] = cached_expert.expert_tradeoffs

                created_func = crud.create_function(
                    db, file_obj.id,
                    func["name"], func["signature"],
                    func["start_line"], func["end_line"],
                    func["docstring"],
                    code_snippet=code_snippet,
                    language=file_obj.language,
                    **preserved_meta,
                )
                name_to_id[func["name"]] = created_func.id
                funcs_created += 1

            # 7. Create IMPORTS relationships
            for imp in parse_result.get("imports", []):
                if name_to_id:
                    first_id = next(iter(name_to_id.values()))
                    try:
                        crud.create_relationship(
                            db, first_id, imp["target"],
                            None, "IMPORTS", 3, imp.get("line"),
                        )
                        imp_ext_created += 1
                    except Exception:
                        pass

            # 8. Create EXTENDS relationships
            for ext in parse_result.get("extends", []):
                source_id = name_to_id.get(ext["class"])
                if source_id:
                    try:
                        crud.create_relationship(
                            db, source_id, ext["parent"],
                            None, "EXTENDS", 5, ext.get("line"),
                        )
                        imp_ext_created += 1
                    except Exception:
                        pass

            # 9. Create class records
            for cls in parse_result.get("classes", []):
                cls_snippet = "".join(lines[cls["start_line"] - 1 : cls["end_line"]])
                try:
                    crud.create_class(
                        db, file_obj.id,
                        cls["name"], cls["start_line"], cls["end_line"],
                        cls["docstring"],
                        code_snippet=cls_snippet,
                    )
                except Exception:
                    pass

            # 10. Create function records for class methods
            for cls in parse_result.get("classes", []):
                for method in cls.get("methods", []):
                    method_snippet = "".join(lines[method["start_line"] - 1 : method["end_line"]])
                    try:
                        crud.create_function(
                            db, file_obj.id,
                            method["name"], method["signature"],
                            method["start_line"], method["end_line"],
                            method["docstring"],
                            code_snippet=method_snippet,
                            language=file_obj.language,
                        )
                    except Exception:
                        pass

            db.commit()
            parsed += 1
            file_results.append({
                "file_path": file_obj.file_path,
                "status": "parsed",
                "functions": len(parse_result.get("functions", [])),
                "classes": len(parse_result.get("classes", [])),
                "imports": len(parse_result.get("imports", [])),
                "extends": len(parse_result.get("extends", [])),
                "funcs_preserved": funcs_preserved,
            })

        except Exception as e:
            db.rollback()
            errors += 1
            file_results.append({
                "file_path": file_obj.file_path,
                "status": "error",
                "reason": str(e),
            })

    return {
        "project_id": project_id,
        "project_name": project.name,
        "repo_root": repo_root,
        "summary": {
            "total_files": len(files),
            "parsed": parsed,
            "skipped": skipped,
            "errors": errors,
            "functions_created": funcs_created,
            "functions_with_preserved_metadata": funcs_preserved,
            "imp_ext_relationships_created": imp_ext_created,
        },
        "files": file_results[:200],
    }


@router.post("/reanalyze/reparse-all")
def reparse_all_projects(
    db: Session = Depends(get_db),
):
    """
    Batch re-parse ALL projects using the latest parsers.

    Applies tree-sitter (JS/TS), improved generic_parser (Go/Java/Rust),
    and enhanced python_parser retroactively to every project.
    Preserves existing AI metadata. Zero AI cost — only parsing.

    Use this after parser improvements to upgrade all existing data in one call.
    """
    projects = db.query(models.Project).all()
    total_parsed = 0
    total_skipped = 0
    total_errors = 0
    total_funcs_created = 0
    total_funcs_preserved = 0
    project_results = []

    for project in projects:
        repo_root = _get_repo_root(project)
        if not repo_root:
            project_results.append({
                "project_id": project.id,
                "project_name": project.name,
                "status": "skipped",
                "reason": "source repo not accessible",
            })
            total_skipped += 1
            continue

        files = crud.get_files_by_project(db, project.id)
        project_parsed = 0
        project_errors = 0

        for file_obj in files:
            full_path = os.path.join(repo_root, file_obj.file_path)
            if not os.path.isfile(full_path):
                continue

            try:
                # Use the per-file logic from reparse_project_files
                import hashlib
                from api.parsers import detect_and_parse

                with open(full_path, "rb") as f:
                    new_file_hash = hashlib.md5(f.read()).hexdigest()

                parse_result = detect_and_parse(full_path)

                with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()

                # Look up old functions for AI metadata preservation
                old_funcs = {}
                for f_old in (
                    db.query(models.Function)
                    .filter(models.Function.file_id == file_obj.id)
                    .all()
                ):
                    old_funcs[(f_old.name, f_old.start_line)] = f_old

                # Delete old records
                old_func_ids = [f.id for f in old_funcs.values()]
                if old_func_ids:
                    db.query(models.FunctionRelationship).filter(
                        models.FunctionRelationship.source_function_id.in_(old_func_ids)
                    ).delete(synchronize_session=False)
                db.query(models.Function).filter(
                    models.Function.file_id == file_obj.id
                ).delete(synchronize_session=False)
                db.query(models.Class).filter(
                    models.Class.file_id == file_obj.id
                ).delete(synchronize_session=False)

                # Update file hash
                if new_file_hash != file_obj.file_hash:
                    file_obj.file_hash = new_file_hash
                    db.flush()

                # Create new function records
                name_to_id = {}
                for func in parse_result.get("functions", []):
                    code_snippet = "".join(lines[func["start_line"] - 1 : func["end_line"]])
                    code_hash = hashlib.md5(code_snippet.encode("utf-8")).hexdigest()

                    preserved = {}
                    old_match = old_funcs.get((func["name"], func["start_line"]))
                    if old_match and old_match.code_hash == code_hash:
                        preserved = {
                            "ai_purpose": old_match.ai_purpose,
                            "ai_inputs": old_match.ai_inputs,
                            "ai_outputs": old_match.ai_outputs,
                            "ai_side_effects": old_match.ai_side_effects,
                            "return_type": old_match.return_type,
                            "explanation_simple": old_match.explanation_simple,
                            "explanation_logic": old_match.explanation_logic,
                            "expert_purpose": old_match.expert_purpose,
                            "expert_tech_details": old_match.expert_tech_details,
                            "expert_error_handling": old_match.expert_error_handling,
                            "expert_concurrency": old_match.expert_concurrency,
                            "expert_tradeoffs": old_match.expert_tradeoffs,
                        }
                        total_funcs_preserved += 1
                    else:
                        # Cross-function code_hash match
                        cached = db.query(models.Function).filter(
                            models.Function.code_hash == code_hash,
                            models.Function.ai_purpose.isnot(None),
                        ).first()
                        if cached:
                            preserved = {
                                "ai_purpose": cached.ai_purpose,
                                "ai_inputs": cached.ai_inputs,
                                "ai_outputs": cached.ai_outputs,
                                "ai_side_effects": cached.ai_side_effects,
                                "return_type": cached.return_type,
                            }
                            total_funcs_preserved += 1

                    created_func = crud.create_function(
                        db, file_obj.id,
                        func["name"], func["signature"],
                        func["start_line"], func["end_line"],
                        func["docstring"],
                        code_snippet=code_snippet,
                        code_hash=code_hash,
                        language=file_obj.language,
                        **preserved,
                    )
                    name_to_id[func["name"]] = created_func.id
                    total_funcs_created += 1

                # IMPORTS
                for imp in parse_result.get("imports", []):
                    if name_to_id:
                        first_id = next(iter(name_to_id.values()))
                        try:
                            crud.create_relationship(db, first_id, imp["target"], None, "IMPORTS", 3, imp.get("line"))
                        except Exception:
                            pass

                # EXTENDS
                for ext in parse_result.get("extends", []):
                    source_id = name_to_id.get(ext["class"])
                    if source_id:
                        try:
                            crud.create_relationship(db, source_id, ext["parent"], None, "EXTENDS", 5, ext.get("line"))
                        except Exception:
                            pass

                # Classes and methods
                for cls in parse_result.get("classes", []):
                    cls_snippet = "".join(lines[cls["start_line"] - 1 : cls["end_line"]])
                    try:
                        crud.create_class(db, file_obj.id, cls["name"], cls["start_line"], cls["end_line"], cls["docstring"], code_snippet=cls_snippet)
                    except Exception:
                        pass
                    for method in cls.get("methods", []):
                        method_snippet = "".join(lines[method["start_line"] - 1 : method["end_line"]])
                        try:
                            crud.create_function(db, file_obj.id, method["name"], method["signature"], method["start_line"], method["end_line"], method["docstring"], code_snippet=method_snippet, language=file_obj.language)
                        except Exception:
                            pass

                db.commit()
                project_parsed += 1

            except Exception:
                db.rollback()
                project_errors += 1

        total_parsed += project_parsed
        total_errors += project_errors
        project_results.append({
            "project_id": project.id,
            "project_name": project.name,
            "status": "processed",
            "repo_root": repo_root,
            "files_parsed": project_parsed,
            "files_errors": project_errors,
            "total_files": len(files),
        })

    return {
        "summary": {
            "total_projects": len(projects),
            "processed": total_parsed + total_skipped - total_errors,
            "skipped_source_not_found": total_skipped,
            "errors": total_errors,
            "functions_created": total_funcs_created,
            "functions_with_preserved_metadata": total_funcs_preserved,
        },
        "projects": project_results,
    }
