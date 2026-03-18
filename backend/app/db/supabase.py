"""Supabase client wrapper.

Provides a thin helper around the supabase-py client so every module
gets the same authenticated connection.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, cast
import json
import time
import uuid

from supabase import create_client, Client
from postgrest.exceptions import APIError

from app.config import get_settings

JSONDict = dict[str, Any]


def _as_dict(value: Any) -> JSONDict:
    return cast(JSONDict, value) if isinstance(value, dict) else {}


def _as_dict_or_none(value: Any) -> JSONDict | None:
    return cast(JSONDict, value) if isinstance(value, dict) else None


def _as_dict_list(value: Any) -> list[JSONDict]:
    if not isinstance(value, list):
        return []
    return [cast(JSONDict, row) for row in value if isinstance(row, dict)]


def _parse_json_text(value: Any) -> JSONDict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _execute_with_retry(request: Any, retries: int = 2) -> Any:
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            return request.execute()
        except Exception as exc:  # pragma: no cover - network dependent
            last_exc = exc
            transient = "RemoteProtocolError" in type(exc).__name__ or "ConnectionTerminated" in str(exc)
            if transient and attempt < retries:
                time.sleep(0.25 * (attempt + 1))
                continue
            raise
    if last_exc:
        raise last_exc
    raise RuntimeError("Query execution failed")


@lru_cache()
def get_supabase() -> Client:
    """Return a cached Supabase client (service-role)."""
    s = get_settings()
    return create_client(s.SUPABASE_URL, s.SUPABASE_KEY)


# ─── Tenant helpers ──────────────────────────────────────────────────────────

def create_tenant(name: str, slug: str, email: str) -> JSONDict:
    try:
        rows = _as_dict_list(
            _execute_with_retry(
                get_supabase()
                .table("tenants")
                .insert({"name": name, "slug": slug, "email": email})
            ).data
        )
        return rows[0] if rows else {}
    except APIError as exc:
        message = str(exc)
        if "23505" in message or "duplicate key" in message.lower():
            existing = _as_dict_list(
                _execute_with_retry(
                    get_supabase().table("tenants").select("*").eq("slug", slug).limit(1)
                ).data
            )
            if existing:
                return existing[0]
        raise


def get_tenant(tenant_id: str) -> JSONDict | None:
    resp = _execute_with_retry(
        get_supabase()
        .table("tenants")
        .select("*")
        .eq("id", tenant_id)
        .single()
    )
    row = _as_dict_or_none(resp.data)
    if not row:
        return None
    return {
        **row,
        "settings": _parse_json_text(row.get("settings")),
    }


# ─── User helpers ────────────────────────────────────────────────────────────

def create_user(
    tenant_id: str,
    email: str,
    password_hash: str,
    full_name: str,
    role: str = "admin",
) -> JSONDict:
    try:
        user_rows = _as_dict_list(
            _execute_with_retry(
                get_supabase()
                .table("users")
                .insert(
                    {
                        "email": email,
                        "hashed_password": password_hash,
                        "full_name": full_name,
                    }
                )
            ).data
        )
    except APIError as exc:
        message = str(exc)
        if "23505" in message or "duplicate key" in message.lower():
            user_rows = _as_dict_list(
                _execute_with_retry(
                    get_supabase().table("users").select("*").eq("email", email).limit(1)
                ).data
            )
        else:
            raise
    if not user_rows:
        return {}

    user = user_rows[0]
    links = _as_dict_list(
        _execute_with_retry(
            get_supabase()
            .table("user_tenants")
            .select("id")
            .eq("user_id", user["id"])
            .eq("tenant_id", tenant_id)
            .limit(1)
        )
        .data
    )
    if not links:
        try:
            _execute_with_retry(
                get_supabase().table("user_tenants").insert(
                    {
                        "user_id": user["id"],
                        "tenant_id": tenant_id,
                        "role": role,
                        "is_active": True,
                    }
                )
            )
        except APIError as exc:
            message = str(exc)
            if "23505" not in message and "duplicate key" not in message.lower():
                raise

    return {
        **user,
        "password_hash": user.get("hashed_password", ""),
        "tenant_id": tenant_id,
        "role": role,
    }


def get_user_by_email(email: str) -> JSONDict | None:
    user_resp = (
        _execute_with_retry(
            get_supabase()
        .table("users")
        .select("*")
        .eq("email", email)
        .maybe_single()
        )
    )
    user = _as_dict_or_none(getattr(user_resp, "data", None))
    if not user:
        return None

    links = _as_dict_list(
        _execute_with_retry(
            get_supabase()
        .table("user_tenants")
        .select("tenant_id, role")
        .eq("user_id", user["id"])
        .eq("is_active", True)
        .order("joined_at", desc=True)
        )
        .data
    )
    link = links[0] if links else {}

    return {
        **user,
        "password_hash": user.get("hashed_password", ""),
        "tenant_id": link.get("tenant_id", ""),
        "role": link.get("role", "member"),
    }


# ─── Document helpers ────────────────────────────────────────────────────────

def insert_document(
    tenant_id: str,
    filename: str,
    uploaded_by: str,
    metadata: JSONDict | None = None,
) -> JSONDict:
    ext = (filename.split(".")[-1].lower() if "." in filename else "")
    rows = _as_dict_list(
        _execute_with_retry(
            get_supabase()
            .table("documents")
            .insert(
                {
                    "tenant_id": tenant_id,
                    "title": filename,
                    "filename": filename,
                    "file_type": ext or "pdf",
                    "doc_type": "general",
                    "source": "upload",
                    "uploaded_by": uploaded_by,
                    "status": "pending",
                    "total_chunks": 0,
                    "processed_chunks": 0,
                    "metadata_json": json.dumps(metadata or {}),
                }
            )
        )
        .data
    )
    if not rows:
        return {}
    row = rows[0]
    return {
        **row,
        "chunk_count": int(row.get("total_chunks", 0) or 0),
        "metadata": _parse_json_text(row.get("metadata_json")),
    }


def update_document(doc_id: str, updates: JSONDict) -> JSONDict:
    mapped_updates: JSONDict = dict(updates)
    if "chunk_count" in mapped_updates:
        mapped_updates["total_chunks"] = mapped_updates.pop("chunk_count")
    if "metadata" in mapped_updates:
        mapped_updates["metadata_json"] = json.dumps(mapped_updates.pop("metadata"))

    rows = _as_dict_list(
        _execute_with_retry(
            get_supabase()
            .table("documents")
            .update(mapped_updates)
            .eq("id", doc_id)
        ).data
    )
    if not rows:
        return {}
    row = rows[0]
    return {
        **row,
        "chunk_count": int(row.get("total_chunks", 0) or 0),
        "metadata": _parse_json_text(row.get("metadata_json")),
    }


def get_documents(tenant_id: str) -> list[JSONDict]:
    rows = _execute_with_retry(
        get_supabase()
        .table("documents")
        .select("*")
        .eq("tenant_id", tenant_id)
        .order("created_at", desc=True)
    ).data
    return [
        {
            **row,
            "filename": row.get("filename") or row.get("title") or "untitled",
            "chunk_count": int(row.get("total_chunks", 0) or 0),
            "metadata": _parse_json_text(row.get("metadata_json")),
        }
        for row in _as_dict_list(rows)
        if not bool(row.get("is_deleted", False))
    ]


def get_document(doc_id: str, tenant_id: str) -> JSONDict | None:
    resp = _execute_with_retry(
        get_supabase()
        .table("documents")
        .select("*")
        .eq("id", doc_id)
        .eq("tenant_id", tenant_id)
        .maybe_single()
    )
    row = _as_dict_or_none(getattr(resp, "data", None))
    if not row:
        return None
    if bool(row.get("is_deleted", False)):
        return None
    return {
        **row,
        "filename": row.get("filename") or row.get("title") or "untitled",
        "chunk_count": int(row.get("total_chunks", 0) or 0),
        "metadata": _parse_json_text(row.get("metadata_json")),
    }


def delete_document_row(doc_id: str) -> None:
    _execute_with_retry(
        get_supabase().table("documents").update({"is_deleted": True}).eq("id", doc_id)
    )


# ─── Conversation / Message helpers ─────────────────────────────────────────

def create_conversation(tenant_id: str, user_id: str, title: str) -> JSONDict:
    return {
        "id": str(uuid.uuid4()),
        "title": title,
        "tenant_id": tenant_id,
        "user_id": user_id,
    }


def get_conversations(tenant_id: str, user_id: str) -> list[JSONDict]:
    rows = _as_dict_list(
        _execute_with_retry(
            get_supabase()
        .table("query_logs")
        .select("conversation_id, query, created_at")
        .eq("tenant_id", tenant_id)
        .eq("user_id", user_id)
        .not_.is_("conversation_id", "null")
        .order("created_at", desc=True)
        )
        .data
    )
    by_conv: dict[str, JSONDict] = {}
    for row in rows:
        conv_id = str(row.get("conversation_id") or "")
        if not conv_id:
            continue
        if conv_id not in by_conv:
            by_conv[conv_id] = {
                "id": conv_id,
                "title": str(row.get("query") or "Conversation"),
                "created_at": row.get("created_at"),
            }
    return list(by_conv.values())


def get_conversation(conv_id: str, tenant_id: str) -> JSONDict | None:
    rows = _as_dict_list(
        _execute_with_retry(
            get_supabase()
        .table("query_logs")
        .select("conversation_id, query, created_at")
        .eq("conversation_id", conv_id)
        .eq("tenant_id", tenant_id)
        .order("created_at", desc=False)
        )
        .data
    )
    if not rows:
        return None
    first = rows[0]
    return {
        "id": conv_id,
        "title": str(first.get("query") or "Conversation"),
        "created_at": first.get("created_at"),
    }


def add_message(
    conversation_id: str,
    role: str,
    content: str,
    tenant_id: str | None = None,
    user_id: str | None = None,
    sources: list | None = None,
) -> JSONDict:
    if role == "user":
        if not tenant_id:
            raise ValueError("tenant_id is required for user messages")
        rows = _as_dict_list(
            _execute_with_retry(
                get_supabase()
            .table("query_logs")
            .insert(
                {
                        "tenant_id": tenant_id,
                        "user_id": user_id,
                    "conversation_id": conversation_id,
                    "query": content,
                    "response": None,
                    "retrieved_chunks": 0,
                }
            )
            )
            .data
        )
        return rows[0] if rows else {}

    if role == "assistant":
        log_rows = _as_dict_list(
            _execute_with_retry(
                get_supabase()
            .table("query_logs")
            .select("id")
            .eq("conversation_id", conversation_id)
            .is_("response", "null")
            .order("created_at", desc=True)
            .limit(1)
            )
            .data
        )
        if not log_rows:
            return {}
        log_id = log_rows[0]["id"]
        update_payload: JSONDict = {
            "response": content,
            "retrieved_chunks": len(sources or []),
        }
        if sources:
            update_payload["retrieved_docs"] = json.dumps(sources)
        rows = _as_dict_list(
            _execute_with_retry(
                get_supabase()
            .table("query_logs")
            .update(update_payload)
            .eq("id", log_id)
            )
            .data
        )
        return rows[0] if rows else {}

    return {}


def get_messages(conversation_id: str) -> list[JSONDict]:
    rows = _as_dict_list(
        _execute_with_retry(
            get_supabase()
        .table("query_logs")
        .select("id, query, response, retrieved_docs, created_at")
        .eq("conversation_id", conversation_id)
        .order("created_at", desc=False)
        )
        .data
    )
    messages: list[JSONDict] = []
    for row in rows:
        created_at = row.get("created_at")
        messages.append(
            {
                "id": f"{row.get('id')}-u",
                "role": "user",
                "content": row.get("query") or "",
                "sources": [],
                "created_at": created_at,
            }
        )
        if row.get("response"):
            sources = _parse_json_text(row.get("retrieved_docs"))
            src_list = sources.get("items") if isinstance(sources.get("items"), list) else []
            if not src_list and isinstance(row.get("retrieved_docs"), str):
                try:
                    parsed = json.loads(row["retrieved_docs"])
                    src_list = parsed if isinstance(parsed, list) else []
                except Exception:
                    src_list = []
            messages.append(
                {
                    "id": f"{row.get('id')}-a",
                    "role": "assistant",
                    "content": row.get("response") or "",
                    "sources": src_list,
                    "created_at": created_at,
                }
            )
    return messages


# ─── Stats ───────────────────────────────────────────────────────────────────

def get_message_count(conversation_id: str) -> int:
    """Return the number of messages in a conversation."""
    rows = _execute_with_retry(
        get_supabase()
        .table("query_logs")
        .select("id")
        .eq("conversation_id", conversation_id)
    ).data
    return len(_as_dict_list(rows)) * 2


def get_tenant_stats(tenant_id: str) -> JSONDict:
    sb = get_supabase()
    docs_rows = _as_dict_list(
        _execute_with_retry(sb.table("documents").select("id").eq("tenant_id", tenant_id)).data
    )
    log_rows = _as_dict_list(
        _execute_with_retry(
            sb.table("query_logs").select("id, conversation_id").eq("tenant_id", tenant_id)
        ).data
    )

    # Aggregate total messages across all tenant conversations
    conv_ids = {
        str(r.get("conversation_id"))
        for r in log_rows
        if r.get("conversation_id")
    }
    total_messages = len(log_rows) * 2

    # Total chunks from documents
    chunk_rows = _as_dict_list(
        _execute_with_retry(
            sb.table("documents").select("total_chunks").eq("tenant_id", tenant_id)
        ).data
    )
    total_chunks = sum(int(r.get("total_chunks", 0) or 0) for r in chunk_rows)

    return {
        "total_documents": len(docs_rows),
        "total_conversations": len(conv_ids),
        "total_messages": total_messages,
        "total_chunks": total_chunks,
    }
