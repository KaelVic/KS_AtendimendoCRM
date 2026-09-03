#!/usr/bin/env python3
"""Validate a non-secret OpenWA commercial-gate manifest."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from src.compliance.commercial_gate import evaluate_gate_manifest  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"decision": "NOT_APPROVED", "error": type(exc).__name__}))
        return 2
    if not isinstance(manifest, dict):
        print(json.dumps({"decision": "NOT_APPROVED", "error": "manifest_must_be_object"}))
        return 2
    result = evaluate_gate_manifest(manifest).public_result()
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["decision"] == "APPROVED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
