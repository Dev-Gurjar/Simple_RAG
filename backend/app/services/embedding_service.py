"""Cohere embedding service.

Uses the embed-english-v3.0 model (1024 dimensions) via the Cohere
Python SDK.
"""

from __future__ import annotations

import cohere
from typing import Any, cast

from app.config import get_settings


def _client() -> cohere.Client:
    return cohere.Client(get_settings().COHERE_API_KEY)


def embed_texts(
    texts: list[str],
    *,
    input_type: str = "search_document",
) -> list[list[float]]:
    """Return embedding vectors for a list of texts.

    ``input_type`` should be ``"search_document"`` when indexing and
    ``"search_query"`` when querying.
    """
    settings = get_settings()
    resp = _client().embed(
        texts=texts,
        model=settings.EMBEDDING_MODEL,
        input_type=input_type,
        truncate="END",
    )
    embeddings: Any = resp.embeddings
    if isinstance(embeddings, list):
        return cast(list[list[float]], embeddings)
    float_embeddings = getattr(embeddings, "float", None)
    if isinstance(float_embeddings, list):
        return cast(list[list[float]], float_embeddings)
    raise ValueError("Unexpected Cohere embeddings response shape")


def embed_query(text: str) -> list[float]:
    """Embed a single query string."""
    return embed_texts([text], input_type="search_query")[0]
