"""
Vector embedding service using pgvector + OpenAI-compatible embedding API.

Generates embeddings for code functions, stores them in pgvector,
and provides semantic + hybrid search over the function corpus.
"""

from __future__ import annotations

from openai import OpenAI
from sqlalchemy import text
from sqlalchemy.orm import Session

from .config import config
from .search_service import _split_query

# Max chars of code_snippet to include in embedding text
MAX_CODE_CHARS = 2000
# Max chars of docstring to include
MAX_DOCSTRING_CHARS = 500

# ── OpenAI-compatible embedding client ──

_embedding_client: OpenAI | None = None


def _get_client() -> OpenAI | None:
    """Get or create the embedding API client. Returns None if disabled."""
    global _embedding_client
    if not config.EMBEDDING_ENABLED:
        return None
    if _embedding_client is None:
        _embedding_client = OpenAI(
            api_key=config.EMBEDDING_API_KEY,
            base_url=config.EMBEDDING_BASE_URL,
            max_retries=1,
        )
    return _embedding_client


def _build_embedding_text(
    name: str,
    signature: str | None = None,
    docstring: str | None = None,
    code_snippet: str | None = None,
    ai_purpose: str | None = None,
) -> str:
    """
    Build a compact text representation of a function for embedding.
    Prioritizes name, signature, purpose, then code.
    """
    parts = [name]
    if signature:
        parts.append(signature)
    if ai_purpose:
        parts.append(ai_purpose)
    if docstring:
        parts.append(docstring[:MAX_DOCSTRING_CHARS])
    if code_snippet:
        parts.append(code_snippet[:MAX_CODE_CHARS])
    return "\n".join(p for p in parts if p)


# ── Public API ──


def is_enabled() -> bool:
    """Check if embedding generation is configured and available."""
    return config.EMBEDDING_ENABLED


def generate_embedding(text: str) -> list[float] | None:
    """
    Generate an embedding vector for arbitrary text.
    Returns None if embedding is disabled or the API call fails.
    """
    client = _get_client()
    if not client:
        return None
    try:
        response = client.embeddings.create(
            model=config.EMBEDDING_MODEL,
            input=text,
        )
        return response.data[0].embedding
    except Exception as e:
        print(f"[Embedding] Failed to generate embedding: {e}")
        return None


def generate_embeddings_batch(texts: list[str]) -> list[list[float] | None]:
    """
    Generate embeddings for multiple texts in a single API call.
    Returns list in the same order as input. Failed items are None.
    """
    if not texts:
        return []

    client = _get_client()
    if not client:
        return [None] * len(texts)

    try:
        response = client.embeddings.create(
            model=config.EMBEDDING_MODEL,
            input=texts,
        )
        # Sort by index to preserve input order
        sorted_data = sorted(response.data, key=lambda x: x.index)
        return [d.embedding for d in sorted_data]
    except Exception as e:
        print(f"[Embedding] Batch embedding failed ({len(texts)} items): {e}")
        return [None] * len(texts)


def generate_function_embedding(func_data: dict) -> list[float] | None:
    """
    Generate embedding for a function's text representation.
    func_data should have keys: name, signature, docstring, code_snippet, ai_purpose.
    """
    text_repr = _build_embedding_text(
        name=func_data.get("name", ""),
        signature=func_data.get("signature"),
        docstring=func_data.get("docstring"),
        code_snippet=func_data.get("code_snippet"),
        ai_purpose=func_data.get("ai_purpose"),
    )
    if not text_repr.strip():
        return None
    return generate_embedding(text_repr)


def generate_function_embeddings_batch(
    funcs: list[dict],
) -> list[list[float] | None]:
    """
    Generate embeddings for multiple functions in a single API call.
    Each func_data should have keys: name, signature, docstring, code_snippet, ai_purpose.
    """
    texts = []
    for func in funcs:
        text_repr = _build_embedding_text(
            name=func.get("name", ""),
            signature=func.get("signature"),
            docstring=func.get("docstring"),
            code_snippet=func.get("code_snippet"),
            ai_purpose=func.get("ai_purpose"),
        )
        texts.append(text_repr)

    if not any(t.strip() for t in texts):
        return [None] * len(funcs)

    return generate_embeddings_batch(texts)


# ── Search ──


