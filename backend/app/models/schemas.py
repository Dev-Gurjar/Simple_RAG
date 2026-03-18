"""Pydantic schemas for request / response validation."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, EmailStr, Field


# ─── Enums ────────────────────────────────────────────────────────────────────

class UserRole(str, Enum):
    ADMIN = "admin"
    MEMBER = "member"


class DocumentStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


# ─── Auth ─────────────────────────────────────────────────────────────────────

class TenantCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    slug: str = Field(..., min_length=2, max_length=50, pattern=r"^[a-z0-9-]+$")


class UserRegister(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8)
    full_name: str = Field(..., min_length=1, max_length=100)
    tenant: TenantCreate


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: str
    email: str
    full_name: str
    role: UserRole
    tenant_id: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


# ─── Documents ────────────────────────────────────────────────────────────────

class DocumentOut(BaseModel):
    id: str
    tenant_id: str
    filename: str
    status: DocumentStatus
    chunk_count: int = 0
    metadata: dict[str, Any] = {}
    created_at: datetime


class DocumentListResponse(BaseModel):
    documents: list[DocumentOut]
    total: int


# ─── Chat ─────────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=4000)
    conversation_id: str | None = None  # None → new conversation


class SourceChunk(BaseModel):
    document_id: str
    filename: str
    text: str
    score: float
    image_url: str | None = None
    image_caption: str | None = None


class ChatResponse(BaseModel):
    answer: str
    sources: list[SourceChunk]
    conversation_id: str


class MessageOut(BaseModel):
    id: str
    role: MessageRole
    content: str
    sources: list[SourceChunk] = []
    created_at: datetime


class ConversationOut(BaseModel):
    id: str
    title: str
    created_at: datetime
    message_count: int = 0


class ConversationDetail(BaseModel):
    conversation: ConversationOut
    messages: list[MessageOut]


# ─── Admin ────────────────────────────────────────────────────────────────────

class TenantOut(BaseModel):
    id: str
    name: str
    slug: str
    settings: dict[str, Any] = {}
    created_at: datetime


class UsageStats(BaseModel):
    total_documents: int
    total_chunks: int
    total_conversations: int
    total_messages: int
    queries_today: int
