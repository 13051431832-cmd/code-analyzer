"""Full-text search service using PostgreSQL tsvector."""

from __future__ import annotations

from sqlalchemy import text, func as safunc
from sqlalchemy.orm import Session
from . import models
from .config import config

# Languages that have been analyzed
SEARCHABLE_LANGUAGES = frozenset({
    "python", "javascript", "typescript", "go", "java", "rust"
})


def _build_searchable_text(func) -> str:
    """Concatenate all text fields of a function into one searchable string."""
    parts = [
        func.name or "",
        func.signature or "",
        func.docstring or "",
        func.explanation_simple or "",
        func.explanation_logic or "",
        func.ai_purpose or "",
        func.code_snippet or "",
    ]
    return " ".join(parts)


def get_search_index_sql() -> str:
    """
    Return the SQL expression for creating a GIN index on the searchable text.
    Includes AI-oriented fields for AI-efficient retrieval.
    """
    return """
    CREATE INDEX IF NOT EXISTS ix_functions_search_text
    ON functions
    USING GIN (to_tsvector('simple',
        coalesce(name, '') || ' ' ||
        coalesce(signature, '') || ' ' ||
        coalesce(docstring, '') || ' ' ||
        coalesce(explanation_simple, '') || ' ' ||
        coalesce(explanation_logic, '') || ' ' ||
        coalesce(ai_purpose, '') || ' ' ||
        coalesce(code_snippet, '')
    ));
    """


def get_class_search_index_sql() -> str:
    """GIN index for full-text search on classes (includes AI fields)."""
    return """
    CREATE INDEX IF NOT EXISTS ix_classes_search_text
    ON classes
    USING GIN (to_tsvector('simple',
        coalesce(name, '') || ' ' ||
        coalesce(docstring, '') || ' ' ||
        coalesce(explanation_simple, '') || ' ' ||
        coalesce(explanation_architecture, '') || ' ' ||
        coalesce(ai_purpose, '') || ' ' ||
        coalesce(code_snippet, '')
    ));
    """


def _get_relationship_counts(db: Session, func_ids: list[int]) -> dict[int, dict]:
    """Get caller_count and callee_count for a list of function IDs."""
    if not func_ids:
        return {}

    # Caller count: how many functions call each function
    caller_counts = dict(
        db.query(
            models.FunctionRelationship.target_function_name,
            safunc.count(models.FunctionRelationship.id),
        )
        .filter(
            models.FunctionRelationship.source_function_id.in_(func_ids),
            models.FunctionRelationship.relationship_type == "CALLS",
        )
        .group_by(models.FunctionRelationship.target_function_name)
        .all()
    )

    # Callee count: how many functions each function calls
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


