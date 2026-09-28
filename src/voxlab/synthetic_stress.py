"""Synthetic counterfactual stress test for the comparability gate.

The human gold (18 pilot + 29 expansion pairs) has no STANCE_REVERSED
example, so reversal recall and the gate's effect on false reversals cannot
be measured on natural data. This module builds controlled counterfactuals
from the gold pairs, without new human annotation:

  REVERSE_ON_COMPARABLE    gold STANCE_MAINTAINED; side b is rewritten to the
                           opposite stance on the same proposition.
                           Expected relation: STANCE_REVERSED.
  NEGATED_PARAPHRASE       gold STANCE_MAINTAINED; side b keeps its stance but
                           is phrased with opposite linguistic polarity.
                           Expected relation: STANCE_MAINTAINED.
  SHIFT_PROPOSITION        gold STANCE_MAINTAINED; side b is moved to a
                           different proposition within the same theme.
                           Expected relation: INCOMPARABLE.
  REVERSE_ON_INCOMPARABLE  gold INCOMPARABLE; side b is rewritten to the
                           opposite stance on its own proposition.
                           Expected relation: INCOMPARABLE.

The expected relation comes from the operation applied to a human-labeled
pair, not from a new human judgment. Every rewrite is produced by a generator
model and audited by a different verifier model plus deterministic edit
checks; only accepted rewrites are evaluated. The evaluated models run the
frozen v1 prompts of automatic_baselines unchanged. All labels here are
SYNTHETIC_EXPECTED, never HUMAN_CONSENSUS.

Network calls are dry-run by default: without --execute the command prints
the call plan and the estimated cost and sends nothing.

    PYTHONPATH=src python3 -m voxlab.synthetic_stress            # dry-run
    PYTHONPATH=src python3 -m voxlab.synthetic_stress --execute  # real calls
"""

from __future__ import annotations

import argparse
import collections
import difflib
import hashlib
import json
import math
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from .audit import write_csv
from .automatic_baselines import (
    END_TO_END_PROMPT_PATH, STRUCTURED_PROMPT_PATH, _extract_json, _git_commit,
    parse_end_to_end, parse_structured, prompt_sha256, relation_with_gate, relation_without_gate,
    render_prompt,
)
from .llm_client import chat_completion, completion_text
from .semantic_pilot import DISPLAY_FIELDS, read_csv

EXPERIMENT_VERSION = "synthetic_stress_v1"
GENERATOR_MODEL = "deepseek-ai/DeepSeek-V3.1"
VERIFIER_MODEL = "Qwen/Qwen3-235B-A22B-Instruct-2507"
EVALUATED_MODELS = ["Qwen/Qwen2.5-72B-Instruct", "meta-llama/Llama-3.3-70B-Instruct-Turbo"]
TEMPERATURE = 0.0
SEED = 20260928

GENERATE_PROMPT_PATH = Path("prompts/stress_generate_v1.txt")
VERIFY_PROMPT_PATH = Path("prompts/stress_verify_v1.txt")
GOLD_PATHS = (Path("data/annotations/semantic_pilot_gold.csv"),
              Path("data/annotations/expansion_semantic_gold.csv"))
OUT_DIR = Path("data/processed/stress")
RAW_SUBDIR = "stress"

# USD per million tokens (input, output), from the DeepInfra model listing
# checked on 2026-09-28. Used only for dry-run estimates.
PRICES = {
    "Qwen/Qwen2.5-72B-Instruct": (0.36, 0.40),
    "meta-llama/Llama-3.3-70B-Instruct-Turbo": (0.10, 0.32),
    GENERATOR_MODEL: (0.25, 0.95),
    VERIFIER_MODEL: (0.09, 0.55),
}
CHARS_PER_TOKEN = 3.5
MAX_WORKERS = 8

DETERMINATE = {"FAVOR", "AGAINST"}
OPPOSITE = {"FAVOR": "AGAINST", "AGAINST": "FAVOR"}
VERIFY_YES_FIELDS = ("operation_achieved", "other_content_preserved", "internally_consistent", "natural")
VERIFY_STANCE_LABELS = {"FAVOR", "AGAINST", "NOT_ADDRESSED", "UNCERTAIN"}

