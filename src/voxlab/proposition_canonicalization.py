"""Proposition canonicalization: how much stance (dis)agreement is framing.

target_proposition is free text, so the same real position can be written
affirmatively or negated, flipping FAVOR/AGAINST. proposition_polarity_audit
looked only at existing disagreements, with a judge that saw the stances.
This module extends it in three ways, without new human annotation:

1. It covers every side where both sources give a determinate stance, not
   only disagreements, so it also finds agreements that are hidden
   disagreements (opposite framing plus opposite stance).
2. Two judges, neither of them an evaluated model, classify each proposition
   pair as EQUIVALENT / OPPOSITE_POLARITY / DIFFERENT / UNCERTAIN without
   seeing the stances. Stance y is flipped only when both say
   OPPOSITE_POLARITY.
3. Expansion model predictions were collected in annotator 1's display
   order; they are realigned to chronological gold sides before any
   side-level comparison.

It also checks within-pair framing: for pairs judged same_proposition=YES,
opposite framing of prop_a and prop_b turns MAINTAINED into REVERSED and vice
versa, which is exactly the false-reversal mechanism the gate targets.

No existing gold, consensus or prediction file is modified. Judgments are
MODEL_JUDGMENT, a diagnostic lens, never a correction of human labels.

    PYTHONPATH=src python3 -m voxlab.proposition_canonicalization            # dry-run
    PYTHONPATH=src python3 -m voxlab.proposition_canonicalization --execute  # real calls
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from .agreement import categorical_agreement
from .audit import write_csv
from .automatic_baselines import _extract_json, _git_commit, prompt_sha256
from .llm_client import completion_text
from .semantic_pilot import read_csv
from .synthetic_stress import (
    GENERATOR_MODEL, MAX_WORKERS, VERIFIER_MODEL, cached_call, estimate_cost, estimate_tokens,
)

EXPERIMENT_VERSION = "proposition_canonicalization_v1"
JUDGES = [GENERATOR_MODEL, VERIFIER_MODEL]
PROMPT_PATH = Path("prompts/proposition_canonicalization_v1.txt")
OUT_DIR = Path("data/processed/canonicalization")
RELATIONS = {"EQUIVALENT", "OPPOSITE_POLARITY", "DIFFERENT", "UNCERTAIN"}
DETERMINATE = {"FAVOR", "AGAINST"}
FLIP = {"FAVOR": "AGAINST", "AGAINST": "FAVOR"}

ANNOTATIONS = Path("data/annotations")
PROCESSED = Path("data/processed")


# --------------------------------------------------------------------------
# Items: one (proposition_x, stance_x, proposition_y, stance_y) per side.
# --------------------------------------------------------------------------

def _item(source: str, pair_id: str, side: str, model: str,
          prop_x: str, stance_x: str, prop_y: str, stance_y: str) -> dict | None:
    if stance_x not in DETERMINATE or stance_y not in DETERMINATE:
        return None
    if not prop_x.strip() or not prop_y.strip():
        return None
    return {"source": source, "pair_id": pair_id, "side": side, "model": model,
            "proposition_x": prop_x.strip(), "stance_x": stance_x,
            "proposition_y": prop_y.strip(), "stance_y": stance_y}


def human_human_items(root: Path, comparison_path: Path, source: str) -> list[dict]:
    """Annotator 1 (x) versus annotator 2 (y); the comparison file is already chronological."""
    items = []
    for row in read_csv(root / comparison_path):
        for side in "ab":
            if row[f"stance_determinable_1_{side}"] != "YES" or row[f"stance_determinable_2_{side}"] != "YES":
                continue
            item = _item(source, row["pair_id"], side, "",
                         row[f"target_proposition_1_{side}"], row[f"stance_1_{side}"],
                         row[f"target_proposition_2_{side}"], row[f"stance_2_{side}"])
            if item:
                items.append(item)
    return items


def realign_expansion_predictions(predictions: list[dict[str, str]],
                                  reference: list[dict[str, str]]) -> list[dict[str, str]]:
    """Swap a/b fields where annotator 1 saw the later side as A.

    expansion29_model_predictions.csv was produced from annotator 1's blind
    packet, whose A/B presentation is randomized; the gold is chronological.
    """
    display = {row["pair_id"]: row["annotator_1_display_a_source_side"] for row in reference}
    output = []
    for row in predictions:
        side = display[row["pair_id"]]
        if side not in {"a", "b"}:
            raise ValueError(f"Unknown display side for {row['pair_id']}: {side!r}")
        if side == "a":
            output.append(dict(row))
            continue
        swapped = dict(row)
        for key in row:
            if key.endswith("_a") and key[:-2] + "_b" in row:
                swapped[key], swapped[key[:-2] + "_b"] = row[key[:-2] + "_b"], row[key]
        output.append(swapped)
    return output


def model_predictions_chronological(root: Path) -> tuple[list[dict], dict[str, dict]]:
    """(model rows in gold side order, gold rows by pair_id) for pilot + expansion."""
    pilot_gold = {r["pair_id"]: r for r in read_csv(root / ANNOTATIONS / "semantic_pilot_gold.csv")}
    exp_gold = {r["pair_id"]: r for r in read_csv(root / ANNOTATIONS / "expansion_semantic_gold.csv")}
    pilot_rows = [{**r, "gold_round": "pilot"} for r in read_csv(root / PROCESSED / "gold18_pairwise_analysis.csv")]
    exp_rows = realign_expansion_predictions(
        read_csv(root / PROCESSED / "expansion29_model_predictions.csv"),
        read_csv(root / ANNOTATIONS / "expansion_semantic_pilot_reference.csv"))
    exp_rows = [{**r, "gold_round": "expansion"} for r in exp_rows]
    return pilot_rows + exp_rows, {**pilot_gold, **exp_gold}


def model_vs_gold_items(model_rows: list[dict], gold: dict[str, dict]) -> list[dict]:
    items = []
    for row in model_rows:
        truth = gold[row["pair_id"]]
        for side in "ab":
            item = _item(f"model_vs_gold_{row['gold_round']}", row["pair_id"], side, row["model"],
                         row[f"target_proposition_{side}"], row[f"stance_{side}"],
                         truth[f"target_proposition_{side}"], truth[f"stance_{side}"])
            if item:
                items.append(item)
    return items


def within_pair_items(model_rows: list[dict], gold: dict[str, dict]) -> list[dict]:
    """prop_a (x) versus prop_b (y) where the source itself said same_proposition=YES."""
    items = []
    for pid, row in sorted(gold.items()):
        if row["same_proposition"] == "YES":
            item = _item("within_pair_gold", pid, "ab", "", row["target_proposition_a"], row["stance_a"],
                         row["target_proposition_b"], row["stance_b"])
            if item:
                items.append(item)
    for row in model_rows:
        if row["same_proposition"] == "YES":
            item = _item(f"within_pair_model_{row['gold_round']}", row["pair_id"], "ab", row["model"],
                         row["target_proposition_a"], row["stance_a"],
                         row["target_proposition_b"], row["stance_b"])
            if item:
                items.append(item)
    return items


def collect_items(root: Path) -> list[dict]:
    model_rows, gold = model_predictions_chronological(root)
    return (
        human_human_items(root, ANNOTATIONS / "semantic_annotation_comparison.csv", "human_human_pilot")
        + human_human_items(root, ANNOTATIONS / "expansion_semantic_annotation_comparison.csv",
                            "human_human_expansion")
        + model_vs_gold_items(model_rows, gold)
        + within_pair_items(model_rows, gold)
    )


# --------------------------------------------------------------------------
# Judging
# --------------------------------------------------------------------------

def judgment_key(prop_x: str, prop_y: str) -> str:
    """Cache key by text, so identical proposition pairs are judged once per judge."""
    return hashlib.sha256(f"{prop_x}\x1f{prop_y}".encode("utf-8")).hexdigest()[:20]


def render(root: Path, prop_x: str, prop_y: str) -> str:
    template = (root / PROMPT_PATH).read_text(encoding="utf-8")
    return template.format(proposition_x=prop_x, proposition_y=prop_y)


def parse_judgment(raw_text: str) -> dict:
    parsed = _extract_json(raw_text or "")
    value = parsed.get("relation", "") if isinstance(parsed, dict) else ""
    valid = value in RELATIONS
    return {"relation": value if valid else "UNCERTAIN", "malformed_output": not valid,
            "reasoning": parsed.get("reasoning", "") if isinstance(parsed, dict) else ""}


def consensus_relation(judgments: list[str]) -> str:
    """Unanimous label, else UNCERTAIN; only unanimous OPPOSITE_POLARITY flips a stance."""
    return judgments[0] if len(set(judgments)) == 1 else "UNCERTAIN"


def aligned_stance_y(item: dict, relation: str) -> str:
    return FLIP[item["stance_y"]] if relation == "OPPOSITE_POLARITY" else item["stance_y"]


# --------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------

def source_metrics(rows: list[dict]) -> dict:
    before_x = [r["stance_x"] for r in rows]
    before_y = [r["stance_y"] for r in rows]
    after_y = [r["aligned_stance_y"] for r in rows]
    transitions = collections.Counter(
        ("agree" if r["stance_x"] == r["stance_y"] else "disagree")
        + "->" + ("agree" if r["stance_x"] == r["aligned_stance_y"] else "disagree")
        for r in rows)
    residual = collections.Counter(r["consensus_relation"] for r in rows if r["stance_x"] != r["aligned_stance_y"])
    return {
        "n_sides": len(rows),
        "relation_distribution": dict(collections.Counter(r["consensus_relation"] for r in rows)),
        "stance_before": categorical_agreement(before_x, before_y),
        "stance_after_alignment": categorical_agreement(before_x, after_y),
        "transitions": dict(transitions),
        "residual_disagreements_by_relation": dict(residual),
    }


def within_pair_metrics(rows: list[dict]) -> dict:
    relation = lambda x, y: "STANCE_MAINTAINED" if x == y else "STANCE_REVERSED"
    before = collections.Counter(relation(r["stance_x"], r["stance_y"]) for r in rows)
    after = collections.Counter(relation(r["stance_x"], r["aligned_stance_y"]) for r in rows)
    flipped = [{"pair_id": r["pair_id"], "model": r["model"], "proposition_a": r["proposition_x"],
                "proposition_b": r["proposition_y"],
                "relation_before": relation(r["stance_x"], r["stance_y"]),
                "relation_after": relation(r["stance_x"], r["aligned_stance_y"])}
               for r in rows if r["consensus_relation"] == "OPPOSITE_POLARITY"]
    return {"n_pairs": len(rows), "relation_before": dict(before), "relation_after_alignment": dict(after),
            "judged_same_proposition_but_DIFFERENT": sum(r["consensus_relation"] == "DIFFERENT" for r in rows),
            "opposite_polarity_pairs": flipped}


def judge_agreement(rows: list[dict]) -> dict:
    return categorical_agreement([r[f"relation_{_short(JUDGES[0])}"] for r in rows],
                                 [r[f"relation_{_short(JUDGES[1])}"] for r in rows])


def _short(model: str) -> str:
    return model.split("/")[-1]


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------

def unique_proposition_pairs(items: list[dict]) -> dict[str, tuple[str, str]]:
    return {judgment_key(i["proposition_x"], i["proposition_y"]): (i["proposition_x"], i["proposition_y"])
            for i in items}


def dry_run(root: Path, items: list[dict]) -> dict:
    unique = unique_proposition_pairs(items)
    plan = {}
    for judge in JUDGES:
        tokens_in = sum(estimate_tokens(render(root, x, y)) for x, y in unique.values())
        tokens_out = 80 * len(unique)
        plan[judge] = {"calls": len(unique), "input_tokens": tokens_in, "output_tokens": tokens_out,
                       "cost_usd": round(estimate_cost(judge, tokens_in, tokens_out), 4)}
    return {"mode": "DRY_RUN_NO_REQUESTS_SENT",
            "items_by_source": dict(collections.Counter(i["source"] for i in items)),
            "unique_proposition_pairs": len(unique), "judges": plan,
            "total_calls": sum(p["calls"] for p in plan.values()),
            "total_cost_usd": round(sum(p["cost_usd"] for p in plan.values()), 4)}


def run(root: Path, execute: bool) -> dict:
    items = collect_items(root)
    if not execute:
        return dry_run(root, items)
    out = root / OUT_DIR
    out.mkdir(parents=True, exist_ok=True)
    tasks = [(judge, key, prop_x, prop_y)
             for key, (prop_x, prop_y) in unique_proposition_pairs(items).items() for judge in JUDGES]

    def judge_one(task: tuple[str, str, str, str]) -> dict:
        judge, key, prop_x, prop_y = task
        raw = cached_call(root, "canonicalize", judge, key, render(root, prop_x, prop_y), execute)
        return parse_judgment(completion_text(raw))

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        judgments = {(t[0], t[1]): result for t, result in zip(tasks, pool.map(judge_one, tasks))}

    rows = []
    for item in items:
        key = judgment_key(item["proposition_x"], item["proposition_y"])
        per_judge = {f"relation_{_short(j)}": judgments[(j, key)]["relation"] for j in JUDGES}
        consensus = consensus_relation(list(per_judge.values()))
        rows.append({**item, **per_judge, "consensus_relation": consensus,
                     "aligned_stance_y": aligned_stance_y(item, consensus),
                     "malformed_any_judge": any(judgments[(j, key)]["malformed_output"] for j in JUDGES),
                     "label_source": "MODEL_JUDGMENT"})
    write_csv(out / "canonicalization_items.csv", rows, list(rows[0]))

    by_source = collections.defaultdict(list)
    for row in rows:
        by_source[row["source"]].append(row)
    summary = {
        "experiment_version": EXPERIMENT_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "judges": JUDGES, "prompt_sha256": prompt_sha256(root / PROMPT_PATH), "git_commit": _git_commit(root),
        "flip_rule": "stance_y flipped only when every judge says OPPOSITE_POLARITY",
        "expansion_side_realignment": "expansion model predictions realigned from annotator-1 display order to chronological gold sides",
        "judge_agreement_all_items": judge_agreement(rows),
        "malformed_output_count": sum(r["malformed_any_judge"] for r in rows),
        "cross_source": {s: source_metrics(r) for s, r in sorted(by_source.items()) if not s.startswith("within_pair")},
        "within_pair": {s: within_pair_metrics(r) for s, r in sorted(by_source.items()) if s.startswith("within_pair")},
    }
    (out / "canonicalization_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--execute", action="store_true", help="send real API requests (default: dry-run)")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    print(json.dumps(run(root, args.execute), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
