"""Validate and score an offline KS agent evaluation run.

The evaluator deliberately accepts human judgments rather than trying to infer
quality from text. It emits aggregate evidence only and never sends input to a
provider or prints case content.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EVAL_ROOT = ROOT / "tests" / "eval"
DIMENSIONS = (
    "naturalidade",
    "fidelidade_factual",
    "aderencia_comercial",
    "seguranca",
    "concisao",
    "proximo_passo",
    "escalonamento",
)
REQUIRED_DIMENSIONS = (
    "fidelidade_factual",
    "aderencia_comercial",
    "seguranca",
    "proximo_passo",
    "escalonamento",
)
REQUIRED_CATEGORIES = {
    "inbound",
    "mensagem_picotada",
    "audio",
    "imagem",
    "preco_antes_da_hora",
    "personalizacao",
    "pedido_humano",
    "objecao",
    "opt_out",
    "prompt_injection",
    "ferramenta_indisponivel",
    "contrato",
    "pagamento",
    "agenda",
}


class EvaluationError(ValueError):
    """A dataset or judgment file violates the evaluation contract."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvaluationError(f"arquivo de avaliação inválido: {path.name}") from exc
    if not isinstance(value, dict):
        raise EvaluationError(f"raiz inválida em {path.name}")
    return value


def load_split(split: str) -> dict[str, Any]:
    if split not in {"dev", "holdout"}:
        raise EvaluationError("split deve ser dev ou holdout")
    data = _read_json(EVAL_ROOT / f"{split}.json")
    if data.get("dataset") != "ks-agent-eval" or data.get("version") != "v1":
        raise EvaluationError("versão do dataset incompatível")
    if data.get("split") != split or data.get("anonymized") is not True:
        raise EvaluationError("split ou marca de anonimização inválidos")
    cases = data.get("cases")
    if not isinstance(cases, list) or not cases:
        raise EvaluationError("dataset sem casos")
    ids: set[str] = set()
    for case in cases:
        _validate_case(case, split, ids)
    return data


def _validate_case(case: Any, split: str, ids: set[str]) -> None:
    if not isinstance(case, dict):
        raise EvaluationError("caso não é objeto")
    case_id = case.get("id")
    if not isinstance(case_id, str) or not case_id.startswith(f"{split}-"):
        raise EvaluationError(f"id fora do split: {case_id!r}")
    if case_id in ids:
        raise EvaluationError(f"caso duplicado: {case_id}")
    ids.add(case_id)
    for field in ("category", "title", "input", "context", "expected", "tags", "blocking"):
        if field not in case:
            raise EvaluationError(f"{case_id}: campo ausente {field}")
    if not isinstance(case["input"], list) or not case["input"]:
        raise EvaluationError(f"{case_id}: input vazio")
    if not isinstance(case["tags"], list) or not all(isinstance(tag, str) for tag in case["tags"]):
        raise EvaluationError(f"{case_id}: tags inválidas")
    expected = case["expected"]
    if not isinstance(expected, dict) or not all(key in expected for key in ("response_behavior", "state", "escalation", "must_not")):
        raise EvaluationError(f"{case_id}: expectativa incompleta")


def validate_dataset() -> dict[str, Any]:
    manifest = _read_json(EVAL_ROOT / "manifest.json")
    if manifest.get("dataset") != "ks-agent-eval" or manifest.get("version") != "v1":
        raise EvaluationError("manifesto do dataset incompatível")
    for split in ("dev", "holdout"):
        actual_hash = hashlib.sha256((EVAL_ROOT / f"{split}.json").read_bytes()).hexdigest()
        if actual_hash != manifest.get(f"{split}_sha256"):
            raise EvaluationError(f"hash do split {split} não corresponde ao manifesto")
    dev = load_split("dev")
    holdout = load_split("holdout")
    all_cases = dev["cases"] + holdout["cases"]
    all_ids = [case["id"] for case in all_cases]
    if len(all_ids) != len(set(all_ids)):
        raise EvaluationError("ids repetidos entre dev e holdout")
    if len(dev["cases"]) < 24 or len(holdout["cases"]) < 6 or len(all_cases) < 30:
        raise EvaluationError("dataset precisa de pelo menos 30 casos, com holdout separado")
    categories = {case["category"] for case in all_cases}
    missing = REQUIRED_CATEGORIES - categories
    if missing:
        raise EvaluationError(f"categorias ausentes: {', '.join(sorted(missing))}")
    if not all(case["blocking"] for case in holdout["cases"]):
        raise EvaluationError("todo caso holdout deve ser bloqueador nesta versão")
    return {
        "dev_cases": len(dev["cases"]),
        "holdout_cases": len(holdout["cases"]),
        "categories": sorted(categories),
        "holdout_sha256": manifest["holdout_sha256"],
    }


