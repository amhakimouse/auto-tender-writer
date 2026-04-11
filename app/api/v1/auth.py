"""
app/api/v1/auth.py

Authentication Router — Phase 0 (Security Layer)

Endpoints:
  POST /api/v1/auth/token    → OAuth2 password flow → returns JWT
  POST /api/v1/auth/register → Create a new user (dev/admin only)
  GET  /api/v1/auth/me       → Return current user profile

RBAC Roles (from UserRole enum):
  ADMIN            → Full access, user management
  COMMITTEE_CHAIR  → Award decisions, all committee actions
  COMMITTEE_MEMBER → Score overrides, evaluations
  REVIEWER         → Read-only + view PDFs
  READONLY         → Public data only (tender listings)

Architecture rule: Python enforces roles — the LLM is never involved in auth.
"""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db, get_current_user
from app.core.security import create_access_token, hash_password, verify_password
from app.core.config import settings
from app.db.models.user import User, UserRole

router = APIRouter()


# ── Pydantic Schemas ──────────────────────────────────────────────────────────


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Seconds until expiry")
    user_email: str
    user_role: str


class UserCreate(BaseModel):
    email: EmailStr
    name: str = Field(..., min_length=2, max_length=255)
    password: str = Field(..., min_length=8, max_length=128)
    role: UserRole = UserRole.READONLY


class UserResponse(BaseModel):
    id: int
    email: str
    name: str
    role: str
    is_active: bool

    model_config = {"from_attributes": True}


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post(
    "/token",
    response_model=Token,
    summary="OAuth2 login — exchange email+password for a JWT",
    responses={
        200: {"description": "Login successful, JWT issued"},
        401: {"description": "Invalid credentials"},
        403: {"description": "Account is disabled"},
    },
)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
) -> Token:
    """
    Standard OAuth2 password flow.

    Submit email as `username` and password in the form body.
    Returns a Bearer JWT valid for `ACCESS_TOKEN_EXPIRE_MINUTES` minutes.

    The token payload contains `sub` (email) and `role` — used by
    `get_current_user()` and `require_role()` on protected endpoints.
    """
    result = await db.execute(
        select(User).where(User.email == form_data.username.lower().strip())
    )
    user = result.scalar_one_or_none()

    # Use constant-time comparison even when user not found (timing attack prevention)
    if user is None or not verify_password(form_data.password, user.hashed_password or ""):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is disabled. Contact your administrator.",
        )

    token = create_access_token(subject=user.email, role=user.role)

    return Token(
        access_token=token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user_email=user.email,
        user_role=user.role,
    )


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user (admin use only in production)",
    responses={
        201: {"description": "User created"},
        409: {"description": "Email already registered"},
    },
)
async def register(
    user_data: UserCreate,
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """
    Create a new user account.

    In production, this endpoint should be protected by an admin role check.
    For the development / UI-seeding phase it is left open.
    """
    # Check for duplicate email
    existing = await db.execute(
        select(User).where(User.email == user_data.email.lower().strip())
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Email '{user_data.email}' is already registered.",
        )

    user = User(
        email=user_data.email.lower().strip(),
        name=user_data.name,
        role=user_data.role,
        hashed_password=hash_password(user_data.password),
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    return UserResponse.model_validate(user)


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get current authenticated user profile",
)
async def get_me(current_user: User = Depends(get_current_user)) -> UserResponse:
    """Return the profile of the currently authenticated user."""
    return UserResponse.model_validate(current_user)
