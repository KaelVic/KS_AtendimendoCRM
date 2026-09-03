"""Owner-only relink/QR authorization helpers.

The gateway-specific QR endpoint is intentionally not guessed here. This
module protects the UI boundary and provides only redacted operational data.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from .whatsapp import SessionStatus


class RelinkAuthorizationError(RuntimeError):
    pass


@dataclass(frozen=True)
class RelinkGrant:
    session_label: str
    owner_id: str
    status: SessionStatus
    qr_may_be_rendered: bool = True


def authorize_relink_view(
    *,
    authenticated_owner_id: str | None,
    session_owner_id: str | None,
    session_id: str,
    status: SessionStatus,
) -> RelinkGrant:
    """Allow QR/pairing UI only to the authenticated owner and right state."""
    if not authenticated_owner_id or authenticated_owner_id != session_owner_id:
        raise RelinkAuthorizationError("owner authentication required")
    if status not in {SessionStatus.QR_REQUIRED, SessionStatus.RELINK_REQUIRED}:
        raise RelinkAuthorizationError("session does not require relink")
    return RelinkGrant(
        session_label=hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:12],
        owner_id=authenticated_owner_id,
        status=status,
    )


def pairing_log_fields(session_id: str, *, rendered_to_owner: bool) -> dict[str, object]:
    """Return safe fields for structured logs; never include QR or session ID."""
    return {
        "session_label": hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:12],
        "rendered_to_owner": rendered_to_owner,
        "qr_logged": False,
    }
