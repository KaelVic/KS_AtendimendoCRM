"""Tenant-scoped, auditable contact opt-out handling."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select

from ..db.models import AuditEvent, Contact


_OPT_OUT_PATTERNS = (
    re.compile(r"^(?:pare|parar|stop|sair)$", re.IGNORECASE),
    re.compile(r"^(?:não|nao)\s+(?:me\s+)?(?:contate|contacte)$", re.IGNORECASE),
    re.compile(r"^(?:não|nao)\s+quero\s+receber(?:\s+mais)?$", re.IGNORECASE),
    re.compile(r"^(?:remova|remover)\s+(?:meu|o)\s+contato$", re.IGNORECASE),
)


def is_opt_out_message(content: str | None) -> bool:
    """Recognize only explicit stop requests; ambiguous text stays untouched."""
    normalized = re.sub(r"\s+", " ", (content or "").strip().rstrip(".!? "))
    return any(pattern.fullmatch(normalized) for pattern in _OPT_OUT_PATTERNS)


async def mark_contact_opt_out(
    session: Any,
    *,
    tenant_id: UUID,
    contact_id: UUID,
    correlation_id: str,
    source: str = "INBOUND_MESSAGE",
) -> bool:
    """Persist an idempotent opt-out and its audit event."""
    contact = await session.scalar(
        select(Contact).where(Contact.tenant_id == tenant_id, Contact.id == contact_id)
    )
    if contact is None:
        raise LookupError("CONTACT_NOT_FOUND")
    if contact.opted_out_at is not None:
        return False
    now = datetime.now(timezone.utc)
    contact.opted_out_at = now
    contact.opt_out_source = source[:80]
    session.add(
        AuditEvent(
            id=uuid4(),
            tenant_id=tenant_id,
            action="CONTACT_OPTED_OUT",
            target_type="contact",
            target_id=contact_id,
            correlation_id=correlation_id,
            event_metadata={"source": source[:80]},
            created_at=now,
            updated_at=now,
        )
    )
    await session.commit()
    return True
