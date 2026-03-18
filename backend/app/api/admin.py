"""Admin / tenant-management endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.auth import get_current_user
from app.db.supabase import get_tenant, get_tenant_stats
from app.models.schemas import TenantOut, UsageStats

router = APIRouter()


def _require_admin(user: dict) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin access required")
    return user


@router.get("/tenant", response_model=TenantOut)
async def get_tenant_info(user: dict = Depends(get_current_user)):
    """Get current tenant details."""
    admin = _require_admin(user)
    tenant = get_tenant(admin["tenant_id"])
    if not tenant:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tenant not found")
    return tenant


@router.get("/stats", response_model=UsageStats)
async def get_stats(user: dict = Depends(get_current_user)):
    """Get usage statistics for the current tenant."""
    admin = _require_admin(user)
    stats = get_tenant_stats(admin["tenant_id"])
    return UsageStats(
        total_documents=stats.get("total_documents", 0),
        total_chunks=stats.get("total_chunks", 0),
        total_conversations=stats.get("total_conversations", 0),
        total_messages=stats.get("total_messages", 0),
        queries_today=0,   # TODO: track daily
    )