def semantic_search(
    db: Session,
    query: str,
    language: str | None = None,
    project_id: int | None = None,
    limit: int = 20,
) -> list[dict]:
    """
    Semantic search over functions using embedding similarity (cosine distance).

    Uses the <=> operator (cosine distance). Lower distance = more similar.
    Results are ordered by similarity (closest first) and include a similarity score.
    Falls back to empty results if embedding is disabled or the query embedding fails.
    """
    limit = min(limit, config.SEARCH_MAX_LIMIT)

    query_embedding = generate_embedding(query)
    if query_embedding is None:
        return []

    # Build embedding vector string for the SQL query
    emb_str = "[" + ",".join(str(v) for v in query_embedding) + "]"

    conditions = ["f.embedding IS NOT NULL"]
    params: dict = {
        "query_emb": emb_str,
        "limit": limit,
    }

    if language:
        conditions.append("f.language = :language")
        params["language"] = language
    if project_id is not None:
        conditions.append("p.id = :project_id")
        params["project_id"] = project_id

    where_clause = " AND ".join(conditions)

    sql = text(f"""
        SELECT
            f.id,
            f.name,
            f.signature,
            f.language,
            f.start_line,
            f.end_line,
            f.code_snippet,
            f.docstring,
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
            f.file_id,
            fl.file_path,
            p.id AS project_id,
            p.name AS project_name,
            1 - (f.embedding <=> :query_emb::vector) AS similarity
        FROM functions f
        JOIN files fl ON fl.id = f.file_id
        JOIN projects p ON p.id = fl.project_id
        WHERE {where_clause}
        ORDER BY f.embedding <=> :query_emb::vector
        LIMIT :limit
    """)

    rows = db.execute(sql, params).fetchall()

    return [
        {
            "id": row.id,
            "name": row.name,
            "signature": row.signature,
            "language": row.language,
            "start_line": row.start_line,
            "end_line": row.end_line,
            "code_snippet": row.code_snippet,
            "docstring": row.docstring,
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
            "file_id": row.file_id,
            "file_path": row.file_path,
            "project_id": row.project_id,
            "project_name": row.project_name,
            "score": round(float(row.similarity), 4),
        }
        for row in rows
    ]


def hybrid_search(
    db: Session,
    query: str,
    language: str | None = None,
    project_id: int | None = None,
    limit: int = 20,
    semantic_weight: float = 0.5,
) -> list[dict]:
    """
    Hybrid search combining keyword (full-text) and semantic (embedding) scores.

    Uses weighted reciprocal rank fusion (RRF) to combine results.
    - semantic_weight: 0 = pure keyword, 1 = pure semantic (default 0.5)

    Falls back to keyword-only if embedding generation fails.
    Falls back to semantic-only if no keyword results.
    """
    from .search_service import search_code

    limit = min(limit, config.SEARCH_MAX_LIMIT)

    # Get keyword search results
    keyword_results = search_code(
        db, query, language=language, project_id=project_id, limit=limit * 3
    )

    # Get semantic search results
    semantic_results = semantic_search(
        db, query, language=language, project_id=project_id, limit=limit * 3
    )

    if not keyword_results:
        return semantic_results[:limit]
    if not semantic_results:
        return keyword_results[:limit]

    # Reciprocal rank fusion
    scores: dict[int, dict] = {}

    for rank, r in enumerate(keyword_results):
        fid = r["id"]
        scores[fid] = {
            **r,
            "_combined_score": (1 - semantic_weight) * (1.0 / (rank + 60)),
            "_keyword_rank": rank,
            "_semantic_rank": None,
        }

    for rank, r in enumerate(semantic_results):
        fid = r["id"]
        sem_score = semantic_weight * (1.0 / (rank + 60))
        if fid in scores:
            scores[fid]["_combined_score"] += sem_score
            scores[fid]["_semantic_rank"] = rank
        else:
            scores[fid] = {
                **r,
                "_combined_score": sem_score,
                "_keyword_rank": None,
                "_semantic_rank": rank,
            }

    # Sort by combined score descending
    ranked = sorted(scores.values(), key=lambda x: x["_combined_score"], reverse=True)

    for r in ranked:
        del r["_combined_score"]
        r.pop("_keyword_rank", None)
        r.pop("_semantic_rank", None)

    return ranked[:limit]


# ── Index management ──


def get_ivfflat_index_sql() -> str:
    """Create an IVFFlat index for fast approximate nearest neighbor search."""
    return """
    CREATE INDEX IF NOT EXISTS ix_functions_embedding
    ON functions
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);
    """


def get_extension_sql() -> str:
    """Enable the pgvector extension."""
    return "CREATE EXTENSION IF NOT EXISTS vector;"
