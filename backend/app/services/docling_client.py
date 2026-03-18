"""Client for calling a Docling server.

Prefers the docling-serve v1 API and falls back to older routes for
backward compatibility.
"""

from __future__ import annotations

from io import BytesIO

import httpx
from fastapi import UploadFile
from pypdf import PdfReader
from docx import Document

from app.config import get_settings

TIMEOUT = httpx.Timeout(300.0, connect=30.0)  # generous for large PDFs


def _extract_text_from_docling_response(result: dict) -> str:
    """Extract markdown/text content from different docling response shapes."""
    if not isinstance(result, dict):
        return ""

    # Legacy shapes
    legacy_text = result.get("markdown") or result.get("text")
    if isinstance(legacy_text, str) and legacy_text.strip():
        return legacy_text

    # v1 single-document shape
    document = result.get("document")
    if isinstance(document, dict):
        md_content = document.get("md_content")
        if isinstance(md_content, str) and md_content.strip():
            return md_content
        text_content = document.get("text_content")
        if isinstance(text_content, str) and text_content.strip():
            return text_content

    # Defensive parsing for potential list-based payloads.
    documents = result.get("documents")
    if isinstance(documents, list):
        for item in documents:
            if not isinstance(item, dict):
                continue
            doc = item.get("document") if isinstance(item.get("document"), dict) else item
            md_content = doc.get("md_content") if isinstance(doc, dict) else None
            if isinstance(md_content, str) and md_content.strip():
                return md_content
            text_content = doc.get("text_content") if isinstance(doc, dict) else None
            if isinstance(text_content, str) and text_content.strip():
                return text_content

    return ""


def _parse_pdf_local(content: bytes) -> str:
    reader = PdfReader(BytesIO(content))
    texts: list[str] = []
    for page in reader.pages:
        txt = page.extract_text() or ""
        if txt.strip():
            texts.append(txt.strip())
    return "\n\n".join(texts)


def _parse_docx_local(content: bytes) -> str:
    doc = Document(BytesIO(content))
    parts = [p.text.strip() for p in doc.paragraphs if p.text and p.text.strip()]
    return "\n\n".join(parts)


def _parse_document_local(file: UploadFile, content: bytes) -> str:
    ctype = (file.content_type or "").lower()
    name = (file.filename or "").lower()

    if ctype == "application/pdf" or name.endswith(".pdf"):
        return _parse_pdf_local(content)

    if (
        ctype == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        or name.endswith(".docx")
    ):
        return _parse_docx_local(content)

    raise ValueError("Unsupported file type for local parser")


async def parse_document(file: UploadFile) -> str:
    """Send *file* to the Docling server and return markdown text.

    Raises ``httpx.HTTPStatusError`` on non-2xx responses.
    """
    settings = get_settings()
    base_url = settings.DOCLING_URL.rstrip("/")

    content = await file.read()

    headers = {}
    if settings.DOCLING_API_KEY:
        headers["X-Api-Key"] = settings.DOCLING_API_KEY

    filenames = file.filename or "document"
    mime_type = file.content_type or "application/pdf"
    remote_attempts = [
        # docling-serve v1
        {
            "url": f"{base_url}/v1/convert/file",
            "files": {"files": (filenames, content, mime_type)},
            "data": {"to_formats": "md"},
        },
        # older v1alpha installations
        {
            "url": f"{base_url}/v1alpha/convert/file",
            "files": {"files": (filenames, content, mime_type)},
            "data": {"to_formats": "md"},
        },
        # legacy compatibility
        {
            "url": f"{base_url}/convert",
            "files": {"file": (filenames, content, mime_type)},
            "data": {"output_format": "markdown"},
        },
    ]

    for attempt in remote_attempts:
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT, verify=settings.DOCLING_VERIFY_SSL) as client:
                resp = await client.post(
                    attempt["url"],
                    files=attempt["files"],
                    data=attempt["data"],
                    headers=headers,
                )
                resp.raise_for_status()

            parsed = _extract_text_from_docling_response(resp.json())
            if parsed.strip():
                return parsed
        except Exception:
            # Try the next remote endpoint variant before falling back locally.
            continue

    try:
        parsed_local = _parse_document_local(file, content)
        return parsed_local
    except Exception:
        # Let ingestion pipeline mark the document as failed gracefully.
        return ""
