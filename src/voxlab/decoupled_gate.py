"""Decoupled comparability gate, and larger models on the same benchmark.

The stress test and gate v2 showed that when one call reads both speeches,
a change of stance leaks into the comparability decision. The decoupled gate
separates the two:

  extraction  one call per side, seeing only that speech: determinability,
              a neutral yes/no target question, and the answer (stance).
  comparison  one call per pair, seeing only the two questions, never the
              speeches or the answers: EQUIVALENT / OPPOSITE_POLARITY /
              DIFFERENT / UNCERTAIN. OPPOSITE_POLARITY counts as the same
              question with side b's stance flipped (question canonicalization).

The relation is then derived by agreement.derive_relation, unchanged.

Conditions reported per model:
  A_end_to_end, B_forced_comparability, C_structured_with_gate   v1 prompts
  D_decoupled_gate, D_forced_comparability                       this module
For the two v1 models, A and C come from the cached v1 runs; larger models
run the frozen v1 prompts here, on the same items, in chronological order.

Items: the 47 human-gold pairs (dev = pilot, test = expansion) and the 39
accepted counterfactuals. Nothing is tuned here: prompts are v1 and were
written before any decoupled call.

A spending cap stops the run once the real cost of new calls exceeds it.

    PYTHONPATH=src python3 -m voxlab.decoupled_gate                          # dry-run
    PYTHONPATH=src python3 -m voxlab.decoupled_gate --execute --max-cost 6
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from .agreement import derive_relation
from .audit import write_csv
from .automatic_baselines import (
    END_TO_END_PROMPT_PATH, STRUCTURED_PROMPT_PATH, _extract_json, _git_commit, comparability_metrics,
    parse_end_to_end, parse_structured, prompt_sha256, relation_metrics, relation_with_gate,
    relation_without_gate, render_prompt,
)
from .llm_client import chat_completion
from .question_gate import natural_items, synthetic_items, v1_natural_predictions, v1_synthetic_predictions
from .synthetic_stress import (
    CHARS_PER_TOKEN, EVALUATED_MODELS, MAX_WORKERS, PRICES, SEED, TEMPERATURE, _slug, headline, load_gold,
    summarize,
)

EXPERIMENT_VERSION = "decoupled_gate_v1"
V1_MODELS = list(EVALUATED_MODELS)
BIG_MODELS = ["zai-org/GLM-5.2", "nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B", "openai/gpt-oss-120b"]
BIG_PRICES = {  # DeepInfra listing, 2026-09-28
    "zai-org/GLM-5.2": (0.75, 2.40),
    "nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B": (0.50, 2.20),
    "openai/gpt-oss-120b": (0.037, 0.17),
}
REASONING_OUTPUT_TOKENS = 1500  # dry-run assumption for reasoning models, per call
REASONING_MAX_TOKENS = 16384
EXTRACT_PROMPT_PATH = Path("prompts/decoupled_extract_v1.txt")
COMPARE_PROMPT_PATH = Path("prompts/decoupled_compare_v1.txt")
RAW_SUBDIR = Path("data/processed/llm_raw_outputs/decoupled")
OUT_DIR = Path("data/processed/decoupled_gate")
DEFAULT_MAX_COST = 6.0

DETERMINABILITY = {"YES", "NO", "UNCERTAIN"}
STANCES = {"FAVOR", "AGAINST", "UNCERTAIN"}
COMPARE_LABELS = {"EQUIVALENT", "OPPOSITE_POLARITY", "DIFFERENT", "UNCERTAIN"}
FLIP = {"FAVOR": "AGAINST", "AGAINST": "FAVOR", "UNCERTAIN": "UNCERTAIN"}
CONDITIONS = ("A_end_to_end", "B_forced_comparability", "C_structured_with_gate",
              "D_decoupled_gate", "D_forced_comparability")


class BudgetExceeded(RuntimeError):
    pass


def price(model: str) -> tuple[float, float]:
    return BIG_PRICES.get(model) or PRICES[model]


def is_big(model: str) -> bool:
    return model in BIG_MODELS


# --------------------------------------------------------------------------
# Cost-capped cached calls
# --------------------------------------------------------------------------

class Caller:
    """Cached calls; new calls add their real cost and stop past the cap."""

    def __init__(self, root: Path, execute: bool, max_cost: float):
        self.root, self.execute, self.max_cost = root, execute, max_cost
        self.spent, self.new_calls = 0.0, 0
        self.lock = threading.Lock()

    def path(self, stage: str, model: str, key: str) -> Path:
        return self.root / RAW_SUBDIR / f"{stage}_{_slug(model)}_{key}.json"

    def call(self, stage: str, model: str, key: str, prompt: str) -> dict | None:
        path = self.path(stage, model, key)
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        if not self.execute:
            return None
        with self.lock:
            if self.spent >= self.max_cost:
                raise BudgetExceeded(f"cap US$ {self.max_cost} reached (spent US$ {self.spent:.4f})")
        big = is_big(model)
        response = chat_completion(self.root, model, [{"role": "user", "content": prompt}],
                                   temperature=TEMPERATURE, seed=SEED,
                                   max_tokens=REASONING_MAX_TOKENS if big else None,
                                   timeout=900 if big else 180)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(response, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        with self.lock:
            self.spent += float((response.get("usage") or {}).get("estimated_cost") or 0.0)
            self.new_calls += 1
        return response


def content(response: dict) -> str:
    """Final answer text; reasoning models may return None when they run out of tokens."""
    return (response["choices"][0]["message"].get("content") or "") if response else ""


# --------------------------------------------------------------------------
# Decoupled gate
# --------------------------------------------------------------------------

def side_record(pair: dict, side: str) -> dict:
    return {"event": pair.get(f"event_{side}", ""), "date": pair.get(f"date_{side}", ""),
            "topic": pair.get(f"topic_{side}", ""), "text": pair.get(f"text_{side}", "")}


def side_key(side: dict) -> str:
    payload = json.dumps(side, ensure_ascii=False, sort_keys=True)
    return "side_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def question_key(question_x: str, question_y: str) -> str:
    return "q_" + hashlib.sha256(f"{question_x}\x1f{question_y}".encode("utf-8")).hexdigest()[:16]


def render_extract(root: Path, side: dict) -> str:
    return (root / EXTRACT_PROMPT_PATH).read_text(encoding="utf-8").format(**side)


def render_compare(root: Path, question_x: str, question_y: str) -> str:
    return (root / COMPARE_PROMPT_PATH).read_text(encoding="utf-8").format(
        question_x=question_x, question_y=question_y)


def parse_extraction(raw_text: str) -> dict:
    parsed = _extract_json(raw_text)
    if not isinstance(parsed, dict):
        return {"determinable": "UNCERTAIN", "question": "", "stance": "UNCERTAIN", "malformed": True}
    det = parsed.get("stance_determinable", "")
    stance = parsed.get("stance", "")
    malformed = det not in DETERMINABILITY
    if det == "YES" and stance not in STANCES:
        malformed = True
    if det != "YES" and stance not in STANCES | {""}:
        malformed = True
    return {"determinable": det if det in DETERMINABILITY else "UNCERTAIN",
            "question": str(parsed.get("target_question", "")).strip(),
            "stance": stance if stance in STANCES else "UNCERTAIN", "malformed": malformed}


def parse_comparison(raw_text: str) -> dict:
    parsed = _extract_json(raw_text)
    value = parsed.get("relation", "") if isinstance(parsed, dict) else ""
    return {"relation": value if value in COMPARE_LABELS else "UNCERTAIN", "malformed": value not in COMPARE_LABELS}


def comparison_to_gate(relation: str, stance_b: str) -> tuple[str, str]:
    """(same_proposition, stance_b aligned to question a)."""
    if relation == "EQUIVALENT":
        return "YES", stance_b
    if relation == "OPPOSITE_POLARITY":
        return "YES", FLIP.get(stance_b, stance_b)
    if relation == "DIFFERENT":
        return "NO", stance_b
    return "UNCERTAIN", stance_b


def decoupled_relation(ext_a: dict, ext_b: dict, comparison: dict | None) -> dict:
    forced = derive_relation(ext_a["determinable"], ext_b["determinable"], "YES", ext_a["stance"], ext_b["stance"])
    if comparison is None:  # a side is not determinable: the comparison is never needed
        gated = derive_relation(ext_a["determinable"], ext_b["determinable"], "UNCERTAIN",
                                ext_a["stance"], ext_b["stance"])
        return {"D_decoupled_gate": gated, "D_forced_comparability": forced,
                "D_same_proposition": "", "D_compare_relation": ""}
    same, aligned_b = comparison_to_gate(comparison["relation"], ext_b["stance"])
    gated = derive_relation(ext_a["determinable"], ext_b["determinable"], same, ext_a["stance"], aligned_b)
    return {"D_decoupled_gate": gated, "D_forced_comparability": forced,
            "D_same_proposition": same, "D_compare_relation": comparison["relation"]}


def needs_comparison(ext_a: dict, ext_b: dict) -> bool:
    return ext_a["determinable"] == "YES" and ext_b["determinable"] == "YES" and ext_a["question"] and ext_b["question"]


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------

def load_items(root: Path) -> list[dict]:
    gold = load_gold(root)
    items = []
    for split, gold_round in (("dev", "pilot"), ("test", "expansion")):
        for item in natural_items(gold, gold_round) + synthetic_items(root, gold, gold_round):
            items.append({**item, "split": split})
    return items


def run_v1_for_big(caller: Caller, model: str, pair: dict) -> dict:
    e2e = caller.call("bigv1_end_to_end", model, pair["pair_id"], render_prompt(caller.root / END_TO_END_PROMPT_PATH, pair))
    struct = caller.call("bigv1_structured", model, pair["pair_id"], render_prompt(caller.root / STRUCTURED_PROMPT_PATH, pair))
    if e2e is None or struct is None:
        return {}
    a, s = parse_end_to_end(content(e2e)), parse_structured(content(struct))
    return {"A_end_to_end": a["relation_normalized"], "B_forced_comparability": relation_without_gate(s),
            "C_structured_with_gate": relation_with_gate(s), "C_same_proposition": s["same_proposition_normalized"],
            "v1_malformed": a["malformed_output"] or s["malformed_output"]}


def evaluate_model(caller: Caller, model: str, items: list[dict]) -> list[dict]:
    root = caller.root
    sides = {}
    for item in items:
        for side in "ab":
            record = side_record(item["pair"], side)
            sides[side_key(record)] = record
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        keys = list(sides)
        raws = list(pool.map(lambda k: caller.call("extract", model, k, render_extract(root, sides[k])), keys))
    extractions = {k: parse_extraction(content(r)) if r else None for k, r in zip(keys, raws)}

    def per_item(item: dict) -> dict:
        ext_a = extractions[side_key(side_record(item["pair"], "a"))]
        ext_b = extractions[side_key(side_record(item["pair"], "b"))]
        row = {"item_id": item["item_id"], "kind": item["kind"], "split": item["split"],
               "source_pair_id": item["source_pair_id"], "model": model,
               "gold_relation": item.get("gold_relation", ""),
               "gold_same_proposition": item.get("gold_same_proposition", ""),
               "operation": item.get("operation", ""), "expected_relation": item.get("expected_relation", "")}
        if ext_a is None or ext_b is None:
            return row
        comparison = None
        if needs_comparison(ext_a, ext_b):
            raw = caller.call("compare", model, question_key(ext_a["question"], ext_b["question"]),
                              render_compare(root, ext_a["question"], ext_b["question"]))
            if raw is None:
                return row
            comparison = parse_comparison(content(raw))
        row.update(decoupled_relation(ext_a, ext_b, comparison))
        row.update({"question_a": ext_a["question"], "question_b": ext_b["question"],
                    "stance_a": ext_a["stance"], "stance_b": ext_b["stance"],
                    "D_malformed": ext_a["malformed"] or ext_b["malformed"] or bool(comparison and comparison["malformed"])})
        if is_big(model):
            row.update(run_v1_for_big(caller, model, item["pair"]))
        return row

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        return list(pool.map(per_item, items))


def attach_v1_references(root: Path, rows: list[dict]) -> None:
    """A and C of the two v1 models, from their cached runs (no calls)."""
    nat, syn = v1_natural_predictions(root), v1_synthetic_predictions(root)
    pairwise = {(r["model"], r["pair_id"]): r["same_proposition"] for r in
                __import__("csv").DictReader(open(root / "data/processed/gold18_pairwise_analysis.csv", encoding="utf-8"))}
    for r in __import__("csv").DictReader(open(root / "data/processed/expansion29_model_predictions.csv", encoding="utf-8")):
        pairwise[(r["model"], r["pair_id"])] = r["same_proposition"]
    stress_b = {(r["model"], r["spec_id"]): r["B_forced_comparability"] for r in
                __import__("csv").DictReader(open(root / "data/processed/stress/stress_predictions.csv", encoding="utf-8"))}
    for row in rows:
        if is_big(row["model"]):
            continue
        key = (row["model"], row["item_id"])
        ref = nat.get(key) if row["kind"] == "natural" else syn.get(key)
        if ref:
            row["A_end_to_end"] = ref["v1_A_end_to_end"]
            row["C_structured_with_gate"] = ref["v1_C_structured_with_gate"]
        if row["kind"] == "synthetic" and key in stress_b:
            row["B_forced_comparability"] = stress_b[key]
        if row["kind"] == "natural":
            row["C_same_proposition"] = pairwise.get(key, "")


def natural_metrics(rows: list[dict]) -> dict:
    out = {}
    for model in sorted({r["model"] for r in rows}):
        out[model] = {}
        for split in ("dev", "test", "all"):
            mine = [r for r in rows if r["model"] == model and r["kind"] == "natural" and split in ("all", r["split"])]
            gold = [r["gold_relation"] for r in mine]
            entry = {"n": len(mine), "relation": {}}
            for condition in ("A_end_to_end", "C_structured_with_gate", "D_decoupled_gate"):
                preds = [r.get(condition, "") for r in mine]
                if all(preds):
                    m = relation_metrics(preds, gold)
                    entry["relation"][condition] = {k: m[k] for k in ("accuracy", "macro_f1", "false_reversal_count")}
            for condition, field in (("C", "C_same_proposition"), ("D", "D_same_proposition")):
                entry[f"comparability_{condition}"] = comparability_metrics(
                    [r.get(field) or "UNCERTAIN" for r in mine], [r["gold_same_proposition"] for r in mine])
            out[model][split] = entry
    return out


def dry_run(root: Path, items: list[dict], models: list[str]) -> dict:
    sides = {side_key(side_record(i["pair"], s)): side_record(i["pair"], s) for i in items for s in "ab"}
    extract_tokens = sum(len(render_extract(root, s)) for s in sides.values()) / CHARS_PER_TOKEN
    v1_tokens = sum(len(render_prompt(root / END_TO_END_PROMPT_PATH, i["pair"])) +
                    len(render_prompt(root / STRUCTURED_PROMPT_PATH, i["pair"])) for i in items) / CHARS_PER_TOKEN
    plan, total = {}, 0.0
    for model in models:
        p_in, p_out = price(model)
        out_per_call = REASONING_OUTPUT_TOKENS if is_big(model) else 150
        calls = len(sides) + len(items)  # extraction + upper bound on comparisons
        tokens_in = extract_tokens + 150 * len(items)
        if is_big(model):
            calls += 2 * len(items)
            tokens_in += v1_tokens
        tokens_out = calls * out_per_call
        cost = (tokens_in * p_in + tokens_out * p_out) / 1e6
        plan[model] = {"calls_upper_bound": calls, "input_tokens": int(tokens_in), "output_tokens": tokens_out,
                       "cost_usd": round(cost, 3)}
        total += cost
    return {"mode": "DRY_RUN_NO_REQUESTS_SENT", "items": dict(collections.Counter(i["kind"] for i in items)),
            "distinct_sides": len(sides), "models": plan,
            "total_calls_upper_bound": sum(p["calls_upper_bound"] for p in plan.values()),
            "total_cost_usd_estimate": round(total, 3)}


def run(root: Path, execute: bool, max_cost: float, models: list[str]) -> dict:
    items = load_items(root)
    if not execute:
        return dry_run(root, items, models)
    caller = Caller(root, execute, max_cost)
    rows, stopped = [], ""
    for model in models:
        try:
            rows.extend(evaluate_model(caller, model, items))
        except BudgetExceeded as exc:
            stopped = f"{model}: {exc}"
            break
    attach_v1_references(root, rows)
    out = root / OUT_DIR
    out.mkdir(parents=True, exist_ok=True)
    fields = sorted({k for r in rows for k in r}, key=lambda k: (k not in ("item_id", "model", "kind", "split"), k))
    write_csv(out / "decoupled_gate_predictions.csv", rows, fields)
    synthetic = [r for r in rows if r["kind"] == "synthetic" and r.get("D_decoupled_gate")]
    result = {
        "experiment_version": EXPERIMENT_VERSION, "timestamp": datetime.now(timezone.utc).isoformat(),
        "models": models, "stopped_early": stopped,
        "new_calls": caller.new_calls, "new_cost_usd": round(caller.spent, 4),
        "prompt_sha256": {str(p): prompt_sha256(root / p) for p in (EXTRACT_PROMPT_PATH, COMPARE_PROMPT_PATH,
                                                                    END_TO_END_PROMPT_PATH, STRUCTURED_PROMPT_PATH)},
        "git_commit": _git_commit(root),
        "malformed": {m: {"decoupled": sum(bool(r.get("D_malformed")) for r in rows if r["model"] == m),
                          "v1": sum(bool(r.get("v1_malformed")) for r in rows if r["model"] == m)} for m in models},
        "natural": natural_metrics([r for r in rows if r.get("D_decoupled_gate")]),
        "synthetic_headline": {split: headline(summarize([r for r in synthetic if split in ("all", r["split"])],
                                                         CONDITIONS), CONDITIONS)
                               for split in ("dev", "test", "all")},
    }
    (out / "decoupled_gate_metrics.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                                                     encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--execute", action="store_true", help="send real API requests (default: dry-run)")
    parser.add_argument("--max-cost", type=float, default=DEFAULT_MAX_COST, help="stop after this real spend (USD)")
    parser.add_argument("--models", nargs="+", default=V1_MODELS + BIG_MODELS)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    result = run(root, args.execute, args.max_cost, args.models)
    print(json.dumps({k: v for k, v in result.items() if k not in ("natural", "synthetic_headline")}
                     if args.execute else result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
