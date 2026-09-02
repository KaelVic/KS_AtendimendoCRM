from __future__ import annotations

from typing import Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import TypeAdapter
from pydantic.networks import HttpUrl
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import get_settings
from ..db.models import ProspectResearch, User
from ..prospecting.adapter import ScrapeGraphProspectResearchAdapter
from ..prospecting.contracts import ProspectResearchResult, ResearchRequest, ResearchResponse
from ..prospecting.service import ProspectResearchService, ResearchIdempotencyConflict
from ..services.auth import AuthenticatedOwner
from .dependencies import get_db_session, require_owner, require_tenant

router = APIRouter(prefix="/prospects", tags=["Prospecting"])


def _adapter() -> ScrapeGraphProspectResearchAdapter:
    settings = get_settings()
    return ScrapeGraphProspectResearchAdapter(
        settings.SCRAPEGRAPH_SERVICE_URL,
        settings.SCRAPEGRAPH_SERVICE_TOKEN,
        timeout_seconds=12.0,
    )


def _response(row: ProspectResearch, duplicate: bool) -> ResearchResponse:
    result = ProspectResearchResult.model_validate(row.result)
    source_url = TypeAdapter(HttpUrl).validate_python(row.source_url)
    return ResearchResponse(
        **result.model_dump(),
        id=row.id,
        tenant_id=row.tenant_id,
        source_url=source_url,
        status=cast(Literal["PENDING_REVIEW", "FAILED"], row.status),
        duplicate=duplicate,
        failure_code=row.failure_code,
    )


@router.post("/research", response_model=ResearchResponse, status_code=status.HTTP_201_CREATED)
async def research_prospect(
    payload: ResearchRequest,
    request: Request,
    owner: AuthenticatedOwner = Depends(require_owner),
    session: AsyncSession = Depends(get_db_session),
) -> ResearchResponse:
    require_tenant(owner, payload.tenant_id)
    actor_user_id = await session.scalar(
        select(User.id).where(User.tenant_id == owner.tenant_id, User.email == owner.email)
    )
    try:
        row, duplicate = await ProspectResearchService(
            session,
            _adapter(),
            get_settings().SCRAPEGRAPH_CACHE_TTL_SECONDS,
        ).research(
            payload,
            correlation_id=request.state.correlation_id,
            actor_user_id=actor_user_id,
        )
    except ResearchIdempotencyConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": str(exc),
                "message": "A chave de idempotência já foi usada com outra fonte",
            },
        ) from exc
    return _response(row, duplicate)
