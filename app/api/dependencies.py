"""
app/api/dependencies.py

Shared FastAPI dependency injectors.

Provides:
  - get_db()        → yields an async SQLAlchemy session per-request.
  - get_current_user() → decodes JWT and returns the authenticated user.
  - require_role()  → factory that returns a role-guard dependency.

Usage in routers:
    from fastapi import Depends
    from sqlalchemy.ext.asyncio import AsyncSession

    @router.post("/upload")
    async def upload_offer(
        file: UploadFile,
        db: AsyncSession = Depends(get_db),
    ):
        ...
"""

from typing import Annotated, AsyncGenerator

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token")


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Yield an async database session for the duration of a single request,
    then close it — even if an exception is raised.

    The session is configured with expire_on_commit=False, so ORM objects
    remain accessible after the transaction commits (needed for response
    serialization in FastAPI).

    Usage in a router:
        async def my_endpoint(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# Type alias for cleaner dependency injection
db_dependency = Annotated[AsyncSession, Depends(get_db)]


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
