import json
import subprocess
import sys


def test_gate_audit_uses_planned_tenant_without_creating_production_data():
    result = subprocess.run(
        [sys.executable, "scripts/audit_openwa_gate.py"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    report = json.loads(result.stdout)
    assert report["tenants"][0]["decision_pt"] == "NÃO APROVADO"
    assert report["tenants"][0]["tenant_id"] == "planned-kaelsolutions-pilot"
    assert "secret" not in result.stdout.lower()
