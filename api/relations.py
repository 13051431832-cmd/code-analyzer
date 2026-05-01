"""
Call graph and impact analysis API endpoints.

Provides:
- Function context (callers + callees)
- BFS impact chain traversal
- Relationship search
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from . import crud, models
from .database import get_db

router = APIRouter()


@router.get("/functions/{function_id}/context")
def get_function_context(
    function_id: int,
    db: Session = Depends(get_db),
):
    """
    Get the call context for a function: who calls it (callers) and who it calls (callees).
    Returns caller/callee lists with name, signature, file path, and code snippet preview.
    """
    func = crud.get_function_by_id(db, function_id)
    if not func:
        raise HTTPException(status_code=404, detail="Function not found")

    callers = crud.get_callers(db, function_id, limit=50)
    callees = crud.get_callees(db, function_id, limit=50)

    # Enrich with code preview snippets
    for caller in callers:
        caller_func = crud.get_function_by_id(db, caller["function_id"])
        if caller_func and caller_func.code_snippet:
            # First 5 lines of code as preview
            lines = caller_func.code_snippet.split("\n")[:5]
            caller["code_preview"] = "\n".join(lines)

    for callee in callees:
        tid = callee.get("target_function_id")
        if tid:
            callee_func = crud.get_function_by_id(db, tid)
            if callee_func and callee_func.code_snippet:
                lines = callee_func.code_snippet.split("\n")[:5]
                callee["code_preview"] = "\n".join(lines)

    # File context
    file_obj = db.query(models.File).filter(models.File.id == func.file_id).first()

    return {
        "function": {
            "id": func.id,
            "name": func.name,
            "signature": func.signature,
            "language": func.language,
            "file_path": file_obj.file_path if file_obj else None,
        },
        "callers": callers,
        "callees": callees,
        "stats": {
            "caller_count": len(callers),
            "callee_count": len(callees),
        },
    }


@router.get("/functions/{function_id}/impact")
def get_function_impact(
    function_id: int,
    depth: int = Query(3, ge=1, le=10, description="Maximum traversal depth"),
    direction: str = Query("upstream", regex="^(upstream|downstream)$"),
    db: Session = Depends(get_db),
):
    """
    BFS traversal of the function call impact chain.

    direction='upstream': find all functions that (transitively) call this function
        → 'who is affected if I modify this function?'

    direction='downstream': find all functions that this function (transitively) calls
        → 'what does this function depend on?'
    """
    func = crud.get_function_by_id(db, function_id)
    if not func:
        raise HTTPException(status_code=404, detail="Function not found")

    result = crud.get_impact_chain(db, function_id, direction=direction, max_depth=depth)

    return {
        "function": {
            "id": func.id,
            "name": func.name,
            "signature": func.signature,
        },
        "direction": direction,
        "depth": depth,
        "total_nodes": len(result["nodes"]),
        "nodes": result["nodes"],
        "edges": result["edges"],
    }


@router.get("/relationships/search")
def search_relationships(
    target: str = Query(..., min_length=1, description="Target function name to search for"),
    relationship_type: str = Query("CALLS", regex="^(CALLS|IMPORTS|EXTENDS)$"),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """
    Search for relationships by target function name.
    Returns all relationships where target_function_name matches.
    """
    rows = (
        db.query(models.FunctionRelationship)
        .filter(
            models.FunctionRelationship.target_function_name.ilike(f"%{target}%"),
            models.FunctionRelationship.relationship_type == relationship_type,
        )
        .limit(limit)
        .all()
    )

    results = []
    for rel in rows:
        src_func = db.query(models.Function).filter(models.Function.id == rel.source_function_id).first()
        src_sig = src_func.signature if src_func else None
        file_obj = db.query(models.File).filter(models.File.id == rel.target_file_id).first() if rel.target_file_id else None
        results.append({
            "id": rel.id,
            "source_function_id": rel.source_function_id,
            "source_name": src_func.name if src_func else None,
            "source_signature": src_sig,
            "target_name": rel.target_function_name,
            "target_file_path": file_obj.file_path if file_obj else None,
            "type": rel.relationship_type,
            "confidence": rel.confidence,
            "context_line": rel.context_line,
        })

    return {
        "results": results,
        "total": len(results),
        "query": target,
    }


@router.get("/relationships/stats")
def get_relationship_stats(
    db: Session = Depends(get_db),
):
    """Get aggregate stats about all function relationships."""
    stats = crud.get_relationship_stats(db)
    total = sum(stats.values())
    return {
        "total_relationships": total,
        "by_type": stats,
    }