# Deterministic edit-locality bounds (word-level SequenceMatcher ratio and
# length ratio). They reject rewrites that change nothing or rewrite
# everything; they were fixed before any generation.
MIN_WORD_SIMILARITY = 0.50
MAX_WORD_SIMILARITY = 0.995
MIN_LENGTH_RATIO = 0.60
MAX_LENGTH_RATIO = 1.50

REVERSE_INSTRUCTION = (
    "Inverta a posição da fala em relação à proposição-alvo. A fala original é {original_stance}; "
    "a reescrita deve ser claramente {expected_stance} à MESMA proposição-alvo, com argumentos "
    "compatíveis com essa nova posição. Não mude a proposição-alvo nem o tema."
)
OPERATIONS = {
    "REVERSE_ON_COMPARABLE": {
        "source_relation": "STANCE_MAINTAINED",
        "expected_relation": "STANCE_REVERSED",
        "instruction": REVERSE_INSTRUCTION,
        "expected_stance_on_target": "opposite",
    },
    "NEGATED_PARAPHRASE": {
        "source_relation": "STANCE_MAINTAINED",
        "expected_relation": "STANCE_MAINTAINED",
        "instruction": (
            "Mantenha exatamente a mesma posição ({original_stance}) em relação à proposição-alvo, mas "
            "reformule as frases que expressam essa posição com polaridade linguística oposta: por "
            "exemplo, trocar 'devemos manter X' por 'não podemos acabar com X', ou 'apoio X' por 'não "
            "posso aceitar que X seja abandonado'. A posição real sobre a proposição-alvo não pode mudar."
        ),
        "expected_stance_on_target": "same",
    },
    "SHIFT_PROPOSITION": {
        "source_relation": "STANCE_MAINTAINED",
        "expected_relation": "INCOMPARABLE",
        "instruction": (
            "Faça a fala tomar posição sobre uma proposição DIFERENTE da proposição-alvo, dentro do mesmo "
            "tema geral e reaproveitando o mesmo vocabulário. Mude um destes elementos: o instrumento ou "
            "medida, a população afetada, o objeto avaliado, ou o escopo (nacional versus local). A posição "
            "sobre a nova proposição não pode determinar a posição sobre a proposição-alvo, e a fala "
            "reescrita não deve mais tomar posição sobre a proposição-alvo original nem sobre a proposição "
            "de referência do outro evento."
        ),
        "expected_stance_on_target": "NOT_ADDRESSED",
    },
    "REVERSE_ON_INCOMPARABLE": {
        "source_relation": "INCOMPARABLE",
        "expected_relation": "INCOMPARABLE",
        "instruction": REVERSE_INSTRUCTION,
        "expected_stance_on_target": "opposite",
    },
}
CONDITIONS = ("A_end_to_end", "B_forced_comparability", "C_structured_with_gate")


# --------------------------------------------------------------------------
# Plan
# --------------------------------------------------------------------------

