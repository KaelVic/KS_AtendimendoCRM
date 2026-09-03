#!/usr/bin/env python3
"""Audit all local OpenWA gate manifests without changing production state."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from src.compliance.commercial_gate import evaluate_gate_manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest-dir", type=Path, default=Path("deploy/aws/gate"))
    parser.add_argument(
        "--planned-manifest",
        type=Path,
        default=Path("deploy/aws/gate/openwa-commercial-gate.example.json"),
    )
    args = parser.parse_args()
    planned = args.planned_manifest.resolve()
    manifests = sorted(
        path for path in args.manifest_dir.glob("*.json") if path.resolve() != planned
    )
    if not manifests:
        manifests = [args.planned_manifest]

    results: list[dict[str, object]] = []
    for path in manifests:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValueError("manifest must be a JSON object")
            result = evaluate_gate_manifest(value).public_result()
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            result = {
                "decision": "NOT_APPROVED",
                "decision_pt": "NÃO APROVADO",
                "tenant_id": "unknown",
                "failed_controls": ["manifest_read"],
                "missing_evidence": ["manifest_read"],
                "owner_approved": False,
                "findings": [{
                    "control": "manifest_read",
                    "evidence": "manifesto não pôde ser lido",
                    "impact": "nenhum tenant pode ser liberado com evidência ilegível",
                    "correction": "corrigir o arquivo sem inserir segredos e repetir a auditoria",
                    "owner": "Operações",
                }],
                "error_type": type(exc).__name__,
            }
        result["manifest"] = path.as_posix()
        results.append(result)

    print(json.dumps({"tenants": results}, ensure_ascii=False, sort_keys=True))
    return 0 if all(item["decision"] == "APPROVED" for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