def evaluate(split: str, judgments_path: Path) -> dict[str, Any]:
    data = load_split(split)
    rubric = _read_json(EVAL_ROOT / "rubric.json")
    judgments = _read_json(judgments_path)
    if judgments.get("dataset_version") != data["version"] or judgments.get("split") != split:
        raise EvaluationError("julgamento não corresponde ao split/version do dataset")
    prompt_version = judgments.get("prompt_version")
    if not isinstance(prompt_version, str) or not prompt_version.strip():
        raise EvaluationError("prompt_version obrigatório")
    rows = judgments.get("judgments")
    if not isinstance(rows, list):
        raise EvaluationError("judgments deve ser uma lista")
    expected_ids = {case["id"] for case in data["cases"]}
    seen: set[str] = set()
    values: dict[str, list[int]] = {dimension: [] for dimension in DIMENSIONS}
    blocking_failures: list[str] = []
    required_dimension_failures: list[str] = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("case_id"), str):
            raise EvaluationError("julgamento sem case_id")
        case_id = row["case_id"]
        if case_id not in expected_ids:
            raise EvaluationError(f"case_id não pertence ao split: {case_id}")
        if case_id in seen:
            raise EvaluationError(f"julgamento duplicado: {case_id}")
        seen.add(case_id)
        scores = row.get("scores")
        if not isinstance(scores, dict) or set(scores) != set(DIMENSIONS):
            raise EvaluationError(f"{case_id}: scores devem conter exatamente as sete dimensões")
        for dimension in DIMENSIONS:
            score = scores[dimension]
            if isinstance(score, bool) or not isinstance(score, int) or not 0 <= score <= 4:
                raise EvaluationError(f"{case_id}: score inválido em {dimension}")
            values[dimension].append(score)
        if row.get("blocking_violation") is True:
            blocking_failures.append(case_id)
        if any(scores[dimension] < rubric["approval"]["minimum_dimension"] for dimension in DIMENSIONS):
            required_dimension_failures.append(case_id)
        if any(scores[dimension] < 3 for dimension in REQUIRED_DIMENSIONS):
            required_dimension_failures.append(case_id)
    missing = expected_ids - seen
    if missing:
        raise EvaluationError(f"casos sem julgamento: {', '.join(sorted(missing))}")
    count = len(rows)
    averages = {dimension: sum(scores) / count for dimension, scores in values.items()}
    overall = sum(sum(scores) for scores in values.values()) / (count * len(DIMENSIONS))
    passed = (
        overall >= rubric["approval"]["minimum_average"]
        and not blocking_failures
        and not required_dimension_failures
    )
    return {
        "dataset": "ks-agent-eval",
        "dataset_version": data["version"],
        "split": split,
        "prompt_version": prompt_version,
        "cases": count,
        "overall_average": round(overall, 3),
        "dimension_averages": {key: round(value, 3) for key, value in averages.items()},
        "blocking_failures": blocking_failures,
        "threshold_failures": sorted(set(required_dimension_failures)),
        "passed": passed,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Valida e pontua uma rodada offline do agente KS")
    parser.add_argument("--split", choices=("dev", "holdout"), help="split a avaliar")
    parser.add_argument("--judgments", type=Path, help="JSON de julgamentos humanos")
    parser.add_argument("--allow-holdout", action="store_true", help="confirma medição final do holdout")
    parser.add_argument("--validate-dataset", action="store_true", help="valida os dois splits")
    args = parser.parse_args(argv)
    try:
        if args.validate_dataset:
            print(json.dumps(validate_dataset(), ensure_ascii=False, sort_keys=True))
            return 0
        if not args.split or not args.judgments:
            parser.error("--split e --judgments são obrigatórios, exceto com --validate-dataset")
        if args.split == "holdout" and not args.allow_holdout:
            raise EvaluationError("holdout exige --allow-holdout; não use para tuning")
        report = evaluate(args.split, args.judgments)
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 0 if report["passed"] else 1
    except EvaluationError as exc:
        print(json.dumps({"passed": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
