"""
app/api/dependencies.py

Shared FastAPI dependency injectors.

Provides:
  - get_db()        → yields an async SQLAlchemy session per-request.
  - get_current_user() → decodes JWT and returns the authenticated user.
  - require_role()  → factory that returns a role-guard dependency.

These are stub implementations.  Full logic is wired in Milestone 1
(DB session) and Milestone 4 (auth + role-based access).
"""

from typing import AsyncGenerator

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

# Will be populated in Milestone 1 when db/session.py is implemented.
# from app.db.session import AsyncSessionLocal

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token")


async def get_db() -> AsyncGenerator:
    """
    Yield an async database session for the duration of a single request,
    then close it — even if an exception is raised.

    Usage in a router:
        async def my_endpoint(db: AsyncSession = Depends(get_db)):
            ...
    """
    # TODO (Milestone 1): Replace with real AsyncSessionLocal
    # async with AsyncSessionLocal() as session:
    #     yield session
    raise NotImplementedError("DB session not yet initialised — implement in Milestone 1.")


async def get_current_user(token: str = Depends(oauth2_scheme)):
    """
    Decode the Bearer JWT and return the active user record.

    TODO (Milestone 4): Decode with python-jose, look up user in DB.
    """
    raise NotImplementedError("Auth not yet implemented — coming in Milestone 4.")


def require_role(*allowed_roles: str):
    """
    Dependency factory that restricts an endpoint to specific roles.

    Usage:
        @router.post("/award", dependencies=[Depends(require_role("committee_chair"))])

    TODO (Milestone 4): Integrate with get_current_user().
    """
    async def role_guard(current_user=Depends(get_current_user)):
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires one of roles: {allowed_roles}",
            )
        return current_user
    return role_guard
