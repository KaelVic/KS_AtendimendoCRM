import secrets
from dataclasses import dataclass
from uuid import UUID

from ..core.config import Settings


@dataclass(frozen=True)
class AuthenticatedOwner:
    tenant_id: UUID
    email: str
    role: str = "OWNER"


class OwnerAuthenticator:
    """Adapter local para o único proprietário enquanto não há IdP configurado."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def authenticate(self, email: str, token: str) -> AuthenticatedOwner | None:
        configured = self.settings.OWNER_AUTH_TOKEN
        if not configured or not secrets.compare_digest(token, configured):
            return None
        if not secrets.compare_digest(email.casefold(), self.settings.ADMIN_EMAIL.casefold()):
            return None
        return AuthenticatedOwner(
            tenant_id=UUID(self.settings.DEFAULT_TENANT_ID),
            email=self.settings.ADMIN_EMAIL,
        )

    def from_bearer(self, token: str | None) -> AuthenticatedOwner | None:
        if not token:
            return None
        return self.authenticate(self.settings.ADMIN_EMAIL, token)
