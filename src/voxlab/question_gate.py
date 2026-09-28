"""Gate v2: comparability judged on neutral yes/no questions, not on answers.

The synthetic stress test showed that the v1 structured gate treats a change
of stance as a change of proposition: when side b is rewritten to the
opposite stance, the models answer same_proposition=NO and the true reversal
becomes INCOMPARABLE. v2 changes only the structured prompt: each side's
target is a neutral yes/no question, comparability is decided on the
questions alone, and the stance is the answer to the question. The JSON
schema, parser and agreement.derive_relation are the v1 ones, unchanged.

Protocol, fixed before any v2 call:
  dev  = 18 pilot gold pairs + accepted counterfactuals derived from them
  test = 29 expansion gold pairs + accepted counterfactuals derived from them
The test split runs only after --freeze has recorded the prompt hash and the
dev results; a changed prompt blocks the test run. Evaluated models are the
two v1 models, so v1 and v2 are compared on identical inputs where possible.

Caveat recorded in the doc: v2 was motivated by stress results on both
splits, so the test split is blind to v2 tuning but not to the failure
analysis that motivated it.

    PYTHONPATH=src python3 -m voxlab.question_gate --split dev             # dry-run
    PYTHONPATH=src python3 -m voxlab.question_gate --split dev --execute
    PYTHONPATH=src python3 -m voxlab.question_gate --freeze
    PYTHONPATH=src python3 -m voxlab.question_gate --split test --execute
"""

from __future__ import annotations

import argparse
import collections
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from .automatic_baselines import (
    _git_commit, comparability_metrics, parse_structured, prompt_sha256, relation_metrics,
    relation_with_gate, relation_without_gate, render_prompt,
)
from .llm_client import completion_text
from .semantic_pilot import DISPLAY_FIELDS, read_csv
from .synthetic_stress import (
    EVALUATED_MODELS, MAX_WORKERS, OUT_DIR as STRESS_DIR, cached_call, estimate_cost, estimate_tokens,
    headline, load_gold, perturbed_pair, summarize,
)

EXPERIMENT_VERSION = "question_gate_v2"
PROMPT_PATH = Path("prompts/structured_extraction_v2_question_gate.txt")
OUT_DIR = Path("data/processed/question_gate")
FREEZE_PATH = OUT_DIR / "question_gate_freeze.json"
SPLIT_ROUND = {"dev": "pilot", "test": "expansion"}
V2_CONDITIONS = ("v1_A_end_to_end", "v1_C_structured_with_gate", "v2_B_forced_comparability", "v2_C_question_gate")


# --------------------------------------------------------------------------
# Items
# --------------------------------------------------------------------------

def natural_items(gold_rows: list[dict], gold_round: str) -> list[dict]:
    """Unmodified gold pairs in chronological order; labels kept apart from the blind pair."""
    items = []
    for row in gold_rows:
        if row["gold_round"] != gold_round:
            continue
        items.append({"item_id": row["pair_id"], "kind": "natural", "source_pair_id": row["pair_id"],
                      "pair": {field: row.get(field, "") for field in DISPLAY_FIELDS},
                      "gold_relation": row["derived_relation"], "gold_same_proposition": row["same_proposition"]})
    return items


def synthetic_items(root: Path, gold_rows: list[dict], gold_round: str) -> list[dict]:
    gold = {row["pair_id"]: row for row in gold_rows}
    items = []
    for audit in read_csv(root / STRESS_DIR / "stress_generation_audit.csv"):
        if audit["accepted"] != "True" or audit["gold_round"] != gold_round:
            continue
        row = gold[audit["source_pair_id"]]
        items.append({"item_id": audit["spec_id"], "kind": "synthetic", "source_pair_id": audit["source_pair_id"],
                      "operation": audit["operation"], "expected_relation": audit["expected_relation"],
                      "pair": perturbed_pair(row, audit, audit["rewritten_text_b"])})
    return items


# --------------------------------------------------------------------------
# v1 references (cache only, no calls)
# --------------------------------------------------------------------------

def v1_natural_predictions(root: Path) -> dict[tuple[str, str], dict]:
    refs: dict[tuple[str, str], dict] = {}
    for row in read_csv(root / "data/processed/gold18_pairwise_analysis.csv"):
        refs[(row["model"], row["pair_id"])] = {"v1_A_end_to_end": row["baseline_a_relation"],
                                                "v1_C_structured_with_gate": row["structured_with_gate_relation"]}
    for row in read_csv(root / "data/processed/expansion29_model_predictions.csv"):
        refs[(row["model"], row["pair_id"])] = {"v1_A_end_to_end": row["relation_end_to_end"],
                                                "v1_C_structured_with_gate": row["relation_structured_with_gate"]}
    return refs


def v1_synthetic_predictions(root: Path) -> dict[tuple[str, str], dict]:
    return {(row["model"], row["spec_id"]): {"v1_A_end_to_end": row["A_end_to_end"],
                                             "v1_C_structured_with_gate": row["C_structured_with_gate"]}
            for row in read_csv(root / STRESS_DIR / "stress_predictions.csv")}


# --------------------------------------------------------------------------
# Calls and metrics
# --------------------------------------------------------------------------

def predict_v2(root: Path, pair: dict, model: str, execute: bool) -> dict | None:
    raw = cached_call(root, "v2_question_gate", model, pair["pair_id"], render_prompt(root / PROMPT_PATH, pair), execute)
    if raw is None:
        return None
    struct = parse_structured(completion_text(raw))
    return {"v2_B_forced_comparability": relation_without_gate(struct),
            "v2_C_question_gate": relation_with_gate(struct),
            "v2_same_proposition": struct["same_proposition_normalized"],
            "v2_question_a": struct["target_proposition_a"], "v2_question_b": struct["target_proposition_b"],
            "v2_stance_a": struct["stance_a_normalized"], "v2_stance_b": struct["stance_b_normalized"],
            "v2_malformed_output": struct["malformed_output"]}