def load_gold(root: Path) -> list[dict[str, str]]:
    rows = []
    for path in GOLD_PATHS:
        for row in read_csv(root / path):
            if row.get("label_source") != "HUMAN_CONSENSUS":
                raise ValueError(f"{path} must be HUMAN_CONSENSUS gold")
            rows.append({**row, "gold_round": "pilot" if "pilot" in path.name else "expansion"})
    ids = [row["pair_id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate pair IDs across gold files")
    return rows


def spec_id(pair_id: str, operation: str) -> str:
    return "syn_" + hashlib.sha256(f"{pair_id}|{operation}".encode()).hexdigest()[:12]


def instruction_text(operation: str, original_stance: str) -> str:
    return OPERATIONS[operation]["instruction"].format(
        original_stance=original_stance, expected_stance=OPPOSITE.get(original_stance, ""))


def expected_verifier_stance(operation: str, original_stance: str) -> str:
    rule = OPERATIONS[operation]["expected_stance_on_target"]
    if rule == "opposite":
        return OPPOSITE[original_stance]
    if rule == "same":
        return original_stance
    return rule


def build_plan(gold_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """One spec per (eligible gold pair, operation); always rewrites side b."""
    plan = []
    for row in sorted(gold_rows, key=lambda r: r["pair_id"]):
        stance_b = row["stance_b"]
        if stance_b not in DETERMINATE or not row["target_proposition_b"].strip():
            continue
        for operation, config in OPERATIONS.items():
            if row["derived_relation"] != config["source_relation"]:
                continue
            plan.append({
                "spec_id": spec_id(row["pair_id"], operation),
                "source_pair_id": row["pair_id"],
                "gold_round": row["gold_round"],
                "operation": operation,
                "source_relation": row["derived_relation"],
                "expected_relation": config["expected_relation"],
                "target_proposition_a": row["target_proposition_a"],
                "target_proposition_b": row["target_proposition_b"],
                "original_stance_b": stance_b,
                "expected_verifier_stance": expected_verifier_stance(operation, stance_b),
                "label_source": "SYNTHETIC_EXPECTED",
            })
    return plan


# --------------------------------------------------------------------------
# Cached calls: a raw response on disk is reused verbatim and never re-billed.
# --------------------------------------------------------------------------

def _slug(model: str) -> str:
    return model.replace("/", "_")


def raw_path(root: Path, stage: str, model: str, key: str) -> Path:
    return root / "data" / "processed" / "llm_raw_outputs" / RAW_SUBDIR / f"{stage}_{_slug(model)}_{key}.json"


def cached_call(root: Path, stage: str, model: str, key: str, prompt: str, execute: bool,
                max_tokens: int | None = None) -> dict | None:
    """Return the raw response, or None when uncached and execute is False."""
    path = raw_path(root, stage, model, key)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    if not execute:
        return None
    response = chat_completion(root, model, [{"role": "user", "content": prompt}],
                               temperature=TEMPERATURE, seed=SEED, max_tokens=max_tokens,
                               timeout=900 if max_tokens else 180)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(response, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return response


def estimate_tokens(text: str) -> int:
    return math.ceil(len(text) / CHARS_PER_TOKEN)


def generation_max_tokens(text: str) -> int:
    """Room for a full rewrite of the speech plus the two header lines."""
    return 2 * estimate_tokens(text) + 512


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    price_in, price_out = PRICES[model]
    return (input_tokens * price_in + output_tokens * price_out) / 1_000_000


# --------------------------------------------------------------------------
# Generation
# --------------------------------------------------------------------------

GENERATION_PATTERN = re.compile(
    r"PROPOSICAO_RESULTANTE:\s*(?P<prop>.*?)\s*\n\s*POSICAO_RESULTANTE:\s*(?P<stance>\S+)\s*\n"
    r"\s*===TEXTO===\s*\n(?P<text>.*?)\n\s*===FIM===",
    re.DOTALL,
)


def render_generation_prompt(root: Path, spec: dict[str, str], text_b: str) -> str:
    template = (root / GENERATE_PROMPT_PATH).read_text(encoding="utf-8")
    return template.format(
        target_proposition=spec["target_proposition_b"], original_stance=spec["original_stance_b"],
        operation_instruction=instruction_text(spec["operation"], spec["original_stance_b"]), text=text_b)


def parse_generation(raw_text: str) -> dict:
    match = GENERATION_PATTERN.search(raw_text or "")
    if not match:
        return {"generation_parsed": False, "resulting_proposition": "", "resulting_stance": "",
                "rewritten_text": ""}
    return {"generation_parsed": True, "resulting_proposition": match["prop"].strip(),
            "resulting_stance": match["stance"].strip().upper(),
            "rewritten_text": match["text"].strip("\n")}


def word_similarity(original: str, rewritten: str) -> float:
    return difflib.SequenceMatcher(None, original.split(), rewritten.split(), autojunk=False).ratio()


COPY_NOISE_PARAGRAPH_RATIO = 0.985


def copy_noise_paragraphs(original: str, rewritten: str) -> int:
    """Paragraphs changed only marginally (typo-like copy errors), a post-hoc diagnostic.

    Not an acceptance criterion: it was added after the run, when inspection
    showed the generator occasionally corrupting words while copying long
    speeches. Used only for the sensitivity analysis.
    """
    old = [p for p in original.split("\n") if p.strip()]
    new = [p for p in rewritten.split("\n") if p.strip()]
    noisy = 0
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        for before, after in zip(old[i1:i2], new[j1:j2]):
            if difflib.SequenceMatcher(None, before, after, autojunk=False).ratio() > COPY_NOISE_PARAGRAPH_RATIO:
                noisy += 1
    return noisy


def deterministic_checks(original: str, rewritten: str) -> dict:
    if not rewritten.strip():
        return {"word_similarity": 0.0, "length_ratio": 0.0, "deterministic_ok": False,
                "deterministic_failures": "EMPTY_REWRITE"}
    similarity = word_similarity(original, rewritten)
    length_ratio = len(rewritten) / max(len(original), 1)
    failures = []
    if similarity < MIN_WORD_SIMILARITY:
        failures.append("TOO_MUCH_REWRITTEN")
    if similarity > MAX_WORD_SIMILARITY:
        failures.append("NOTHING_CHANGED")
    if not MIN_LENGTH_RATIO <= length_ratio <= MAX_LENGTH_RATIO:
        failures.append("LENGTH_OUT_OF_BOUNDS")
    if re.search(r"===|\[(?:alterad|reescrit|edit)", rewritten, re.IGNORECASE):
        failures.append("EDIT_MARKERS")
    return {"word_similarity": round(similarity, 4), "length_ratio": round(length_ratio, 4),
            "deterministic_ok": not failures, "deterministic_failures": "|".join(failures)}


# --------------------------------------------------------------------------
# Verification
# --------------------------------------------------------------------------

def render_verification_prompt(root: Path, spec: dict[str, str], original: str, rewritten: str) -> str:
    template = (root / VERIFY_PROMPT_PATH).read_text(encoding="utf-8")
    reference = spec["target_proposition_a"] if spec["operation"] == "SHIFT_PROPOSITION" else "(não se aplica)"
    return template.format(
        target_proposition=spec["target_proposition_b"], original_stance=spec["original_stance_b"],
        reference_proposition=reference,
        operation_instruction=instruction_text(spec["operation"], spec["original_stance_b"]),
        original_text=original, rewritten_text=rewritten)


def parse_verification(raw_text: str) -> dict:
    parsed = _extract_json(raw_text or "")
    result = {"verification_malformed": False}
    if not isinstance(parsed, dict):
        parsed = {}
        result["verification_malformed"] = True
    for field in VERIFY_YES_FIELDS:
        value = parsed.get(field, "")
        if value not in {"YES", "NO", "UNCERTAIN"}:
            result["verification_malformed"] = True
        result[field] = value
    stance = parsed.get("rewritten_stance_on_original_target", "")
    if stance not in VERIFY_STANCE_LABELS:
        result["verification_malformed"] = True
    result["rewritten_stance_on_original_target"] = stance
    result["verification_reasoning"] = parsed.get("reasoning", "")
    return result


def accept(spec: dict[str, str], generation: dict, checks: dict, verification: dict) -> tuple[bool, str]:
    """A rewrite is evaluated only when every automatic check passes."""
    reasons = []
    if not generation["generation_parsed"]:
        reasons.append("GENERATION_UNPARSEABLE")
    if not checks["deterministic_ok"]:
        reasons.append("DETERMINISTIC:" + checks["deterministic_failures"])
    if verification.get("verification_malformed", True):
        reasons.append("VERIFICATION_MALFORMED")
    for field in VERIFY_YES_FIELDS:
        if verification.get(field) != "YES":
            reasons.append(f"VERIFIER_{field.upper()}_{verification.get(field) or 'MISSING'}")
    if verification.get("rewritten_stance_on_original_target") != spec["expected_verifier_stance"]:
        reasons.append("VERIFIER_STANCE_MISMATCH")
    return not reasons, "|".join(reasons)


# --------------------------------------------------------------------------
# Evaluation with the frozen v1 prompts
# --------------------------------------------------------------------------

def perturbed_pair(gold_row: dict[str, str], spec: dict[str, str], rewritten: str) -> dict[str, str]:
    """Blind display record: only the frozen display fields, side b replaced.

    Evidence/context fields of side b are blanked because they quote the
    original speech; the frozen prompts do not read them either way.
    """
    pair = {field: gold_row.get(field, "") for field in DISPLAY_FIELDS}
    pair.update({"pair_id": spec["spec_id"], "text_b": rewritten, "evidence_b": "",
                 "context_before_b": "", "context_after_b": "", "blinding_warning": ""})
    return pair


def predict(root: Path, pair: dict[str, str], model: str, execute: bool) -> dict | None:
    e2e_raw = cached_call(root, "eval_end_to_end", model, pair["pair_id"],
                          render_prompt(root / END_TO_END_PROMPT_PATH, pair), execute)
    struct_raw = cached_call(root, "eval_structured", model, pair["pair_id"],
                             render_prompt(root / STRUCTURED_PROMPT_PATH, pair), execute)
    if e2e_raw is None or struct_raw is None:
        return None
    e2e = parse_end_to_end(completion_text(e2e_raw))
    struct = parse_structured(completion_text(struct_raw))
    return {
        "A_end_to_end": e2e["relation_normalized"],
        "B_forced_comparability": relation_without_gate(struct),
        "C_structured_with_gate": relation_with_gate(struct),
        "same_proposition": struct["same_proposition_normalized"],
        "stance_a": struct["stance_a_normalized"], "stance_b": struct["stance_b_normalized"],
        "malformed_output": e2e["malformed_output"] or struct["malformed_output"],
    }


def original_predictions(root: Path, model: str, pair_id: str) -> dict | None:
    """Predictions already collected on the unmodified gold pair (cache only)."""
    raw_dir = root / "data" / "processed" / "llm_raw_outputs"
    e2e_path = raw_dir / f"end_to_end_{_slug(model)}_{pair_id}.json"
    struct_path = raw_dir / f"structured_{_slug(model)}_{pair_id}.json"
    if not e2e_path.exists() or not struct_path.exists():
        return None
    e2e = parse_end_to_end(completion_text(json.loads(e2e_path.read_text(encoding="utf-8"))))
    struct = parse_structured(completion_text(json.loads(struct_path.read_text(encoding="utf-8"))))
    return {"A_end_to_end": e2e["relation_normalized"],
            "B_forced_comparability": relation_without_gate(struct),
            "C_structured_with_gate": relation_with_gate(struct)}


# --------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------

def wilson(successes: int, n: int, z: float = 1.96) -> list[float] | None:
    if n == 0:
        return None
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return [round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)]


def rate(rows: list[dict], predicate) -> dict:
    hits = sum(1 for row in rows if predicate(row))
    return {"k": hits, "n": len(rows), "rate": round(hits / len(rows), 4) if rows else None,
            "wilson_95": wilson(hits, len(rows))}


def summarize(prediction_rows: list[dict]) -> dict:
    """Headline rates per model x condition x operation, on accepted rewrites only."""
    output: dict = {}
    for model in sorted({row["model"] for row in prediction_rows}):
        output[model] = {}
        for operation in OPERATIONS:
            rows = [row for row in prediction_rows if row["model"] == model and row["operation"] == operation]
            per_condition = {}
            for condition in CONDITIONS:
                preds = [{"pred": row[condition], "expected": row["expected_relation"]} for row in rows]
                per_condition[condition] = {
                    "accuracy_vs_expected": rate(preds, lambda r: r["pred"] == r["expected"]),
                    "predicted_reversed": rate(preds, lambda r: r["pred"] == "STANCE_REVERSED"),
                    "predicted_comparable_relation": rate(
                        preds, lambda r: r["pred"] in {"STANCE_MAINTAINED", "STANCE_REVERSED"}),
                    "prediction_distribution": dict(collections.Counter(r["pred"] for r in preds)),
                }
            output[model][operation] = {"n_accepted": len(rows), "conditions": per_condition}
    return output


def headline(summary: dict) -> dict:
    """The four quantities the stress test was designed to measure."""
    out = {}
    for model, ops in summary.items():
        entry = {}
        for condition in CONDITIONS:
            get = lambda op, key: ops.get(op, {}).get("conditions", {}).get(condition, {}).get(key, {})
            entry[condition] = {
                "reversal_recall__REVERSE_ON_COMPARABLE": get("REVERSE_ON_COMPARABLE", "predicted_reversed"),
                "false_reversal__REVERSE_ON_INCOMPARABLE": get("REVERSE_ON_INCOMPARABLE", "predicted_reversed"),
                "false_reversal__NEGATED_PARAPHRASE": get("NEGATED_PARAPHRASE", "predicted_reversed"),
                "false_comparability__SHIFT_PROPOSITION": get("SHIFT_PROPOSITION", "predicted_comparable_relation"),
            }
        out[model] = entry
    return out


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------

def manifest(root: Path, plan: list[dict]) -> dict:
    return {
        "experiment_version": EXPERIMENT_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "generator_model": GENERATOR_MODEL, "verifier_model": VERIFIER_MODEL,
        "evaluated_models": EVALUATED_MODELS, "temperature": TEMPERATURE, "seed": SEED,
        "prompt_sha256": {str(p): prompt_sha256(root / p) for p in (
            GENERATE_PROMPT_PATH, VERIFY_PROMPT_PATH, END_TO_END_PROMPT_PATH, STRUCTURED_PROMPT_PATH)},
        "gold_sha256": {str(p): hashlib.sha256((root / p).read_bytes()).hexdigest() for p in GOLD_PATHS},
        "deterministic_bounds": {"min_word_similarity": MIN_WORD_SIMILARITY, "max_word_similarity": MAX_WORD_SIMILARITY,
                                 "min_length_ratio": MIN_LENGTH_RATIO, "max_length_ratio": MAX_LENGTH_RATIO},
        "plan_counts": dict(collections.Counter(spec["operation"] for spec in plan)),
        "label_policy": "expected relations are SYNTHETIC_EXPECTED, derived from the operation applied to human gold",
        "git_commit": _git_commit(root),
    }


def dry_run_plan(root: Path, plan: list[dict], gold: dict[str, dict]) -> dict:
    """Upper-bound call count and cost; verify/evaluate assume every rewrite is accepted."""
    stages = collections.defaultdict(lambda: {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0})

    def add(stage: str, model: str, prompt: str, output_tokens: int) -> None:
        entry = stages[f"{stage} [{model}]"]
        tokens_in = estimate_tokens(prompt)
        entry["calls"] += 1
        entry["input_tokens"] += tokens_in
        entry["output_tokens"] += output_tokens
        entry["cost_usd"] += estimate_cost(model, tokens_in, output_tokens)

    for spec in plan:
        row = gold[spec["source_pair_id"]]
        text_b = row["text_b"]
        add("generate", GENERATOR_MODEL, render_generation_prompt(root, spec, text_b), estimate_tokens(text_b) + 100)
        add("verify", VERIFIER_MODEL, render_verification_prompt(root, spec, text_b, text_b), 200)
        pair = perturbed_pair(row, spec, text_b)
        for model in EVALUATED_MODELS:
            add("eval_end_to_end", model, render_prompt(root / END_TO_END_PROMPT_PATH, pair), 120)
            add("eval_structured", model, render_prompt(root / STRUCTURED_PROMPT_PATH, pair), 250)
    for entry in stages.values():
        entry["cost_usd"] = round(entry["cost_usd"], 4)
    return {"stages": dict(stages),
            "total_calls_upper_bound": sum(s["calls"] for s in stages.values()),
            "total_cost_usd_upper_bound": round(sum(s["cost_usd"] for s in stages.values()), 4)}


def process_spec(root: Path, spec: dict, row: dict, execute: bool) -> tuple[dict, list[dict]]:
    """Generate, check, verify and (if accepted) evaluate one counterfactual."""
    original = row["text_b"]
    gen_raw = cached_call(root, "generate", GENERATOR_MODEL, spec["spec_id"],
                          render_generation_prompt(root, spec, original), execute,
                          max_tokens=generation_max_tokens(original))
    generation = parse_generation(completion_text(gen_raw))
    checks = deterministic_checks(original, generation["rewritten_text"])
    verification: dict = {"verification_malformed": True}
    if generation["generation_parsed"] and checks["deterministic_ok"]:
        ver_raw = cached_call(root, "verify", VERIFIER_MODEL, spec["spec_id"],
                              render_verification_prompt(root, spec, original, generation["rewritten_text"]),
                              execute)
        verification = parse_verification(completion_text(ver_raw))
    accepted, reasons = accept(spec, generation, checks, verification)
    audit = {**spec, **{k: v for k, v in generation.items() if k != "rewritten_text"}, **checks,
             **{k: verification.get(k, "") for k in (*VERIFY_YES_FIELDS,
                "rewritten_stance_on_original_target", "verification_reasoning")},
             "accepted": accepted, "rejection_reasons": reasons,
             "copy_noise_paragraphs": copy_noise_paragraphs(original, generation["rewritten_text"]),
             "rewritten_text_b": generation["rewritten_text"]}
    predictions = []
    if accepted:
        pair = perturbed_pair(row, spec, generation["rewritten_text"])
        for model in EVALUATED_MODELS:
            prediction = predict(root, pair, model, execute)
            before = original_predictions(root, model, spec["source_pair_id"]) or {}
            predictions.append({
                "spec_id": spec["spec_id"], "source_pair_id": spec["source_pair_id"],
                "gold_round": spec["gold_round"], "operation": spec["operation"],
                "expected_relation": spec["expected_relation"], "model": model, **prediction,
                **{f"original_{c}": before.get(c, "") for c in CONDITIONS},
                "label_source": "MODEL_PREDICTION_ON_SYNTHETIC",
            })
    return audit, predictions


def run(root: Path, execute: bool) -> dict:
    gold_rows = load_gold(root)
    gold = {row["pair_id"]: row for row in gold_rows}
    plan = build_plan(gold_rows)
    out = root / OUT_DIR
    out.mkdir(parents=True, exist_ok=True)
    write_csv(out / "stress_plan.csv", plan, list(plan[0]))
    if not execute:
        return {"mode": "DRY_RUN_NO_REQUESTS_SENT", "plan_counts": dict(collections.Counter(s["operation"] for s in plan)),
                **dry_run_plan(root, plan, gold)}

    (out / "stress_manifest.json").write_text(
        json.dumps(manifest(root, plan), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        results = list(pool.map(lambda spec: process_spec(root, spec, gold[spec["source_pair_id"]], execute), plan))
    audit_rows = [audit for audit, _ in results]
    prediction_rows = [prediction for _, predictions in results for prediction in predictions]

    write_csv(out / "stress_generation_audit.csv", audit_rows, list(audit_rows[0]))
    if prediction_rows:
        write_csv(out / "stress_predictions.csv", prediction_rows, list(prediction_rows[0]))
    funnel = {op: {"planned": sum(r["operation"] == op for r in audit_rows),
                   "accepted": sum(r["operation"] == op and r["accepted"] for r in audit_rows)}
              for op in OPERATIONS}
    summary = summarize(prediction_rows)
    noisy = {r["spec_id"] for r in audit_rows if r["accepted"] and r["copy_noise_paragraphs"]}
    clean_rows = [r for r in prediction_rows if r["spec_id"] not in noisy]
    result = {"mode": "EXECUTED", "funnel": funnel, "headline": headline(summary),
              "sensitivity_excluding_copy_noise": {"excluded_spec_ids": sorted(noisy),
                                                   "headline": headline(summarize(clean_rows))},
              "by_operation": summary,
              "rejection_reason_counts": dict(collections.Counter(
                  reason for r in audit_rows for reason in r["rejection_reasons"].split("|") if reason))}
    (out / "stress_metrics.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--execute", action="store_true", help="send real API requests (default: dry-run)")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    print(json.dumps(run(root, args.execute), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
