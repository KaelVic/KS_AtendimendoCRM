import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
EVAL = ROOT / "tests" / "eval"

sys.path.insert(0, str(ROOT / "scripts"))
from evaluate_agent import DIMENSIONS, REQUIRED_CATEGORIES, EvaluationError, load_split, validate_dataset  # noqa: E402


def test_dataset_has_minimum_cases_split_and_required_coverage():
    summary = validate_dataset()
    assert summary["dev_cases"] >= 24
    assert summary["holdout_cases"] >= 6
    assert len(summary["holdout_sha256"]) == 64
    assert REQUIRED_CATEGORIES <= set(summary["categories"])


def test_cases_have_no_real_contact_shape_or_unexpected_fields():
    for split in ("dev", "holdout"):
        data = load_split(split)
        for case in data["cases"]:
            serialized = json.dumps(case, ensure_ascii=False).lower()
            assert "@gmail.com" not in serialized
            assert "@" not in serialized
            assert not any(key in serialized for key in ("api_key", "secret", "password", "token"))
            assert all(part["role"] == "customer" for part in case["input"])


def test_rubric_has_exact_seven_dimensions_and_zero_to_four_anchors():
    rubric = json.loads((EVAL / "rubric.json").read_text(encoding="utf-8"))
    assert set(rubric["dimensions"]) == set(DIMENSIONS)
    assert set(rubric["scale"]["anchors"]) == {"0", "1", "2", "3", "4"}
    assert rubric["approval"]["minimum_average"] == 3.0


def test_holdout_cannot_be_scored_without_explicit_confirmation(tmp_path):
    holdout = load_split("holdout")
    judgments = {
        "dataset_version": "v1",
        "split": "holdout",
        "prompt_version": "agent-test-v1",
        "judgments": [
            {
                "case_id": case["id"],
                "scores": {dimension: 4 for dimension in DIMENSIONS},
                "blocking_violation": False,
            }
            for case in holdout["cases"]
        ],
    }
    path = tmp_path / "scores.json"
    path.write_text(json.dumps(judgments), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "scripts/evaluate_agent.py", "--split", "holdout", "--judgments", str(path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "allow-holdout" in result.stderr


def test_invalid_score_and_blocking_case_fail_gate(tmp_path):
    data = load_split("dev")
    rows = [
        {
            "case_id": case["id"],
            "scores": {dimension: 4 for dimension in DIMENSIONS},
            "blocking_violation": case["id"] == data["cases"][0]["id"],
        }
        for case in data["cases"]
    ]
    path = tmp_path / "scores.json"
    path.write_text(json.dumps({"dataset_version": "v1", "split": "dev", "prompt_version": "agent-test-v1", "judgments": rows}), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "scripts/evaluate_agent.py", "--split", "dev", "--judgments", str(path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    report = json.loads(result.stdout)
    assert report["passed"] is False
    assert report["blocking_failures"] == [data["cases"][0]["id"]]


def test_complete_judgment_passes_gate(tmp_path):
    data = load_split("dev")
    judgments = {
        "dataset_version": "v1",
        "split": "dev",
        "prompt_version": "agent-test-v1",
        "judgments": [
            {
                "case_id": case["id"],
                "scores": {dimension: 4 for dimension in DIMENSIONS},
                "blocking_violation": False,
            }
            for case in data["cases"]
        ],
    }
    path = tmp_path / "scores.json"
    path.write_text(json.dumps(judgments), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "scripts/evaluate_agent.py", "--split", "dev", "--judgments", str(path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert json.loads(result.stdout)["passed"] is True


def test_dataset_validator_rejects_wrong_split_id():
    with pytest.raises(EvaluationError):
        _ = load_split("invalid")
