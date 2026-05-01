"""Search and reference API endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from . import database, search_service, embedding_service
from .models import FunctionRelationship

router = APIRouter()


@router.get("/search")
def search_functions(
    q: str = Query(..., min_length=1, description="Search query"),
    language: str | None = Query(None, description="Filter by language"),
    project_id: int | None = Query(None, description="Filter by project ID"),
    limit: int = Query(20, ge=1, le=100, description="Max results"),
    offset: int = Query(0, ge=0, description="Result offset for pagination"),
    group_by: str | None = Query(None, regex="^(file|project)$", description="Group results by file or project"),
    db: Session = Depends(database.get_db),
):
    """
    Full-text search across all analyzed functions.
    Returns ranked results with code snippets and AI explanations.

    Use group_by='file' to group results by file_path — useful for understanding
    how multiple matched functions work together within the same file.
    Use group_by='project' to group results by project_name.
    """
    results = search_service.search_code(
        db, query=q, language=language, project_id=project_id, limit=limit, offset=offset
    )

    # Add context stats about the overall relationship graph
    from sqlalchemy import func as safunc
    total_rels = db.query(safunc.count(FunctionRelationship.id)).scalar() or 0

    if group_by == "file":
        grouped = search_service.group_results_by_file(results)
        return {
            "results": results,
            "total": len(results),
            "query": q,
            "group_by": "file",
            "groups": grouped,
            "context_stats": {
                "total_relationships": total_rels,
            },
            "pagination": {"limit": limit, "offset": offset, "has_more": len(results) == limit},
        }

    if group_by == "project":
        grouped = search_service.group_results_by_project(results)
        return {
            "results": results,
            "total": len(results),
            "query": q,
            "group_by": "project",
            "groups": grouped,
            "context_stats": {
                "total_relationships": total_rels,
            },
            "pagination": {"limit": limit, "offset": offset, "has_more": len(results) == limit},
        }

    return {
        "results": results,
        "total": len(results),
        "query": q,
        "context_stats": {
            "total_relationships": total_rels,
        },
        "pagination": {"limit": limit, "offset": offset, "has_more": len(results) == limit},
    }


@router.get("/reference")
def code_reference(
    q: str = Query(..., min_length=1, description="Search query for AI reference"),
    limit: int = Query(5, ge=1, le=20, description="Max results"),
    db: Session = Depends(database.get_db),
):
    """
    Compact search endpoint designed for AI program consumption.
    Returns minimal essential fields: name, code, explanation, context.
    """
    results = search_service.get_reference_context(db, query=q, limit=limit)
    return {"results": results, "query": q}


@router.get("/functions/{function_id}/detail")
def function_detail(
    function_id: int,
    db: Session = Depends(database.get_db),
):
    """
    Get full detail for a specific function, including file and project context.
    """
    result = search_service.get_function_detail(db, function_id)
    if not result:
        raise HTTPException(status_code=404, detail="Function not found")
    return result


@router.get("/search/semantic")
def semantic_search(
    q: str = Query(..., min_length=1, description="Search query"),
    language: str | None = Query(None, description="Filter by language"),
    project_id: int | None = Query(None, description="Filter by project ID"),
    limit: int = Query(20, ge=1, le=100, description="Max results"),
    db: Session = Depends(database.get_db),
):
    """
    Semantic search using embedding similarity (cosine distance).
    Finds functions conceptually similar to the query, not just keyword matches.
    Falls back to empty results if embeddings are not configured.
    """
    results = embedding_service.semantic_search(
        db, query=q, language=language, project_id=project_id, limit=limit
    )

    return {
        "results": results,
        "total": len(results),
        "query": q,
        "mode": "semantic",
        "pagination": {"limit": limit, "offset": 0, "has_more": len(results) == limit},
    }


@router.get("/search/hybrid")
def hybrid_search(
    q: str = Query(..., min_length=1, description="Search query"),
    language: str | None = Query(None, description="Filter by language"),
    project_id: int | None = Query(None, description="Filter by project ID"),
    limit: int = Query(20, ge=1, le=100, description="Max results"),
    semantic_weight: float = Query(0.5, ge=0.0, le=1.0, description="0=keyword only, 1=semantic only"),
    db: Session = Depends(database.get_db),
):
    """
    Hybrid search combining keyword (full-text) and semantic (embedding) scores.
    Uses reciprocal rank fusion (RRF) to rank combined results.

    - semantic_weight=0: pure keyword search
    - semantic_weight=1: pure semantic search
    - semantic_weight=0.5: balanced (default)
    """
    results = embedding_service.hybrid_search(
        db, query=q, language=language, project_id=project_id,
        limit=limit, semantic_weight=semantic_weight,
    )

    return {
        "results": results,
        "total": len(results),
        "query": q,
        "mode": "hybrid",
        "semantic_weight": semantic_weight,
        "pagination": {"limit": limit, "offset": 0, "has_more": len(results) == limit},
    }