def search_code(
    db: Session,
    query: str,
    language: str | None = None,
    project_id: int | None = None,
    limit: int = 20,
) -> list[dict]:
    """
    Full-text search across all analyzed functions.
    Returns ranked results with metadata.
    """
    if not query or not query.strip():
        return []

    limit = min(limit, config.SEARCH_MAX_LIMIT)

    # Build WHERE clauses
    conditions = []
    params: dict = {"query": query}

    if language:
        conditions.append("f.language = :language")
        params["language"] = language
    if project_id is not None:
        conditions.append("p.id = :project_id")
        params["project_id"] = project_id

    where_clause = " AND ".join(conditions) if conditions else "TRUE"

    sql = text(f"""
        SELECT
            f.id,
            f.name,
            f.signature,
            f.language,
            f.start_line,
            f.end_line,
            f.code_snippet,
            f.explanation_simple,
            f.explanation_logic,
            f.ai_purpose,
            f.ai_inputs,
            f.ai_outputs,
            f.ai_side_effects,
            f.return_type,
            f.expert_purpose,
            f.expert_tech_details,
            f.expert_error_handling,
            f.expert_concurrency,
            f.expert_tradeoffs,
            f.docstring,
            f.file_id,
            fl.file_path,
            p.id AS project_id,
            p.name AS project_name,
            ts_rank(
                to_tsvector('simple',
                    coalesce(f.name, '') || ' ' ||
                    coalesce(f.signature, '') || ' ' ||
                    coalesce(f.docstring, '') || ' ' ||
                    coalesce(f.explanation_simple, '') || ' ' ||
                    coalesce(f.explanation_logic, '') || ' ' ||
                    coalesce(f.ai_purpose, '') || ' ' ||
                    coalesce(f.code_snippet, '')
                ),
                websearch_to_tsquery('simple', :query)
            ) AS rank
        FROM functions f
        JOIN files fl ON fl.id = f.file_id
        JOIN projects p ON p.id = fl.project_id
        WHERE
            {where_clause}
            AND to_tsvector('simple',
                coalesce(f.name, '') || ' ' ||
                coalesce(f.signature, '') || ' ' ||
                coalesce(f.docstring, '') || ' ' ||
                coalesce(f.explanation_simple, '') || ' ' ||
                coalesce(f.explanation_logic, '') || ' ' ||
                coalesce(f.ai_purpose, '') || ' ' ||
                coalesce(f.code_snippet, '')
            ) @@ websearch_to_tsquery('simple', :query)
        ORDER BY rank DESC
        LIMIT :limit
    """)

    params["limit"] = limit

    rows = db.execute(sql, params).fetchall()

    # Enrich with relationship counts
    func_ids = [row.id for row in rows]
    rel_counts = _get_relationship_counts(db, func_ids)

    return [
        {
            "id": row.id,
            "name": row.name,
            "signature": row.signature,
            "language": row.language,
            "start_line": row.start_line,
            "end_line": row.end_line,
            "code_snippet": row.code_snippet,
            "explanation_simple": row.explanation_simple,
            "explanation_logic": row.explanation_logic,
            "ai_purpose": row.ai_purpose,
            "ai_inputs": row.ai_inputs,
            "ai_outputs": row.ai_outputs,
            "ai_side_effects": row.ai_side_effects,
            "return_type": row.return_type,
            "expert_purpose": row.expert_purpose,
            "expert_tech_details": row.expert_tech_details,
            "expert_error_handling": row.expert_error_handling,
            "expert_concurrency": row.expert_concurrency,
            "expert_tradeoffs": row.expert_tradeoffs,
            "docstring": row.docstring,
            "file_id": row.file_id,
            "file_path": row.file_path,
            "project_id": row.project_id,
            "project_name": row.project_name,
            "score": round(float(row.rank), 4),
            "caller_count": rel_counts.get(row.id, {}).get("callers", 0),
            "callee_count": rel_counts.get(row.id, {}).get("callees", 0),
        }
        for row in rows
    ]


def get_reference_context(db: Session, query: str, limit: int = 5) -> list[dict]:
    """
    Simplified search endpoint for AI program consumption.
    Returns compact JSON with AI-oriented fields prioritized.
    """
    results = search_code(db, query, limit=limit)
    return [
        {
            "name": r["name"],
            "signature": r["signature"],
            "language": r["language"],
            "code": r["code_snippet"],
            "ai": {
                "purpose": r["ai_purpose"],
                "inputs": r["ai_inputs"],
                "outputs": r["ai_outputs"],
                "side_effects": r["ai_side_effects"],
            },
            "return_type": r["return_type"],
            "context": {
                "file_path": r["file_path"],
                "project": r["project_name"],
                "start_line": r["start_line"],
                "end_line": r["end_line"],
            },
            "score": r["score"],
        }
        for r in results
    ]


def get_ai_context(db: Session, function_id: int) -> dict | None:
    """
    Ultra-compact AI-oriented function context.
    Returns only what an AI needs to understand and use a function.
    No human explanations, no prose — just structured metadata + call graph summary.
    """
    func = db.query(models.Function).filter(models.Function.id == function_id).first()
    if not func:
        return None

    file_obj = db.query(models.File).filter(models.File.id == func.file_id).first()
    project = db.query(models.Project).filter(models.Project.id == file_obj.project_id).first() if file_obj else None

    # Get caller/callee counts
    counts = _get_relationship_counts(db, [function_id]).get(function_id, {"callers": 0, "callees": 0})

    return {
        "id": func.id,
        "name": func.name,
        "sig": func.signature,
        "return_type": func.return_type,
        "ai": {
            "purpose": func.ai_purpose,
            "inputs": func.ai_inputs,
            "outputs": func.ai_outputs,
            "side_effects": func.ai_side_effects,
        },
        "loc": {
            "file": file_obj.file_path if file_obj else None,
            "project": project.name if project else None,
            "lines": f"{func.start_line}-{func.end_line}",
        },
        "graph": {
            "callers": counts["callers"],
            "callees": counts["callees"],
        },
    }


