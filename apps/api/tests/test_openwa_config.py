import hashlib
import json

import pytest

from src.compliance.commercial_gate import COMMERCIAL_GATE_CONTROLS
from src.core.config import Settings, validate_openwa_settings


def _manifest() -> dict[str, object]:
    return {
        "schema_version": 1,
        "tenant_id": "synthetic-tenant",
        "owner_approved": True,
        "owner_approval_evidence_ref": "evidence/owner-approval",
        "controls": {
            control: {"verified": True, "evidence_ref": f"evidence/{control}"}
            for control in COMMERCIAL_GATE_CONTROLS
        },
    }


def _settings(path: str, digest: str) -> Settings:
    return Settings(
        OPENWA_COMMERCIAL_USE=True,
        OPENWA_COMMERCIAL_GATE_APPROVED=True,
        OPENWA_GATE_EVIDENCE_FILE=path,
        OPENWA_GATE_EVIDENCE_SHA256=digest,
        OPENWA_API_KEY="k" * 32,
        OPENWA_API_MASTER_KEY="m" * 32,
        OPENWA_API_KEY_PEPPER="p" * 32,
        OPENWA_WEBHOOK_SECRET="webhook-test-secret",
        OPENWA_DEDICATED_NUMBER_REF="vault://number/kaelsolutions-pilot",
        OPENWA_ALLOWED_SESSIONS="kaelsolutions_pilot",
        OPENWA_ALLOWED_IPS="172.30.0.0/24",
    )


def test_commercial_startup_accepts_only_hashed_approved_manifest(tmp_path):
    path = tmp_path / "gate.json"
    raw = json.dumps(_manifest(), sort_keys=True).encode()
    path.write_bytes(raw)

    validate_openwa_settings(_settings(str(path), hashlib.sha256(raw).hexdigest()))


def test_commercial_startup_rejects_hash_of_not_approved_manifest(tmp_path):
    path = tmp_path / "gate.json"
    value = _manifest()
    value["owner_approved"] = False
    raw = json.dumps(value, sort_keys=True).encode()
    path.write_bytes(raw)

    with pytest.raises(RuntimeError, match="manifesto"):
        validate_openwa_settings(_settings(str(path), hashlib.sha256(raw).hexdigest()))
