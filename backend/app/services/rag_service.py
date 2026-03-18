"""RAG pipeline — ties together embedding, Qdrant search, and LLM generation.

Also includes the text-chunking logic used during document ingestion.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from fastapi import UploadFile

from app.config import get_settings
from app.services import (
    docling_client,
    embedding_service,
    qdrant_service,
    llm_service,
)
from app.db.supabase import (
    insert_document,
    update_document,
    create_conversation,
    add_message,
    get_messages,
)


IMAGE_MD_RE = re.compile(r"!\[(?P<alt>[^\]]*)\]\((?P<url>[^)\s]+)(?:\s+\"[^\"]*\")?\)")


def _chunk_image_metadata(chunk: str) -> dict[str, str]:
    """Extract the first markdown image reference from a chunk, if present."""
    match = IMAGE_MD_RE.search(chunk)
    if not match:
        return {}

    url = (match.group("url") or "").strip()
    if not url:
        return {}

    alt = (match.group("alt") or "").strip()
    return {
        "image_url": url,
        "image_caption": alt,
    }


# ─── Text Chunking ───────────────────────────────────────────────────────────

def chunk_text(text: str, chunk_size: int | None = None, overlap: int | None = None) -> list[str]:
    """Split *text* into overlapping chunks by token-ish word count."""
    settings = get_settings()
    chunk_size = chunk_size or settings.CHUNK_SIZE
    overlap = overlap or settings.CHUNK_OVERLAP

    # Normalise whitespace
    text = re.sub(r"\s+", " ", text).strip()
    words = text.split()

    if not words:
        return []

    chunks: list[str] = []
    start = 0
    while start < len(words):
        end = start + chunk_size
        chunks.append(" ".join(words[start:end]))
        start += chunk_size - overlap

    return chunks


# ─── Document Ingestion Pipeline ─────────────────────────────────────────────

async def ingest_document(
    tenant_id: str,
    user_id: str,
    file: UploadFile,
) -> dict:
    """Full pipeline: parse → chunk → embed → store.

    Returns the document DB row (dict).
    """
    # 1. Create DB row (status=pending)
    doc = insert_document(tenant_id, file.filename or "untitled.pdf", uploaded_by=user_id)
    doc_id = doc["id"]

    try:
        # 2. Update status → processing
        update_document(doc_id, {"status": "processing"})

        # 3. Parse via Docling
        markdown = await docling_client.parse_document(file)

        # 4. Chunk
        chunks = chunk_text(markdown)
        if not chunks:
            update_document(doc_id, {"status": "failed", "metadata": {"error": "No text extracted"}})
            return doc

        chunk_metadata = [_chunk_image_metadata(chunk) for chunk in chunks]
        image_count = sum(1 for item in chunk_metadata if item.get("image_url"))

        # 5. Embed
        vectors = embedding_service.embed_texts(chunks)

        # 6. Store in Qdrant
        count = qdrant_service.upsert_chunks(
            tenant_id=tenant_id,
            document_id=doc_id,
            filename=file.filename or "untitled.pdf",
            chunks=chunks,
            vectors=vectors,
            chunk_metadata=chunk_metadata,
        )

        # 7. Mark ready
        doc = update_document(
            doc_id,
            {
                "status": "ready",
                "chunk_count": count,
                "metadata": {"image_refs": image_count},
            },
        )
        return doc

    except Exception as exc:
        update_document(doc_id, {"status": "failed", "metadata": {"error": str(exc)}})
        raise


# ─── Query Pipeline ──────────────────────────────────────────────────────────

async def query(
    tenant_id: str,
    user_id: str,
    query_text: str,
    conversation_id: str | None = None,
    top_k: int = 5,
) -> dict:
    """Full RAG query: embed query → search → generate → persist.

    Returns ``{"answer": ..., "sources": [...], "conversation_id": ...}``.
    """
    # 1. Embed query
    query_vector = embedding_service.embed_query(query_text)

    # 2. Retrieve
    hits = qdrant_service.search(tenant_id, query_vector, top_k=top_k)

    # 3. Conversation history (if continuing)
    history: list[dict] = []
    if conversation_id:
        raw_msgs = get_messages(conversation_id)
        history = [{"role": m["role"], "content": m["content"]} for m in raw_msgs]

    # 4. Generate
    answer = llm_service.generate_answer(query_text, hits, history or None)

    # 5. Persist conversation + messages
    if not conversation_id:
        conv = create_conversation(tenant_id, user_id, title=query_text[:80])
        conversation_id = conv["id"]

    if not conversation_id:
        raise ValueError("Failed to create conversation")

    sources_payload = [
        {
            "document_id": h.get("document_id", ""),
            "filename": h.get("filename", ""),
            "text": h.get("text", ""),
            "score": h.get("score", 0.0),
            "image_url": h.get("image_url"),
            "image_caption": h.get("image_caption"),
        }
        for h in hits
    ]

    add_message(conversation_id, "user", query_text, tenant_id=tenant_id, user_id=user_id)
    add_message(conversation_id, "assistant", answer, tenant_id=tenant_id, user_id=user_id, sources=sources_payload)

    return {
        "answer": answer,
        "sources": sources_payload,
        "conversation_id": conversation_id,
    }
