"""Evaluate frozen model predictions against the future expansion human gold.

This module never calls an API. It is intentionally implemented before the
29 expansion labels exist. The primary comparison is end-to-end (A) versus
structured with gate (C); forced-comparability (B) remains diagnostic.

Run after ``expansion_semantic_gold.csv`` has been generated:
    PYTHONPATH=src python3 -m voxlab.prospective_evaluation
"""

from __future__ import annotations

import collections
import hashlib
import json
from pathlib import Path

from .automatic_baselines import comparability_metrics, relation_metrics
from .semantic_pilot import read_csv


CONDITIONS = {
    "end_to_end_A": "relation_end_to_end",
    "forced_comparability_B_diagnostic": "relation_structured_without_gate",
    "structured_with_gate_C": "relation_structured_with_gate",
}


def paired_effect(rows: list[dict[str, str]], gold: dict[str, dict[str, str]]) -> dict:
    counts = collections.Counter()
    for row in rows:
        truth = gold[row["pair_id"]]["derived_relation"]
        a_correct = row["relation_end_to_end"] == truth
        c_correct = row["relation_structured_with_gate"] == truth
        counts[(a_correct, c_correct)] += 1
    return {
        "A_error_to_C_correct": counts[(False, True)],
        "A_correct_to_C_error": counts[(True, False)],
        "both_correct": counts[(True, True)],
        "both_error": counts[(False, False)],
    }


def evaluate_predictions(predictions: list[dict[str, str]], gold_rows: list[dict[str, str]]) -> dict:
    gold_ids = [row["pair_id"] for row in gold_rows]
    if len(gold_ids) != len(set(gold_ids)):
        raise ValueError("Expansion gold contains duplicate pair IDs")
    gold = {row["pair_id"]: row for row in gold_rows}
    if any(row.get("label_source") != "HUMAN_CONSENSUS" for row in gold_rows):
        raise ValueError("Expansion gold must be labeled HUMAN_CONSENSUS")
    if any(row.get("label_source") != "MODEL_PREDICTION" for row in predictions):
        raise ValueError("Prediction rows must remain labeled MODEL_PREDICTION")

    models = sorted({row["model"] for row in predictions})
    output: dict[str, dict] = {}
    for model in models:
        rows = [row for row in predictions if row["model"] == model]
        ids = [row["pair_id"] for row in rows]
        if len(ids) != len(set(ids)) or set(ids) != set(gold_ids):
            raise ValueError(f"Prediction/gold pair IDs are not exactly 1:1 for {model}")
        by_id = {row["pair_id"]: row for row in rows}
        ordered = [by_id[pair_id] for pair_id in gold_ids]
        relations_gold = [gold[pair_id]["derived_relation"] for pair_id in gold_ids]
        condition_metrics = {
            name: relation_metrics([row[column] for row in ordered], relations_gold)
            for name, column in CONDITIONS.items()
        }
        output[model] = {
            "primary_comparison": "end_to_end_A_vs_structured_with_gate_C",
            "conditions": condition_metrics,
            "paired_A_vs_C": paired_effect(ordered, gold),
            "comparability_gate": comparability_metrics(
                [row["same_proposition"] for row in ordered],
                [gold[pair_id]["same_proposition"] for pair_id in gold_ids],
            ),
        }
    return {
        "evaluation_role": "PROSPECTIVE_EXPANSION_HOLDOUT",
        "n_gold_pairs": len(gold_rows),
        "models": output,
        "interpretation_policy": (
            "A vs C is primary. B cannot emit INCOMPARABLE and is diagnostic only. "
            "STANCE_REVERSED recall is estimable only if the human gold contains positive examples."
        ),
    }


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    gold_path = root / "data" / "annotations" / "expansion_semantic_gold.csv"
    prediction_path = root / "data" / "processed" / "expansion29_model_predictions.csv"
    if not gold_path.exists():
        print("PENDING: expansion gold does not exist yet; complete agreement and consensus first.")
        return
    report = evaluate_predictions(read_csv(prediction_path), read_csv(gold_path))
    report["input_sha256"] = {
        str(gold_path.relative_to(root)): hashlib.sha256(gold_path.read_bytes()).hexdigest(),
        str(prediction_path.relative_to(root)): hashlib.sha256(prediction_path.read_bytes()).hexdigest(),
    }
    output = root / "data" / "processed" / "expansion29_prospective_metrics.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