def get_function_neighborhood(db: Session, function_id: int, depth: int = 1) -> dict | None:
    """
    Get a function and its immediate neighbors (callers + callees) for AI consumption.
    Returns a compact graph neighborhood without human-oriented explanations.
    """
    from collections import deque

    center = db.query(models.Function).filter(models.Function.id == function_id).first()
    if not center:
        return None

    nodes = {}
    edges = []
    visited = {function_id}

    # Center node
    center_file = db.query(models.File).filter(models.File.id == center.file_id).first()
    nodes[function_id] = {
        "name": center.name,
        "sig": center.signature,
        "purpose": center.ai_purpose,
        "return_type": center.return_type,
    }

    queue = deque([(function_id, 0)])
    while queue:
        current_id, current_depth = queue.popleft()
        if current_depth >= depth:
            continue

        current_func = db.query(models.Function).filter(models.Function.id == current_id).first()
        if not current_func:
            continue

        # Callers (upstream)
        caller_rels = (
            db.query(models.FunctionRelationship)
            .filter(
                models.FunctionRelationship.target_function_name == current_func.name,
                models.FunctionRelationship.relationship_type == "CALLS",
            )
            .all()
        )
        for rel in caller_rels:
            if rel.source_function_id not in visited:
                visited.add(rel.source_function_id)
                src = db.query(models.Function).filter(models.Function.id == rel.source_function_id).first()
                if src:
                    nodes[rel.source_function_id] = {
                        "name": src.name,
                        "sig": src.signature,
                        "purpose": src.ai_purpose,
                        "return_type": src.return_type,
                    }
                    queue.append((rel.source_function_id, current_depth + 1))
            edges.append({"from": rel.source_function_id, "to": current_id, "type": "CALLS"})

        # Callees (downstream)
        callee_rels = (
            db.query(models.FunctionRelationship)
            .filter(
                models.FunctionRelationship.source_function_id == current_id,
                models.FunctionRelationship.relationship_type == "CALLS",
            )
            .all()
        )
        for rel in callee_rels:
            target_func = db.query(models.Function).filter(
                models.Function.name == rel.target_function_name,
            ).first()
            if target_func and target_func.id not in visited:
                visited.add(target_func.id)
                nodes[target_func.id] = {
                    "name": target_func.name,
                    "sig": target_func.signature,
                    "purpose": target_func.ai_purpose,
                    "return_type": target_func.return_type,
                }
                queue.append((target_func.id, current_depth + 1))
            edges.append({"from": current_id, "to": rel.target_function_name, "type": "CALLS"})

    # Convert nodes dict to a list for cleaner output
    node_list = [{"id": nid, **n} for nid, n in sorted(nodes.items())]

    return {"center": function_id, "nodes": node_list, "edges": edges}


def group_results_by_file(results: list[dict]) -> dict:
    """
    Group search results by file_path.
    Returns {file_path: {project_name, language, functions: [...]}}.
    """
    groups: dict = {}
    for r in results:
        key = r["file_path"]
        if key not in groups:
            groups[key] = {
                "file_path": key,
                "project_name": r["project_name"],
                "project_id": r["project_id"],
                "file_id": r["file_id"],
                "language": r.get("language"),
                "function_count": 0,
                "functions": [],
            }
        groups[key]["functions"].append({
            "id": r["id"],
            "name": r["name"],
            "signature": r["signature"],
            "start_line": r["start_line"],
            "end_line": r["end_line"],
            "score": r["score"],
            "explanation_simple": r.get("explanation_simple"),
        })
        groups[key]["function_count"] += 1

    # Sort: groups with most matches first, functions within group by score desc
    sorted_groups = sorted(groups.values(), key=lambda g: g["function_count"], reverse=True)
    for g in sorted_groups:
        g["functions"].sort(key=lambda f: f["score"], reverse=True)

    return {"files": sorted_groups, "file_count": len(sorted_groups)}


def group_results_by_project(results: list[dict]) -> dict:
    """
    Group search results by project_name.
    Returns {project_name: {project_id, function_count, files: [...]}}.
    """
    groups: dict = {}
    for r in results:
        key = r["project_name"]
        if key not in groups:
            groups[key] = {
                "project_name": key,
                "project_id": r["project_id"],
                "function_count": 0,
                "files": {},
            }
        groups[key]["function_count"] += 1

        # Also track per-file within project
        fpath = r["file_path"]
        if fpath not in groups[key]["files"]:
            groups[key]["files"][fpath] = {
                "file_path": fpath,
                "file_id": r["file_id"],
                "function_count": 0,
            }
        groups[key]["files"][fpath]["function_count"] += 1

    # Convert inner files dict to list
    for g in groups.values():
        g["files"] = sorted(g["files"].values(), key=lambda f: f["function_count"], reverse=True)

    sorted_groups = sorted(groups.values(), key=lambda g: g["function_count"], reverse=True)
    return {"projects": sorted_groups, "project_count": len(sorted_groups)}


