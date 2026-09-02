from __future__ import annotations

import hashlib
import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .dependencies import get_db_session, require_owner
from ..commercial.config import PaymentLinkAllowlist
from ..commercial.contracts import (
    AcceptanceRequest,
    CommercialOrderResponse,
    PaymentWebhookPayload,
    PaymentWebhookResponse,
)
from ..commercial.service import (
    AcceptanceIdempotencyConflict,
    CommercialFlowService,
    CommercialFlowError,
    PaymentAmountMismatch,
    PaymentEventConflict,
    PaymentStateRejected,
    PaymentWebhookVerifier,
    ProposalNotReady,
)
from ..core.config import get_settings
from ..db.models import CommercialOrder
from ..services.auth import AuthenticatedOwner

router = APIRouter(prefix="/commercial", tags=["Commercial flow"])


def _order_response(order: CommercialOrder, duplicate: bool = False) -> CommercialOrderResponse:
    return CommercialOrderResponse(
        id=order.id,
        tenant_id=order.tenant_id,
        proposal_id=order.proposal_id,
        conversation_id=order.conversation_id,
        status=order.status,
        expected_amount_cents=order.expected_amount_cents,
        currency=order.currency,
        catalog_version=order.catalog_version,
        contract_template_version=order.contract_template_version,
        payment_link_config_version=order.payment_link_config_version,
        payment_link=order.payment_link,
        accepted_at=order.accepted_at,
        paid_at=order.paid_at,
        onboarding_released_at=order.onboarding_released_at,
        duplicate=duplicate,
    )


def _service(session: AsyncSession) -> CommercialFlowService:
    settings = get_settings()
    links = PaymentLinkAllowlist.from_json(
        settings.PAYMENT_LINK_CONFIG_VERSION,
        settings.PAYMENT_LINK_ALLOWLIST_JSON,
    )
    return CommercialFlowService(
        session,
        contract_template_version=settings.CONTRACT_TEMPLATE_VERSION,
        payment_links=links,
    )


@router.post(
    "/proposals/{proposal_id}/accept",
    response_model=CommercialOrderResponse,
    status_code=status.HTTP_201_CREATED,
)
async def accept_proposal(
    proposal_id: UUID,
    payload: AcceptanceRequest,
    request: Request,
    owner: AuthenticatedOwner = Depends(require_owner),
    session: AsyncSession = Depends(get_db_session),
) -> CommercialOrderResponse:
    try:
        order, duplicate = await _service(session).accept(
            owner.tenant_id,
            proposal_id,
            payload.idempotency_key,
            correlation_id=request.state.correlation_id,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": str(exc), "message": "Proposta não encontrada"},
        ) from exc
    except (ProposalNotReady, AcceptanceIdempotencyConflict) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error_code": str(exc), "message": "Proposta não pode ser aceita"},
        ) from exc
    except CommercialFlowError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error_code": str(exc), "message": "Fluxo comercial não pode avançar"},
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error_code": "COMMERCIAL_CONFIGURATION_INVALID", "message": str(exc)},
        ) from exc
    return _order_response(order, duplicate)


@router.post(
    "/webhooks/payments/{provider}",
    response_model=PaymentWebhookResponse,
)
async def payment_webhook(
    provider: str,
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> PaymentWebhookResponse:
    body = await request.body()
    verifier = PaymentWebhookVerifier(get_settings().PAYMENT_WEBHOOK_SECRET)
    if not verifier.verify(body, request.headers.get("X-Payment-Signature")):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error_code": "PAYMENT_SIGNATURE_INVALID", "message": "Assinatura inválida"},
        )
    try:
        payload = PaymentWebhookPayload.model_validate(json.loads(body))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error_code": "PAYMENT_PAYLOAD_INVALID", "message": "Payload inválido"},
        ) from exc

    order = await session.scalar(
        select(CommercialOrder).where(CommercialOrder.id == payload.payment_reference)
    )
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "COMMERCIAL_ORDER_NOT_FOUND", "message": "Pedido não encontrado"},
        )
    try:
        result = await CommercialFlowService(session).process_payment(
            order.tenant_id,
            provider,
            payload,
            hashlib.sha256(body).hexdigest(),
            correlation_id=request.headers.get("X-Correlation-ID", "payment-webhook"),
        )
    except PaymentEventConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error_code": "PAYMENT_EVENT_CONFLICT", "message": str(exc)},
        ) from exc
    except PaymentAmountMismatch as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error_code": "PAYMENT_AMOUNT_MISMATCH", "message": str(exc)},
        ) from exc
    except PaymentStateRejected as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error_code": "PAYMENT_STATE_REJECTED", "message": str(exc)},
        ) from exc
    return PaymentWebhookResponse(
        event_id=result.event.id,
        commercial_order_id=result.order.id,
        status=result.order.status,
        duplicate=result.duplicate,
    )
