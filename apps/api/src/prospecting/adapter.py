from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import httpx

from .contracts import ProspectResearchResult, ResearchRequest


class ProspectResearchError(RuntimeError):
    """Expected failure while querying the isolated research service."""

    def __init__(self, code: str, message: str = "Pesquisa indisponível") -> None:
        super().__init__(message)
        self.code = code


class ProspectResearchAdapter(ABC):
    """Port for public-source research; no domain rule depends on ScrapeGraphAI."""

    @abstractmethod
    async def research(self, request: ResearchRequest) -> ProspectResearchResult:
        raise NotImplementedError


class ScrapeGraphProspectResearchAdapter(ProspectResearchAdapter):
    def __init__(
        self,
        base_url: str,
        service_token: str | None = None,
        timeout_seconds: float = 12.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.service_token = service_token
        self.timeout_seconds = timeout_seconds
        self.client = client

    async def research(self, request: ResearchRequest) -> ProspectResearchResult:
        headers: dict[str, str] = {"X-Correlation-Id": "prospect-research"}
        if self.service_token:
            headers["X-Service-Token"] = self.service_token
        client = self.client or httpx.AsyncClient(timeout=self.timeout_seconds)
        close = self.client is None
        try:
            try:
                response = await client.post(
                    f"{self.base_url}/research",
                    headers=headers,
                    json={"url": str(request.source_url), "segment": request.segment},
                )
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                raise ProspectResearchError("RESEARCH_SERVICE_UNAVAILABLE") from exc
            if response.status_code in {400, 422}:
                raise ProspectResearchError("PUBLIC_SOURCE_REJECTED")
            if response.status_code >= 500:
                raise ProspectResearchError("RESEARCH_SERVICE_UNAVAILABLE")
            try:
                payload: Any = response.json()
                return ProspectResearchResult.model_validate(payload)
            except (ValueError, TypeError) as exc:
                raise ProspectResearchError("RESEARCH_OUTPUT_INVALID") from exc
        finally:
            if close:
                await client.aclose()


def canonicalize_source_url(value: str) -> str:
    """Normalize only transport-neutral URL details used for deduplication."""
    from urllib.parse import urlsplit, urlunsplit

    parsed = urlsplit(value.strip())
    host = (parsed.hostname or "").lower().rstrip(".")
    scheme = parsed.scheme.lower()
    port = parsed.port
    default_port = (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    netloc = host if not port or default_port else f"{host}:{port}"
    path = parsed.path or "/"
    return urlunsplit((scheme, netloc, path, parsed.query, ""))
