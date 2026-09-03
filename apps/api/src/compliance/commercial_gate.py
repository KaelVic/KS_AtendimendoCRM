"""Fail-closed commercial gate evaluation.

The manifest contains only evidence references and boolean attestations. It
must never contain secrets, QR data, message content, or personal data.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping


COMMERCIAL_GATE_CONTROLS: tuple[str, ...] = (
    "contract_unofficial_risk",
    "dedicated_number",
    "opt_out",
    "limits",
    "tenant_session_isolation",
    "restricted_key",
    "webhook_hmac",
    "encrypted_volume",
    "backup_restore",
    "qr_relink",
    "unique_owner",
    "health_alerts",
    "pinned_version",
    "contract_tests",
    "independent_history",
    "support_runbook",
    "media_tests",
    "handoff",
    "deduplication",
    "outage_fail_closed",
)
MANIFEST_SCHEMA_VERSION = 1
_SAFE_EVIDENCE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_./-]{0,199}$")
_ALLOWED_MANIFEST_KEYS = {
    "schema_version",
    "tenant_id",
    "owner_approved",
    "owner_approval_evidence_ref",
    "controls",
}


@dataclass(frozen=True)
class GateEvaluation:
    decision: str
    tenant_id: str
    failed_controls: tuple[str, ...]
    missing_evidence: tuple[str, ...]
    owner_approved: bool

    @property
    def approved(self) -> bool:
        return self.decision == "APPROVED"

    def public_result(self) -> dict[str, Any]:
        """Return a safe result suitable for CLI/structured logs."""
        return {
            "decision": self.decision,
            "decision_pt": (
                "APROVADO COM RISCO EXPLÍCITO" if self.approved else "NÃO APROVADO"
            ),
            "tenant_id": self.tenant_id,
            "failed_controls": list(self.failed_controls),
            "missing_evidence": list(self.missing_evidence),
            "owner_approved": self.owner_approved,
            "findings": [
                {
                    "control": control,
                    "evidence": "evidência ausente, inválida ou não verificável",
                    "impact": "o risco do canal permanece sem controle demonstrado",
                    "correction": "anexar referência segura e validar o controle antes da ativação",
                    "owner": "proprietário da KaelSolutions com Segurança/Operações",
                }
                for control in self.failed_controls
            ],
        }


def evaluate_gate_manifest(manifest: Mapping[str, Any]) -> GateEvaluation:
    """Evaluate a non-secret gate manifest without contacting external systems."""
    tenant_id = manifest.get("tenant_id")
    tenant = tenant_id if isinstance(tenant_id, str) and tenant_id else "unknown"
    controls = manifest.get("controls")
    controls_map: Mapping[str, Any] = controls if isinstance(controls, Mapping) else {}
    failed: list[str] = []
    missing: list[str] = []

    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        failed.append("manifest_schema")
        missing.append("manifest_schema")
    if set(manifest) - _ALLOWED_MANIFEST_KEYS:
        failed.append("manifest_shape")
        missing.append("manifest_shape")

    owner_evidence = manifest.get("owner_approval_evidence_ref")
    if not isinstance(owner_evidence, str) or not _SAFE_EVIDENCE_REF.fullmatch(owner_evidence):
        failed.append("owner_approval")
        missing.append("owner_approval")

    for control in COMMERCIAL_GATE_CONTROLS:
        entry = controls_map.get(control)
        if not isinstance(entry, Mapping) or entry.get("verified") is not True:
            failed.append(control)
            missing.append(control)
            continue
        if set(entry) - {"verified", "evidence_ref"}:
            failed.append(control)
            missing.append(control)
            continue
        evidence_ref = entry.get("evidence_ref")
        if not isinstance(evidence_ref, str) or not _SAFE_EVIDENCE_REF.fullmatch(evidence_ref):
            failed.append(control)
            missing.append(control)

    owner_approved = manifest.get("owner_approved") is True
    if not owner_approved:
        failed.append("owner_approval")
        missing.append("owner_approval")

    decision = "APPROVED" if not failed else "NOT_APPROVED"
    return GateEvaluation(
        decision=decision,
        tenant_id=tenant,
        failed_controls=tuple(dict.fromkeys(failed)),
        missing_evidence=tuple(dict.fromkeys(missing)),
        owner_approved=owner_approved,
    )
