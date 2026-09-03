from src.compliance.commercial_gate import COMMERCIAL_GATE_CONTROLS, evaluate_gate_manifest


def manifest(*, verified: bool, owner_approved: bool) -> dict:
    return {
        "schema_version": 1,
        "tenant_id": "synthetic-tenant",
        "owner_approved": owner_approved,
        "owner_approval_evidence_ref": "evidence/owner-approval",
        "controls": {
            control: {"verified": verified, "evidence_ref": f"evidence/{control}"}
            for control in COMMERCIAL_GATE_CONTROLS
        },
    }


def test_gate_is_fail_closed_when_evidence_or_owner_approval_is_missing():
    result = evaluate_gate_manifest({"tenant_id": "synthetic-tenant", "controls": {}})

    assert result.decision == "NOT_APPROVED"
    assert "owner_approval" in result.failed_controls
    assert "manifest_schema" in result.failed_controls
    assert set(COMMERCIAL_GATE_CONTROLS) <= set(result.missing_evidence)


def test_gate_approves_only_complete_non_secret_manifest():
    result = evaluate_gate_manifest(manifest(verified=True, owner_approved=True))

    assert result.approved
    assert result.public_result()["decision_pt"] == "APROVADO COM RISCO EXPLÍCITO"
    assert result.public_result()["failed_controls"] == []


def test_gate_requires_evidence_reference_for_each_verified_control():
    value = manifest(verified=True, owner_approved=True)
    value["controls"]["backup_restore"] = {"verified": True}

    result = evaluate_gate_manifest(value)

    assert result.decision == "NOT_APPROVED"
    assert "backup_restore" in result.failed_controls


def test_gate_rejects_arbitrary_manifest_fields_and_unsafe_evidence_refs():
    value = manifest(verified=True, owner_approved=True)
    value["secret"] = "must-not-be-accepted"
    value["controls"]["backup_restore"] = {
        "verified": True,
        "evidence_ref": "../../secret",
    }

    result = evaluate_gate_manifest(value)

    assert result.decision == "NOT_APPROVED"
    assert "manifest_shape" in result.failed_controls
    assert "backup_restore" in result.failed_controls
