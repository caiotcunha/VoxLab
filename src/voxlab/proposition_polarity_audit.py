"""Diagnostic: how much observed stance disagreement is a proposition-polarity
framing artifact, versus genuine substantive disagreement.

Raised by a human annotator while building the expansion consensus sheet:
target_proposition is free text, and the same real position can be phrased
affirmatively or negated, flipping FAVOR/AGAINST without any real difference
in what the actor said. This module measures the scope of that effect on
already-collected disagreement cases. It never rewrites any existing gold,
consensus, or prediction file, and it never turns a model judgment into a
correction of human data — it only adds a diagnostic label to already-known
disagreements.

This is a separate exploratory track making real API calls (DeepInfra), like
automatic_baselines.py. No LLM judgment here is treated as ground truth.

Run after the expansion gold and gold18 pairwise analysis exist:
    PYTHONPATH=src python3 -m voxlab.proposition_polarity_audit
"""

from __future__ import annotations

import collections
import json
from pathlib import Path

from .automatic_baselines import _extract_json
from .llm_client import chat_completion, completion_text
from .semantic_pilot import read_csv

POLARITY_LABELS = {"YES", "NO", "UNCERTAIN"}
DETERMINATE_STANCES = {"FAVOR", "AGAINST"}
AUDIT_MODEL = "Qwen/Qwen2.5-72B-Instruct"
AUDIT_PROMPT_PATH = Path("prompts/proposition_polarity_audit_v1.txt")


def _model_slug(model: str) -> str:
    return model.replace("/", "_")


def human_human_expansion_cases(root: Path) -> list[dict[str, str]]:
    """Stance disagreements between the two expansion annotators, per side."""
    path = root / "data" / "annotations" / "expansion_semantic_annotation_comparison.csv"
    if not path.exists():
        return []
    cases = []
    for row in read_csv(path):
        sides = [side for side in row.get("stance_disagreement_sides", "").split("|") if side]
        for side in sides:
            cases.append({
                "source": "human_human_expansion",
                "pair_id": row["pair_id"],
                "side": side,
                "model": "",
                "proposition_x": row[f"target_proposition_1_{side}"],
                "stance_x": row[f"stance_1_{side}"],
                "proposition_y": row[f"target_proposition_2_{side}"],
                "stance_y": row[f"stance_2_{side}"],
            })
    return cases


def model_vs_gold_cases(root: Path, predictions_path: Path, gold_path: Path, source_label: str) -> list[dict[str, str]]:
    """Stance disagreements between a model's structured prediction and human gold."""
    predictions_path, gold_path = root / predictions_path, root / gold_path
    if not predictions_path.exists() or not gold_path.exists():
        return []
    gold_by_id = {row["pair_id"]: row for row in read_csv(gold_path)}
    cases = []
    for row in read_csv(predictions_path):
        gold = gold_by_id.get(row["pair_id"])
        if gold is None:
            continue
        for side in "ab":
            model_stance, gold_stance = row.get(f"stance_{side}", ""), gold.get(f"stance_{side}", "")
            if model_stance in DETERMINATE_STANCES and gold_stance in DETERMINATE_STANCES and model_stance != gold_stance:
                cases.append({
                    "source": source_label,
                    "pair_id": row["pair_id"],
                    "side": side,
                    "model": row.get("model", ""),
                    "proposition_x": row.get(f"target_proposition_{side}", ""),
                    "stance_x": model_stance,
                    "proposition_y": gold.get(f"target_proposition_{side}", ""),
                    "stance_y": gold_stance,
                })
    return cases


def collect_all_cases(root: Path) -> list[dict[str, str]]:
    return (
        human_human_expansion_cases(root)
        + model_vs_gold_cases(
            root, Path("data/processed/gold18_pairwise_analysis.csv"),
            Path("data/annotations/semantic_pilot_gold.csv"), "model_vs_gold_pilot")
        + model_vs_gold_cases(
            root, Path("data/processed/expansion29_model_predictions.csv"),
            Path("data/annotations/expansion_semantic_gold.csv"), "model_vs_gold_expansion")
    )


def parse_polarity_response(raw_text: str) -> dict:
    parsed = _extract_json(raw_text)
    if parsed is None or not isinstance(parsed, dict):
        return {"same_claim_opposite_polarity_raw": "", "same_claim_opposite_polarity_valid": False,
                "same_claim_opposite_polarity_normalized": "UNCERTAIN",
                "malformed_output": True, "reasoning": ""}
    raw_value = parsed.get("same_claim_opposite_polarity", "")
    valid = raw_value in POLARITY_LABELS
    return {"same_claim_opposite_polarity_raw": raw_value,
            "same_claim_opposite_polarity_valid": valid,
            "same_claim_opposite_polarity_normalized": raw_value if valid else "UNCERTAIN",
            "malformed_output": not valid, "reasoning": parsed.get("reasoning", "")}


def _raw_path(root: Path, case: dict[str, str]) -> Path:
    out_dir = root / "data" / "processed" / "llm_raw_outputs"
    name = f"polarity_audit_{_model_slug(AUDIT_MODEL)}_{case['pair_id']}_{case['side']}_{case['source']}"
    if case.get("model"):
        name += f"_{_model_slug(case['model'])}"
    return out_dir / f"{name}.json"


def call_polarity_check(root: Path, case: dict[str, str]) -> dict:
    """Cached like automatic_baselines: a raw response already on disk is reused verbatim."""
    path = _raw_path(root, case)
    if path.exists():
        response = json.loads(path.read_text(encoding="utf-8"))
    else:
        template = (root / AUDIT_PROMPT_PATH).read_text(encoding="utf-8")
        prompt = template.format(proposition_x=case["proposition_x"], stance_x=case["stance_x"],
                                 proposition_y=case["proposition_y"], stance_y=case["stance_y"])
        response = chat_completion(root, AUDIT_MODEL, [{"role": "user", "content": prompt}], temperature=0.0)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(response, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return parse_polarity_response(completion_text(response))


def run_audit(root: Path) -> tuple[list[dict], dict]:
    cases = collect_all_cases(root)
    rows = []
    for case in cases:
        judgment = call_polarity_check(root, case)
        rows.append({**case, **judgment})

    by_source: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for row in rows:
        by_source[row["source"]][row["same_claim_opposite_polarity_normalized"]] += 1

    summary = {
        "audit_model": AUDIT_MODEL,
        "total_disagreement_cases_examined": len(rows),
        "malformed_output_count": sum(row["malformed_output"] for row in rows),
        "by_source": {
            source: {
                "n": sum(counts.values()),
                "opposite_polarity_framing_artifact": counts.get("YES", 0),
                "genuine_disagreement": counts.get("NO", 0),
                "uncertain": counts.get("UNCERTAIN", 0),
            }
            for source, counts in by_source.items()
        },
        "interpretation": (
            "This labels each already-observed stance disagreement as a likely "
            "proposition-polarity framing artifact or a genuine disagreement, "
            "using a single LLM judgment as a diagnostic lens — never as a "
            "correction to any existing gold, consensus, or prediction file."
        ),
    }
    return rows, summary


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    rows, summary = run_audit(root)
    out = root / "data" / "processed"
    if rows:
        from .audit import write_csv
        write_csv(out / "proposition_polarity_audit.csv", rows, list(rows[0]))
    (out / "proposition_polarity_audit_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
