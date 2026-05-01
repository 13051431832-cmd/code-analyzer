"""
File-level API endpoints.

Provides:
- List all functions in a file
- Find file by project + path
- File metadata with function call context
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from . import crud, models
from .database import get_db

router = APIRouter()


@router.get("/files/by-path")
def get_file_by_path(
    project_id: int = Query(..., description="Project ID"),
    file_path: str = Query(..., description="File path (e.g. 'api/apps/user_app.py')"),
    include_functions: bool = Query(True, description="Include function list"),
    db: Session = Depends(get_db),
):
    """
    Find a file by project ID and file path, then return its details and functions.
    Useful when you know the project and file path but not the file ID.
    """
    file_obj = crud.get_file_by_path(db, project_id, file_path)
    if not file_obj:
        raise HTTPException(
            status_code=404,
            detail=f"File not found: project_id={project_id}, path={file_path}",
        )

    return _build_file_response(file_obj, db, include_functions)


@router.get("/files/{file_id}")
def get_file_detail(
    file_id: int,
    include_functions: bool = Query(True, description="Include function list"),
    db: Session = Depends(get_db),
):
    """
    Get file details, optionally with all its functions.
    Each function includes signature, explanation, and relationship counts.
    """
    file_obj = db.query(models.File).filter(models.File.id == file_id).first()
    if not file_obj:
        raise HTTPException(status_code=404, detail="File not found")

    return _build_file_response(file_obj, db, include_functions)


def _build_file_response(file_obj: models.File, db: Session, include_functions: bool):
    """Shared response builder for file endpoints."""
    project = db.query(models.Project).filter(models.Project.id == file_obj.project_id).first()

    result = {
        "id": file_obj.id,
        "project_id": file_obj.project_id,
        "project_name": project.name if project else None,
        "file_path": file_obj.file_path,
        "language": file_obj.language,
        "size_bytes": file_obj.size_bytes,
    }

    if include_functions:
        functions = crud.get_functions_by_file(db, file_obj.id)
        func_ids = [f.id for f in functions]
        rel_counts = crud.get_relationship_counts(db, func_ids)

        result["functions"] = [
            {
                "id": f.id,
                "name": f.name,
                "signature": f.signature,
                "language": f.language,
                "start_line": f.start_line,
                "end_line": f.end_line,
                "docstring": f.docstring,
                "code_snippet": f.code_snippet,
                "explanation_simple": f.explanation_simple,
                "explanation_logic": f.explanation_logic,
                "ai_purpose": f.ai_purpose,
                "ai_inputs": f.ai_inputs,
                "ai_outputs": f.ai_outputs,
                "ai_side_effects": f.ai_side_effects,
                "return_type": f.return_type,
                "caller_count": rel_counts.get(f.id, {}).get("callers", 0),
                "callee_count": rel_counts.get(f.id, {}).get("callees", 0),
            }
            for f in functions
        ]
        result["function_count"] = len(functions)

    return result
