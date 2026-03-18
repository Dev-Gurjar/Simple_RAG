"""Qdrant vector-database service.

Each tenant gets its own collection: ``tenant_{tenant_id}``.
Vectors are 1024-dim (Cohere embed-english-v3.0).
"""

from __future__ import annotations

import uuid
from functools import lru_cache
from typing import Any, cast

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    PointStruct,
    VectorParams,
    Filter,
    FieldCondition,
    MatchValue,
)

from app.config import get_settings


@lru_cache()
def _client() -> QdrantClient:
    s = get_settings()
    return QdrantClient(url=s.QDRANT_URL, api_key=s.QDRANT_API_KEY)


def _collection_name(tenant_id: str) -> str:
    s = get_settings()
    return f"{s.QDRANT_COLLECTION_PREFIX}_{tenant_id}"


# ── Collection management ────────────────────────────────────────────────────

def ensure_collection(tenant_id: str) -> None:
    """Create the tenant collection if it doesn't exist."""
    name = _collection_name(tenant_id)
    collections = [c.name for c in _client().get_collections().collections]
    if name not in collections:
        _client().create_collection(
            collection_name=name,
            vectors_config=VectorParams(
                size=get_settings().EMBEDDING_DIMS,
                distance=Distance.COSINE,
            ),
        )


# ── Upsert ────────────────────────────────────────────────────────────────────

def upsert_chunks(
    tenant_id: str,
    document_id: str,
    filename: str,
    chunks: list[str],
    vectors: list[list[float]],
    chunk_metadata: list[dict[str, Any]] | None = None,
) -> int:
    """Store text chunks + vectors. Returns count of points upserted."""
    ensure_collection(tenant_id)

    metadata_list = chunk_metadata or [{} for _ in chunks]
    points = [
        PointStruct(
            id=str(uuid.uuid4()),
            vector=vec,
            payload=(
                {
                    "document_id": document_id,
                    "filename": filename,
                    "text": chunk,
                    "chunk_index": idx,
                }
                | {
                    key: value
                    for key, value in metadata_list[idx].items()
                    if value is not None and value != ""
                }
            ),
        )
        for idx, (chunk, vec) in enumerate(zip(chunks, vectors))
    ]
    _client().upsert(collection_name=_collection_name(tenant_id), points=points)
    return len(points)


# ── Search ────────────────────────────────────────────────────────────────────

def search(
    tenant_id: str,
    query_vector: list[float],
    top_k: int = 5,
    document_id: str | None = None,
) -> list[dict]:
    """Search the tenant's collection. Returns list of payloads + scores."""
    ensure_collection(tenant_id)
    query_filter = None
    if document_id:
        query_filter = Filter(
            must=[FieldCondition(key="document_id", match=MatchValue(value=document_id))]
        )

    client = cast(Any, _client())
    if hasattr(client, "search"):
        hits = client.search(
            collection_name=_collection_name(tenant_id),
            query_vector=query_vector,
            limit=top_k,
            query_filter=query_filter,
        )
    else:
        result = client.query_points(
            collection_name=_collection_name(tenant_id),
            query=query_vector,
            limit=top_k,
            query_filter=query_filter,
        )
        hits = getattr(result, "points", [])

    return [
        {**(hit.payload or {}), "score": float(getattr(hit, "score", 0.0))}
        for hit in hits
    ]


# ── Delete ────────────────────────────────────────────────────────────────────

def delete_document_vectors(tenant_id: str, document_id: str) -> None:
    """Remove all vectors belonging to a specific document."""
    _client().delete(
        collection_name=_collection_name(tenant_id),
        points_selector=Filter(
            must=[FieldCondition(key="document_id", match=MatchValue(value=document_id))]
        ),
    )
