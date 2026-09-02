from __future__ import annotations

from .adapter import ProspectResearchAdapter
from .contracts import ProspectResearchResult, ResearchRequest


class FakeProspectResearchAdapter(ProspectResearchAdapter):
    """Contract fake; fixtures are supplied by the test, never fabricated by the API."""

    def __init__(self, result: ProspectResearchResult | None = None, error: Exception | None = None):
        self.result = result
        self.error = error
        self.calls = 0

    async def research(self, request: ResearchRequest) -> ProspectResearchResult:
        self.calls += 1
        if self.error:
            raise self.error
        if self.result is None:
            raise RuntimeError("fake sem resultado configurado")
        return self.result
