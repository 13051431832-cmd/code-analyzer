"""
AI-oriented API endpoints.

Provides compact, structured responses designed for AI program consumption
rather than human readability. All endpoints return minimal JSON with
AI-oriented metadata (purpose, inputs, outputs, side_effects) and call graph info.

Usage by AI:
- get_ai_context: Understand what a function does and how to call it
- get_ai_neighborhood: Understand a function's role in the call graph
- ai_search: Find functions by purpose/signature, get AI-optimized results
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from . import search_service
from .database import get_db

router = APIRouter()


@router.get("/ai/functions/{function_id}/context")
def ai_function_context(
    function_id: int,
    db: Session = Depends(get_db),
):
    """
    Ultra-compact AI-oriented function context.

    Returns only what an AI needs to understand and use a function:
    - ai.purpose: one-line description
    - ai.inputs: structured parameter definitions (name, type, description)
    - ai.outputs: return value description
    - ai.side_effects: state changes, I/O, errors
    - graph.callers/callees: relationship counts
    - loc: file and project context

    Purpose: AI should call this BEFORE attempting to use a function,
    to ensure correct invocation and understand side effects.
    """
    result = search_service.get_ai_context(db, function_id)
    if not result:
        raise HTTPException(status_code=404, detail="Function not found")
    return result


@router.get("/ai/functions/{function_id}/neighborhood")
def ai_function_neighborhood(
    function_id: int,
    depth: int = Query(1, ge=1, le=3, description="Traversal depth"),
    db: Session = Depends(get_db),
):
    """
    Get a function and its call graph neighborhood for AI consumption.

    Returns a compact graph where each node has name, signature, purpose, return_type.
    Edges show caller/callee relationships.

    depth=1: immediate callers and callees only
    depth=2: one more level of transitive callers/callees

    Purpose: AI should call this to understand how a function fits into
    the broader codebase, enabling safe refactoring and modification.
    """
    result = search_service.get_function_neighborhood(db, function_id, depth=depth)
    if not result:
        raise HTTPException(status_code=404, detail="Function not found")
    return result


@router.get("/ai/search")
def ai_search(
    q: str = Query(..., min_length=1, description="Search query for AI consumption"),
    limit: int = Query(10, ge=1, le=50, description="Max results"),
    language: str | None = Query(None, description="Filter by language"),
    project_id: int | None = Query(None, description="Filter by project ID"),
    db: Session = Depends(get_db),
):
    """
    AI-optimized search. Returns results with AI metadata prioritized.

    Response prioritizes ai.purpose, ai.inputs, ai.outputs, ai.side_effects
    over human-oriented explanation fields. Designed for AI tool use.

    Use this when an AI agent needs to find relevant functions by task description
    (e.g., "find rate limiting middleware" or "find user validation function").
    """
    results = search_service.search_code(
        db, query=q, language=language, project_id=project_id, limit=limit
    )

    # Return compact AI-oriented format
    compact = [
        {
            "id": r["id"],
            "name": r["name"],
            "sig": r["signature"],
            "return_type": r["return_type"],
            "ai": {
                "purpose": r["ai_purpose"],
                "inputs": r["ai_inputs"],
                "outputs": r["ai_outputs"],
                "side_effects": r["ai_side_effects"],
            },
            "loc": {
                "file": r["file_path"],
                "project": r["project_name"],
                "lines": f"{r['start_line']}-{r['end_line']}",
            },
            "graph": {
                "callers": r["caller_count"],
                "callees": r["callee_count"],
            },
            "score": r["score"],
        }
        for r in results
    ]

    return {
        "results": compact,
        "total": len(compact),
        "query": q,
    }
