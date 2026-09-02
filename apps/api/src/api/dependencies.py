from typing import AsyncGenerator

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import get_settings
from ..db.session import async_session_factory
from ..services.auth import AuthenticatedOwner, OwnerAuthenticator

bearer = HTTPBearer(auto_error=False)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session


def get_owner_authenticator() -> OwnerAuthenticator:
    return OwnerAuthenticator(get_settings())


async def require_owner(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    authenticator: OwnerAuthenticator = Depends(get_owner_authenticator),
) -> AuthenticatedOwner:
    owner = authenticator.from_bearer(credentials.credentials if credentials else None)
    if not owner:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error_code": "AUTHENTICATION_REQUIRED", "message": "AutenticaÃ§Ã£o obrigatÃ³ria"},
            headers={"WWW-Authenticate": "Bearer"},
        )
    request.state.tenant_id = owner.tenant_id
    request.state.owner_email = owner.email
    return owner


def require_tenant(owner: AuthenticatedOwner, requested_tenant_id):
    if requested_tenant_id != owner.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error_code": "TENANT_ACCESS_DENIED", "message": "Tenant nÃ£o autorizado"},
        )
