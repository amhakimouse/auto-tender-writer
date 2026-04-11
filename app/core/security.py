"""
app/core/security.py

JWT token utilities — password hashing, token creation, and token verification.

Design rules:
    - This module contains PURE FUNCTIONS only — no DB access, no HTTP.
    - All DB lookups happen in dependencies.py (get_current_user).
    - Tokens are signed with HS256 using SECRET_KEY from settings.
    - Tokens expire after ACCESS_TOKEN_EXPIRE_MINUTES from settings.

Token payload structure:
    {"sub": "user@example.com", "role": "COMMITTEE_MEMBER", "exp": <unix_ts>}
"""

from __future__ import annotations

import bcrypt
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt

from app.core.config import settings

# ── Password hashing ──────────────────────────────────────────────────────────

def hash_password(plain: str) -> str:
    """Hash a plaintext password using bcrypt directly."""
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(plain.encode('utf-8'), salt).decode('ascii')

def verify_password(plain: str, hashed: str) -> bool:
    """Return True if plain matches the stored bcrypt hash."""
    try:
        return bcrypt.checkpw(plain.encode('utf-8'), hashed.encode('ascii'))
    except ValueError:
        return False


# ── JWT ───────────────────────────────────────────────────────────────────────

def create_access_token(
    subject: str,
    role: str,
    expires_delta: timedelta | None = None,
) -> str:
    """
    Create a signed JWT access token.

    Args:
        subject:       The unique identifier for the user (email).
        role:          The user's role (stored in token payload).
        expires_delta: Custom TTL; defaults to settings.ACCESS_TOKEN_EXPIRE_MINUTES.

    Returns:
        A signed JWT string.
    """
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    payload = {
        "sub": subject,
        "role": role,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    """
    Decode and verify a JWT token.

    Returns:
        The decoded payload dict with keys: sub, role, exp, iat.

    Raises:
        JWTError: If the token is expired, tampered, or invalid.
    """
    return jwt.decode(
        token,
        settings.SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],
    )