def search_classes(
    db: Session,
    query: str,
    language: str | None = None,
    project_id: int | None = None,
    limit: int = 20,
) -> list[dict]:
    """Full-text search across analyzed classes."""
    if not query or not query.strip():
        return []

    limit = min(limit, config.SEARCH_MAX_LIMIT)

    conditions = []
    params: dict = {"query": query}

    if language:
        conditions.append("fl.language = :language")
        params["language"] = language
    if project_id is not None:
        conditions.append("p.id = :project_id")
        params["project_id"] = project_id

    where_clause = " AND ".join(conditions) if conditions else "TRUE"

    sql = text(f"""
        SELECT
            c.id,
            c.name,
            c.start_line,
            c.end_line,
            c.docstring,
            c.code_snippet,
            c.explanation_simple,
            c.explanation_architecture,
            c.ai_purpose,
            c.ai_interfaces,
            c.expert_purpose,
            c.expert_architecture,
            c.expert_responsibilities,
            c.expert_extension_points,
            c.file_id,
            fl.file_path,
            fl.language,
            p.id AS project_id,
            p.name AS project_name,
            ts_rank(
                to_tsvector('simple',
                    coalesce(c.name, '') || ' ' ||
                    coalesce(c.docstring, '') || ' ' ||
                    coalesce(c.explanation_simple, '') || ' ' ||
                    coalesce(c.explanation_architecture, '') || ' ' ||
                    coalesce(c.ai_purpose, '') || ' ' ||
                    coalesce(c.code_snippet, '')
                ),
                websearch_to_tsquery('simple', :query)
            ) AS rank
        FROM classes c
        JOIN files fl ON fl.id = c.file_id
        JOIN projects p ON p.id = fl.project_id
        WHERE
            {where_clause}
            AND to_tsvector('simple',
                coalesce(c.name, '') || ' ' ||
                coalesce(c.docstring, '') || ' ' ||
                coalesce(c.explanation_simple, '') || ' ' ||
                coalesce(c.explanation_architecture, '') || ' ' ||
                coalesce(c.ai_purpose, '') || ' ' ||
                coalesce(c.code_snippet, '')
            ) @@ websearch_to_tsquery('simple', :query)
        ORDER BY rank DESC
        LIMIT :limit
    """)

    params["limit"] = limit
    rows = db.execute(sql, params).fetchall()

    return [
        {
            "id": row.id,
            "name": row.name,
            "language": row.language,
            "start_line": row.start_line,
            "end_line": row.end_line,
            "code_snippet": row.code_snippet,
            "explanation_simple": row.explanation_simple,
            "explanation_architecture": row.explanation_architecture,
            "ai_purpose": row.ai_purpose,
            "ai_interfaces": row.ai_interfaces,
            "expert_purpose": row.expert_purpose,
            "expert_architecture": row.expert_architecture,
            "expert_responsibilities": row.expert_responsibilities,
            "expert_extension_points": row.expert_extension_points,
            "docstring": row.docstring,
            "file_id": row.file_id,
            "file_path": row.file_path,
            "project_id": row.project_id,
            "project_name": row.project_name,
            "score": round(float(row.rank), 4),
        }
        for row in rows
    ]


def get_function_detail(db: Session, function_id: int) -> dict | None:
    """
    Get full details for a specific function, including project and file context.
    """
    func = db.query(models.Function).filter(models.Function.id == function_id).first()
    if not func:
        return None

    file_obj = db.query(models.File).filter(models.File.id == func.file_id).first()
    project = None
    if file_obj:
        project = db.query(models.Project).filter(models.Project.id == file_obj.project_id).first()

    # Get relationship counts
    counts = _get_relationship_counts(db, [function_id]).get(function_id, {"callers": 0, "callees": 0})

    return {
        "id": func.id,
        "name": func.name,
        "signature": func.signature,
        "language": func.language,
        "start_line": func.start_line,
        "end_line": func.end_line,
        "code_snippet": func.code_snippet,
        "explanation_simple": func.explanation_simple,
        "explanation_logic": func.explanation_logic,
        "ai_purpose": func.ai_purpose,
        "ai_inputs": func.ai_inputs,
        "ai_outputs": func.ai_outputs,
        "ai_side_effects": func.ai_side_effects,
        "return_type": func.return_type,
        "expert_purpose": func.expert_purpose,
        "expert_tech_details": func.expert_tech_details,
        "expert_error_handling": func.expert_error_handling,
        "expert_concurrency": func.expert_concurrency,
        "expert_tradeoffs": func.expert_tradeoffs,
        "docstring": func.docstring,
        "related_functions": func.related_functions or [],
        "file_id": func.file_id,
        "file_path": file_obj.file_path if file_obj else None,
        "project_id": project.id if project else None,
        "project_name": project.name if project else None,
        "caller_count": counts["callers"],
        "callee_count": counts["callees"],
    }
