"""Authentication endpoints — register & login with JWT."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from postgrest.exceptions import APIError

from app.config import get_settings
from app.db.supabase import create_tenant, create_user, get_user_by_email
from app.models.schemas import (
    TokenResponse,
    UserLogin,
    UserOut,
    UserRegister,
    UserRole,
)

router = APIRouter()
security = HTTPBearer()


def _raise_db_unavailable(exc: Exception) -> None:
    """Convert upstream DB/network issues into a user-safe API error."""
    raise HTTPException(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        f"Database temporarily unavailable: {exc}",
    )


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def _verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def _create_token(user: dict) -> str:
    settings = get_settings()
    payload = {
        "sub": user["id"],
        "email": user["email"],
        "tenant_id": user["tenant_id"],
        "role": user["role"],
        "exp": datetime.now(timezone.utc) + timedelta(minutes=settings.JWT_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def get_current_user(
    creds: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """Decode JWT and return the payload dict (used as a dependency)."""
    settings = get_settings()
    try:
        payload = jwt.decode(
            creds.credentials,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(body: UserRegister):
    """Create a new tenant + admin user and return a JWT."""
    # Check duplicate email
    existing_user: dict | None = None
    try:
        existing_user = get_user_by_email(body.email)
    except APIError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"Supabase user lookup failed: {exc}",
        )
    except Exception as exc:
        _raise_db_unavailable(exc)

    if existing_user:
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")

    # Create tenant
    tenant: dict = {}
    try:
        tenant = create_tenant(body.tenant.name, body.tenant.slug, body.email)
    except APIError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"Supabase tenant insert failed: {exc}",
        )
    except Exception as exc:
        _raise_db_unavailable(exc)

    # Create admin user
    user: dict = {}
    try:
        user = create_user(
            tenant_id=tenant["id"],
            email=body.email,
            password_hash=_hash_password(body.password),
            full_name=body.full_name,
            role=UserRole.ADMIN.value,
        )
    except APIError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"Supabase user insert failed: {exc}",
        )
    except Exception as exc:
        _raise_db_unavailable(exc)

    token = _create_token(user)
    return TokenResponse(
        access_token=token,
        user=UserOut(
            id=user["id"],
            email=user["email"],
            full_name=user["full_name"],
            role=user["role"],
            tenant_id=user["tenant_id"],
        ),
    )


@router.post("/login", response_model=TokenResponse)
async def login(body: UserLogin):
    """Authenticate and return a JWT."""
    user: dict | None = None
    try:
        user = get_user_by_email(body.email)
    except APIError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"Supabase user lookup failed: {exc}",
        )
    except Exception as exc:
        _raise_db_unavailable(exc)

    if not user or not user.get("password_hash") or not _verify_password(body.password, str(user["password_hash"])):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")

    if not user.get("tenant_id"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "User is not linked to any tenant")

    token = _create_token(user)
    return TokenResponse(
        access_token=token,
        user=UserOut(
            id=user["id"],
            email=user["email"],
            full_name=user.get("full_name", ""),
            role=user["role"],
            tenant_id=user["tenant_id"],
        ),
    )
