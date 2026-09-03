import pytest

from src.integrations.relink import (
    RelinkAuthorizationError,
    authorize_relink_view,
    pairing_log_fields,
)
from src.integrations.whatsapp import SessionStatus


def test_relink_view_requires_authenticated_session_owner():
    with pytest.raises(RelinkAuthorizationError):
        authorize_relink_view(
            authenticated_owner_id="other-owner",
            session_owner_id="owner",
            session_id="synthetic-session",
            status=SessionStatus.RELINK_REQUIRED,
        )


def test_relink_grant_is_redacted_and_limited_to_relink_states():
    grant = authorize_relink_view(
        authenticated_owner_id="owner",
        session_owner_id="owner",
        session_id="synthetic-session",
        status=SessionStatus.QR_REQUIRED,
    )
    fields = pairing_log_fields("synthetic-session", rendered_to_owner=True)

    assert grant.qr_may_be_rendered
    assert len(grant.session_label) == 12
    assert fields == {
        "session_label": grant.session_label,
        "rendered_to_owner": True,
        "qr_logged": False,
    }