def natural_metrics(rows: list[dict]) -> dict:
    out = {}
    for model in sorted({r["model"] for r in rows}):
        mine = [r for r in rows if r["model"] == model]
        gold = [r["gold_relation"] for r in mine]
        out[model] = {
            "n": len(mine),
            "relation": {c: relation_metrics([r[c] for r in mine], gold)
                         for c in ("v1_A_end_to_end", "v1_C_structured_with_gate", "v2_C_question_gate")},
            "v2_comparability": comparability_metrics([r["v2_same_proposition"] for r in mine],
                                                      [r["gold_same_proposition"] for r in mine]),
            "v2_malformed_output_count": sum(bool(r["v2_malformed_output"]) for r in mine),
        }
        for c in out[model]["relation"].values():
            c.pop("per_class", None)
            c.pop("macro_f1_note", None)
    return out


def dry_run(root: Path, items: list[dict]) -> dict:
    calls, tokens_in, cost = 0, 0, 0.0
    for item in items:
        prompt = render_prompt(root / PROMPT_PATH, item["pair"])
        for model in EVALUATED_MODELS:
            calls += 1
            tokens_in += estimate_tokens(prompt)
            cost += estimate_cost(model, estimate_tokens(prompt), 300)
    return {"mode": "DRY_RUN_NO_REQUESTS_SENT", "items": dict(collections.Counter(i["kind"] for i in items)),
            "calls": calls, "input_tokens": tokens_in, "estimated_cost_usd": round(cost, 4)}


def check_freeze(root: Path) -> None:
    path = root / FREEZE_PATH
    if not path.exists():
        raise RuntimeError("Test split is blocked: run --freeze after the dev split first")
    frozen = json.loads(path.read_text(encoding="utf-8"))
    if frozen["prompt_sha256"] != prompt_sha256(root / PROMPT_PATH):
        raise RuntimeError("Test split is blocked: the v2 prompt changed after it was frozen")


def run_split(root: Path, split: str, execute: bool) -> dict:
    gold_rows = load_gold(root)
    gold_round = SPLIT_ROUND[split]
    items = natural_items(gold_rows, gold_round) + synthetic_items(root, gold_rows, gold_round)
    if split == "test":
        check_freeze(root)
    if not execute:
        return {"split": split, **dry_run(root, items)}

    tasks = [(item, model) for item in items for model in EVALUATED_MODELS]
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        predictions = list(pool.map(lambda t: predict_v2(root, t[0]["pair"], t[1], execute), tasks))
    v1_nat, v1_syn = v1_natural_predictions(root), v1_synthetic_predictions(root)
    natural_rows, synthetic_rows = [], []
    for (item, model), prediction in zip(tasks, predictions):
        base = {"item_id": item["item_id"], "source_pair_id": item["source_pair_id"], "model": model, **prediction}
        if item["kind"] == "natural":
            natural_rows.append({**base, **v1_nat.get((model, item["item_id"]), {}),
                                 "gold_relation": item["gold_relation"],
                                 "gold_same_proposition": item["gold_same_proposition"]})
        else:
            synthetic_rows.append({**base, **v1_syn.get((model, item["item_id"]), {}),
                                   "spec_id": item["item_id"], "operation": item["operation"],
                                   "expected_relation": item["expected_relation"]})

    out = root / OUT_DIR
    out.mkdir(parents=True, exist_ok=True)
    from .audit import write_csv
    for name, rows in (("natural", natural_rows), ("synthetic", synthetic_rows)):
        if rows:
            write_csv(out / f"question_gate_{split}_{name}.csv", rows, list(rows[0]))
    result = {
        "experiment_version": EXPERIMENT_VERSION, "split": split, "gold_round": gold_round,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "prompt_sha256": prompt_sha256(root / PROMPT_PATH), "models": EVALUATED_MODELS,
        "natural": natural_metrics(natural_rows),
        "synthetic_headline": headline(summarize(synthetic_rows, V2_CONDITIONS), V2_CONDITIONS),
    }
    (out / f"question_gate_{split}_metrics.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def freeze(root: Path) -> dict:
    dev_path = root / OUT_DIR / "question_gate_dev_metrics.json"
    if not dev_path.exists():
        raise RuntimeError("Run the dev split with --execute before freezing")
    dev = json.loads(dev_path.read_text(encoding="utf-8"))
    if dev["prompt_sha256"] != prompt_sha256(root / PROMPT_PATH):
        raise RuntimeError("Dev results were produced with a different prompt; rerun dev first")
    frozen = {"experiment_version": EXPERIMENT_VERSION, "frozen_at": datetime.now(timezone.utc).isoformat(),
              "prompt_path": str(PROMPT_PATH), "prompt_sha256": dev["prompt_sha256"],
              "models": EVALUATED_MODELS, "git_commit": _git_commit(root)}
    (root / FREEZE_PATH).write_text(json.dumps(frozen, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return frozen


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--split", choices=sorted(SPLIT_ROUND))
    parser.add_argument("--execute", action="store_true", help="send real API requests (default: dry-run)")
    parser.add_argument("--freeze", action="store_true", help="freeze the v2 prompt after the dev split")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    if args.freeze:
        result = freeze(root)
    elif args.split:
        result = run_split(root, args.split, args.execute)
    else:
        parser.error("choose --split dev|test or --freeze")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
