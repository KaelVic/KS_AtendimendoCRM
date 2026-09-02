from fastapi import APIRouter, Depends, HTTPException, status

from .contracts import AuthResponse, LoginRequest, OwnerIdentity
from .dependencies import get_owner_authenticator, require_owner
from ..services.auth import AuthenticatedOwner, OwnerAuthenticator

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/login", response_model=AuthResponse)
async def login(request: LoginRequest, authenticator: OwnerAuthenticator = Depends(get_owner_authenticator)):
    owner = authenticator.authenticate(request.email, request.token)
    if not owner:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error_code": "INVALID_CREDENTIALS", "message": "Credenciais invÃ¡lidas"},
            headers={"WWW-Authenticate": "Bearer"},
        )
    return AuthResponse(
        access_token=request.token,
        tenant_id=owner.tenant_id,
        email=owner.email,
    )


@router.get("/me", response_model=OwnerIdentity)
async def current_owner(owner: AuthenticatedOwner = Depends(require_owner)):
    return OwnerIdentity(tenant_id=owner.tenant_id, email=owner.email, role=owner.role)
