"""Document upload & management endpoints."""

from __future__ import annotations

import httpx

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status, BackgroundTasks

from app.api.auth import get_current_user
from app.db.supabase import get_documents, get_document, delete_document_row
from app.models.schemas import DocumentListResponse, DocumentOut
from app.services.qdrant_service import delete_document_vectors
from app.services.rag_service import ingest_document

router = APIRouter()

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB
ALLOWED_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


@router.post("/upload", response_model=DocumentOut, status_code=202)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
):
    """Upload a PDF/DOCX → parse via Docling → chunk → embed → store."""
    tenant_id = user["tenant_id"]

    # Basic validation
    if file.content_type and file.content_type not in ALLOWED_TYPES:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Only PDF and DOCX files are accepted")

    # Enforce file size limit
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"File too large. Maximum size is {MAX_FILE_SIZE // (1024 * 1024)} MB",
        )
    await file.seek(0)  # Reset so downstream can re-read

    # Instead of blocking, we could do background processing.
    # For now, run inline so the user sees immediate status.
    try:
        doc = await ingest_document(tenant_id, user["sub"], file)
        return doc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"Docling request failed: {exc.response.status_code} {exc.response.reason_phrase}",
        )
    except httpx.HTTPError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Docling connection failed: {exc}")
    except Exception as exc:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"Document ingestion failed: {exc}")


@router.get("", response_model=DocumentListResponse)
async def list_documents(user: dict = Depends(get_current_user)):
    """List all documents for the current tenant."""
    tenant_id = user["tenant_id"]
    docs = get_documents(tenant_id)
    return {"documents": docs, "total": len(docs)}


@router.delete("/{doc_id}", status_code=204)
async def delete_document(doc_id: str, user: dict = Depends(get_current_user)):
    """Delete a document and its vectors."""
    tenant_id = user["tenant_id"]
    doc = get_document(doc_id, tenant_id)
    if not doc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")

    # Try vector cleanup first; always soft-delete DB row so UI is consistent
    # even if the vector backend is temporarily unavailable.
    try:
        delete_document_vectors(tenant_id, doc_id)
    except Exception:
        pass

    delete_document_row(doc_id)
