"""Class-level API endpoints.

Provides:
- Search classes across all projects
- Get class detail with methods
- List classes in a file
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from . import crud, models
from .database import get_db
from .search_service import search_classes

router = APIRouter()


@router.get("/classes/search")
def search_classes_endpoint(
    q: str = Query(..., min_length=1, description="Search query"),
    language: str | None = Query(None, description="Filter by language"),
    project_id: int | None = Query(None, description="Filter by project ID"),
    limit: int = Query(20, ge=1, le=100, description="Max results"),
    offset: int = Query(0, ge=0, description="Result offset for pagination"),
    db: Session = Depends(get_db),
):
    """Full-text search across analyzed classes by name, docstring, and code."""
    results = search_classes(
        db, query=q, language=language, project_id=project_id, limit=limit, offset=offset
    )
    return {
        "results": results,
        "total": len(results),
        "query": q,
        "pagination": {"limit": limit, "offset": offset, "has_more": len(results) == limit},
    }


@router.get("/classes/{class_id}")
def get_class_detail(
    class_id: int,
    include_methods: bool = Query(True, description="Include method functions"),
    db: Session = Depends(get_db),
):
    """Get class detail with metadata and optional method list."""
    cls = db.query(models.Class).filter(models.Class.id == class_id).first()
    if not cls:
        raise HTTPException(status_code=404, detail="Class not found")

    file_obj = db.query(models.File).filter(models.File.id == cls.file_id).first()
    project = None
    if file_obj:
        project = db.query(models.Project).filter(models.Project.id == file_obj.project_id).first()

    result = {
        "id": cls.id,
        "name": cls.name,
        "language": file_obj.language if file_obj else None,
        "start_line": cls.start_line,
        "end_line": cls.end_line,
        "docstring": cls.docstring,
        "code_snippet": cls.code_snippet,
        "explanation_simple": cls.explanation_simple,
        "explanation_architecture": cls.explanation_architecture,
        "ai_purpose": cls.ai_purpose,
        "ai_interfaces": cls.ai_interfaces,
        "expert_purpose": cls.expert_purpose,
        "expert_architecture": cls.expert_architecture,
        "expert_responsibilities": cls.expert_responsibilities,
        "expert_extension_points": cls.expert_extension_points,
        "file_id": cls.file_id,
        "file_path": file_obj.file_path if file_obj else None,
        "project_id": project.id if project else None,
        "project_name": project.name if project else None,
    }

    if include_methods:
        methods = (
            db.query(models.Function)
            .filter(models.Function.file_id == cls.file_id)
            .filter(models.Function.name.startswith(f"{cls.name}."))
            .all()
        ) or (
            # Fallback: methods within the class line range
            db.query(models.Function)
            .filter(
                models.Function.file_id == cls.file_id,
                models.Function.start_line >= cls.start_line,
                models.Function.end_line <= cls.end_line,
            )
            .all()
        )
        result["methods"] = [
            {
                "id": m.id,
                "name": m.name,
                "signature": m.signature,
                "start_line": m.start_line,
                "end_line": m.end_line,
                "code_snippet": m.code_snippet,
                "explanation_simple": m.explanation_simple,
            }
            for m in methods
        ]
        result["method_count"] = len(methods)

    return result
