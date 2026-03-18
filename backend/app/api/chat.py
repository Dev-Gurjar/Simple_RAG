"""Chat / RAG query endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.auth import get_current_user
from app.db.supabase import get_conversations, get_conversation, get_messages, get_message_count
from app.models.schemas import (
    ChatRequest,
    ChatResponse,
    ConversationDetail,
    ConversationOut,
    MessageOut,
)
from app.services.rag_service import query as rag_query

router = APIRouter()


@router.post("", response_model=ChatResponse)
async def chat(body: ChatRequest, user: dict = Depends(get_current_user)):
    """Ask a question — runs the full RAG pipeline."""
    tenant_id = user["tenant_id"]
    user_id = user["sub"]

    result = await rag_query(
        tenant_id=tenant_id,
        user_id=user_id,
        query_text=body.query,
        conversation_id=body.conversation_id,
    )
    return result


@router.get("/conversations", response_model=list[ConversationOut])
async def list_conversations(user: dict = Depends(get_current_user)):
    """List conversations for the current user."""
    convs = get_conversations(user["tenant_id"], user["sub"])
    # Enrich with message counts
    for c in convs:
        c["message_count"] = get_message_count(c["id"])
    return convs


@router.get("/conversations/{conv_id}", response_model=ConversationDetail)
async def get_conversation_detail(conv_id: str, user: dict = Depends(get_current_user)):
    """Get a conversation with all its messages."""
    conv = get_conversation(conv_id, user["tenant_id"])
    if not conv:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")

    msgs = get_messages(conv_id)
    return {"conversation": conv, "messages": msgs}
