from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

import pytest


ARTIFACT_ROOT = Path(os.getenv("E2E_ARTIFACT_DIR", "test-results/e2e"))


@dataclass
class Evidence:
    """Writes a PII-free execution record for every E2E scenario."""

    nodeid: str
    correlation_id: str = field(default_factory=lambda: f"e2e-{uuid4().hex}")
    started_at: float = field(default_factory=time.perf_counter)
    steps: list[dict[str, str]] = field(default_factory=list)
    logs: list[dict[str, str]] = field(default_factory=list)
    data: dict[str, str] = field(
        default_factory=lambda: {
            "tenant": "synthetic-tenant",
            "contact": "synthetic-contact",
            "external_side_effect": "none",
        }
    )
    screenshot: str | None = None

    def step(self, name: str, result: str = "passed") -> None:
        self.steps.append({"name": name, "result": result})

    def log(self, message: str, level: str = "INFO") -> None:
        self.logs.append({"correlation_id": self.correlation_id, "level": level, "message": message})

    def screenshot_path(self, name: str = "ui.png") -> Path:
        path = ARTIFACT_ROOT / f"{_safe_name(self.nodeid)}-{name}"
        path.parent.mkdir(parents=True, exist_ok=True)
        self.screenshot = str(path)
        return path


def _safe_name(value: str) -> str:
    return "".join(character if character.isalnum() else "_" for character in value)


@pytest.fixture(autouse=True)
def evidence(request: pytest.FixtureRequest) -> Evidence:
    record = Evidence(request.node.nodeid)
    request.node._e2e_evidence = record
    return record


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[object]):
    outcome = yield
    report = outcome.get_result()
    if report.when == "call":
        record = getattr(item, "_e2e_evidence", None)
        if record is None:
            return
        ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
        payload = {
            "nodeid": record.nodeid,
            "correlation_id": record.correlation_id,
            "duration_ms": round((time.perf_counter() - record.started_at) * 1000, 2),
            "outcome": report.outcome,
            "steps": record.steps,
            "logs": record.logs,
            "data": record.data,
            "screenshot": record.screenshot,
        }
        (ARTIFACT_ROOT / f"{_safe_name(record.nodeid)}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
