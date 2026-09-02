from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .dependencies import get_db_session, require_owner, require_tenant
from ..core.config import get_settings
from ..db.models import User
from ..proposals.contracts import ProposalCreateRequest, ProposalResponse
from ..proposals.service import (
    ProposalConversationNotFound,
    ProposalIdempotencyConflict,
    ProposalService,
)
from ..proposals.storage import ProposalStorage
from ..services.auth import AuthenticatedOwner

router = APIRouter(prefix="/proposals", tags=["Proposals"])


def _response(proposal, duplicate: bool = False) -> ProposalResponse:
    reasons = proposal.approval_reason.split(";") if proposal.approval_reason else []
    return ProposalResponse(
        id=proposal.id,
        tenant_id=proposal.tenant_id,
        conversation_id=proposal.conversation_id,
        status=proposal.status,
        approval_reasons=reasons,
        catalog_version=proposal.catalog_version,
        template_version=proposal.template_version,
        data_hash=proposal.data_hash,
        pdf_sha256=proposal.pdf_sha256,
        pdf_storage_key=proposal.pdf_storage_key,
        duplicate=duplicate,
    )


def get_proposal_storage() -> ProposalStorage:
    return ProposalStorage(get_settings().PROPOSAL_STORAGE_ROOT)


@router.post("", response_model=ProposalResponse, status_code=status.HTTP_201_CREATED)
async def create_proposal(
    payload: ProposalCreateRequest,
    request: Request,
    owner: AuthenticatedOwner = Depends(require_owner),
    session: AsyncSession = Depends(get_db_session),
    storage: ProposalStorage = Depends(get_proposal_storage),
) -> ProposalResponse:
    # The client value is only a routing hint; authorization comes from the token.
    require_tenant(owner, payload.tenant_id)
    actor_user_id = await session.scalar(
        select(User.id).where(User.tenant_id == owner.tenant_id, User.email == owner.email)
    )
    try:
        proposal, duplicate, _ = await ProposalService(session, storage).create(
            payload,
            correlation_id=request.state.correlation_id,
            actor_user_id=actor_user_id,
        )
    except ProposalConversationNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "CONVERSATION_NOT_FOUND", "message": "Conversa não encontrada"},
        ) from exc
    except ProposalIdempotencyConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error_code": "IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_DATA",
                "message": "A chave de idempotência já foi usada com outros dados",
            },
        ) from exc
    return _response(proposal, duplicate)
