"""Automatic (LLM) comparability-gate baselines — an experimental track separate
from the deterministic, no-API pipeline in audit/provenance/expansion/agreement/
consensus. No LLM is a classifier anywhere else in this project.

Three conditions, only two LLM calls per pair x model:
  A) end-to-end: one call, model outputs the final relation directly.
  structured extraction: one call, model outputs stance_determinable_a/b,
    target_proposition_a/b, same_proposition, stance_a/b.
  B) structured WITHOUT gate: derived from the structured call, ignoring
    same_proposition (assumes comparability).
  C) structured WITH gate: derived from the same structured call, using
    agreement.derive_relation unmodified.

The 18-pair human gold (semantic_pilot_gold.csv) is the only ground truth.
The 29 expansion pairs have no ground truth: predictions on them are always
label_source=MODEL_PREDICTION, never HUMAN_CONSENSUS, and metrics (accuracy,
F1, "correct") are never computed against them. Model-to-model agreement on
the 29 is INTER_MODEL_AGREEMENT, never gold.

A malformed model output (a value outside the schema's vocabulary) is a
format/schema error, not semantic uncertainty: it is flagged malformed_output
+ malformed_fields and never silently folded into a legitimate UNCERTAIN.

Run from the repository root (requires DEEPINFRA_API_KEY):
    PYTHONPATH=src python3 -m voxlab.automatic_baselines
"""

from __future__ import annotations

import collections
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .agreement import DETERMINABILITY, SAME_PROPOSITION, STANCE, categorical_agreement, derive_relation
from .audit import write_csv
from .llm_client import chat_completion, completion_text
from .semantic_pilot import DISPLAY_FIELDS, read_csv

RELATION_LABELS = {
    "STANCE_MAINTAINED", "STANCE_REVERSED", "INCOMPARABLE",
    "RELATION_UNCERTAIN", "INSUFFICIENT_EVIDENCE",
}
STRUCTURED_CATEGORICAL_FIELDS = (
    "stance_determinable_a", "stance_determinable_b", "same_proposition", "stance_a", "stance_b",
)
STRUCTURED_TEXT_FIELDS = ("target_proposition_a", "target_proposition_b")
STRUCTURED_VOCAB = {
    "stance_determinable_a": DETERMINABILITY, "stance_determinable_b": DETERMINABILITY,
    "same_proposition": SAME_PROPOSITION, "stance_a": STANCE, "stance_b": STANCE,
}
GATE_EFFECTS = ("ERROR_TO_CORRECT", "CORRECT_TO_ERROR", "CORRECT_TO_CORRECT", "ERROR_TO_ERROR")
DEFAULT_TEMPERATURE = 0.0
DEFAULT_SEED = 20260924
EXPERIMENT_VERSION = "automatic_baselines_v1"

STRUCTURED_PROMPT_PATH = Path("prompts/structured_extraction_v1.txt")
END_TO_END_PROMPT_PATH = Path("prompts/baseline_a_end_to_end_v1.txt")


# --------------------------------------------------------------------------
# Blind input loading — never expose human response fields to the model.
# --------------------------------------------------------------------------

def load_blind_pairs_from_gold(root: Path) -> list[dict[str, str]]:
    rows = read_csv(root / "data" / "annotations" / "semantic_pilot_gold.csv")
    return [{field: row[field] for field in DISPLAY_FIELDS} for row in rows]


def load_gold_truth(root: Path) -> dict[str, dict[str, str]]:
    """Human labels, used only for evaluation — never given to the model."""
    rows = read_csv(root / "data" / "annotations" / "semantic_pilot_gold.csv")
    fields = ("same_proposition", "stance_determinable_a", "stance_determinable_b",
              "stance_a", "stance_b", "derived_relation")
    return {row["pair_id"]: {field: row[field] for field in fields} for row in rows}


def load_blind_pairs_from_expansion(root: Path, annotator: int = 1) -> list[dict[str, str]]:
    rows = read_csv(root / "data" / "annotations" / f"expansion_annotator_{annotator}.csv")
    return [{field: row[field] for field in DISPLAY_FIELDS} for row in rows]


# --------------------------------------------------------------------------
# Prompt rendering
# --------------------------------------------------------------------------

def render_prompt(template_path: Path, pair: dict[str, str]) -> str:
    template = template_path.read_text(encoding="utf-8")
    return template.format(**{field: pair.get(field, "") for field in DISPLAY_FIELDS})


def prompt_sha256(template_path: Path) -> str:
    return hashlib.sha256(template_path.read_bytes()).hexdigest()


# --------------------------------------------------------------------------
# Raw calls — every raw response is persisted verbatim, never hand-edited.
# --------------------------------------------------------------------------

def _model_slug(model: str) -> str:
    return model.replace("/", "_")


def _raw_path(root: Path, condition: str, model: str, pair_id: str) -> Path:
    out_dir = root / "data" / "processed" / "llm_raw_outputs"
    return out_dir / f"{condition}_{_model_slug(model)}_{pair_id}.json"


def _save_raw(root: Path, condition: str, model: str, pair_id: str, raw: dict) -> None:
    path = _raw_path(root, condition, model, pair_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _load_cached_raw(root: Path, condition: str, model: str, pair_id: str) -> dict | None:
    """Resume support: a raw response already on disk is reused verbatim,
    never re-requested. Keeps a crash mid-run from re-billing completed calls."""
    path = _raw_path(root, condition, model, pair_id)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def call_end_to_end(root: Path, pair: dict[str, str], model: str) -> dict:
    cached = _load_cached_raw(root, "end_to_end", model, pair["pair_id"])
    if cached is not None:
        return cached
    prompt = render_prompt(END_TO_END_PROMPT_PATH, pair)
    response = chat_completion(root, model, [{"role": "user", "content": prompt}],
                               temperature=DEFAULT_TEMPERATURE, seed=DEFAULT_SEED)
    _save_raw(root, "end_to_end", model, pair["pair_id"], response)
    return response


def call_structured(root: Path, pair: dict[str, str], model: str) -> dict:
    cached = _load_cached_raw(root, "structured", model, pair["pair_id"])
    if cached is not None:
        return cached
    prompt = render_prompt(STRUCTURED_PROMPT_PATH, pair)
    response = chat_completion(root, model, [{"role": "user", "content": prompt}],
                               temperature=DEFAULT_TEMPERATURE, seed=DEFAULT_SEED)
    _save_raw(root, "structured", model, pair["pair_id"], response)
    return response


# --------------------------------------------------------------------------
# Parsing — schema/format errors are distinguished from semantic UNCERTAIN.
# --------------------------------------------------------------------------

def _extract_json(raw_text: str) -> dict | None:
    """Best-effort JSON extraction; returns None (not a fabricated value) on failure."""
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            return None


def parse_end_to_end(raw_text: str) -> dict:
    parsed = _extract_json(raw_text)
    if parsed is None or not isinstance(parsed, dict):
        return {"relation_raw": raw_text, "relation_valid": False,
                "relation_normalized": "RELATION_UNCERTAIN",
                "malformed_output": True, "malformed_fields": ["relation"],
                "reasoning": ""}
    raw_value = parsed.get("relation", "")
    valid = raw_value in RELATION_LABELS
    return {"relation_raw": raw_value, "relation_valid": valid,
            "relation_normalized": raw_value if valid else "RELATION_UNCERTAIN",
            "malformed_output": not valid, "malformed_fields": [] if valid else ["relation"],
            "reasoning": parsed.get("reasoning", "")}


def parse_structured(raw_text: str) -> dict:
    parsed = _extract_json(raw_text)
    result: dict = {"raw_text": raw_text}
    malformed_fields: list[str] = []
    if parsed is None or not isinstance(parsed, dict):
        for field in STRUCTURED_CATEGORICAL_FIELDS:
            vocab = STRUCTURED_VOCAB[field]
            result[f"{field}_raw"] = ""
            result[f"{field}_valid"] = False
            result[f"{field}_normalized"] = "UNCERTAIN" if "UNCERTAIN" in vocab else next(iter(vocab))
            malformed_fields.append(field)
        for field in STRUCTURED_TEXT_FIELDS:
            result[field] = ""
        result["malformed_output"] = True
        result["malformed_fields"] = malformed_fields
        return result
    # Determinability and same_proposition are always required (strict).
    for field in ("stance_determinable_a", "stance_determinable_b", "same_proposition"):
        vocab = STRUCTURED_VOCAB[field]
        raw_value = parsed.get(field, "")
        valid = raw_value in vocab
        result[f"{field}_raw"] = raw_value
        result[f"{field}_valid"] = valid
        result[f"{field}_normalized"] = raw_value if valid else "UNCERTAIN"
        if not valid:
            malformed_fields.append(field)
    # stance_a/b are conditionally required: the prompt instructs the model to
    # leave them empty when the matching stance_determinable side isn't YES.
    # An empty stance in that case is a correctly-formatted response, not a
    # schema/format error.
    for field, det_field in (("stance_a", "stance_determinable_a"), ("stance_b", "stance_determinable_b")):
        vocab = STRUCTURED_VOCAB[field]
        raw_value = parsed.get(field, "")
        determinable_is_yes = result[f"{det_field}_normalized"] == "YES"
        if raw_value == "" and not determinable_is_yes:
            result[f"{field}_raw"] = raw_value
            result[f"{field}_valid"] = True
            result[f"{field}_normalized"] = "UNCERTAIN"
            continue
        valid = raw_value in vocab
        result[f"{field}_raw"] = raw_value
        result[f"{field}_valid"] = valid
        result[f"{field}_normalized"] = raw_value if valid else "UNCERTAIN"
        if not valid:
            malformed_fields.append(field)
    for field in STRUCTURED_TEXT_FIELDS:
        result[field] = parsed.get(field, "")
    result["malformed_output"] = bool(malformed_fields)
    result["malformed_fields"] = malformed_fields
    return result


# --------------------------------------------------------------------------
# Deterministic derivation — the ONLY difference between B and C.
# --------------------------------------------------------------------------

def relation_without_gate(structured: dict) -> str:
    """Condition B: same structured output, same_proposition forced to YES."""
    return derive_relation(
        structured["stance_determinable_a_normalized"],
        structured["stance_determinable_b_normalized"],
        "YES",
        structured["stance_a_normalized"],
        structured["stance_b_normalized"],
    )


def relation_with_gate(structured: dict) -> str:
    """Condition C: same structured output, real same_proposition value."""
    return derive_relation(
        structured["stance_determinable_a_normalized"],
        structured["stance_determinable_b_normalized"],
        structured["same_proposition_normalized"],
        structured["stance_a_normalized"],
        structured["stance_b_normalized"],
    )


def gate_effect(gold_relation: str, without_gate: str, with_gate: str) -> str:
    without_correct = without_gate == gold_relation
    with_correct = with_gate == gold_relation
    if not without_correct and with_correct:
        return "ERROR_TO_CORRECT"
    if without_correct and not with_correct:
        return "CORRECT_TO_ERROR"
    if without_correct and with_correct:
        return "CORRECT_TO_CORRECT"
    return "ERROR_TO_ERROR"


# --------------------------------------------------------------------------
# Metrics — undefined is reported explicitly, never omitted or coerced to 0.
# --------------------------------------------------------------------------

def _class_prf1(predicted: list[str], gold: list[str], label: str) -> dict:
    tp = sum(p == label and g == label for p, g in zip(predicted, gold))
    fp = sum(p == label and g != label for p, g in zip(predicted, gold))
    fn = sum(p != label and g == label for p, g in zip(predicted, gold))
    n_pred, n_gold = tp + fp, tp + fn
    precision = "undefined" if n_pred == 0 else round(tp / n_pred, 4)
    recall = "undefined" if n_gold == 0 else round(tp / n_gold, 4)
    if precision == "undefined" or recall == "undefined" or (precision + recall) == 0:
        f1 = "undefined"
    else:
        f1 = round(2 * precision * recall / (precision + recall), 4)
    return {"precision": precision, "recall": recall, "f1": f1,
            "support_gold": n_gold, "support_predicted": n_pred}


def relation_metrics(predicted: list[str], gold: list[str]) -> dict:
    if len(predicted) != len(gold):
        raise ValueError("Predicted and gold sequences must be paired 1:1")
    n = len(gold)
    accuracy = sum(p == g for p, g in zip(predicted, gold)) / n if n else 0.0
    per_class = {label: _class_prf1(predicted, gold, label) for label in sorted(RELATION_LABELS)}
    defined_f1 = [c["f1"] for c in per_class.values() if c["f1"] != "undefined"]
    macro_f1 = round(sum(defined_f1) / len(defined_f1), 4) if defined_f1 else "undefined"
    confusion = collections.defaultdict(lambda: collections.defaultdict(int))
    for p, g in zip(predicted, gold):
        confusion[g][p] += 1
    false_reversal_count = sum(p == "STANCE_REVERSED" and g != "STANCE_REVERSED" for p, g in zip(predicted, gold))
    return {
        "n": n, "accuracy": round(accuracy, 4),
        "macro_f1": macro_f1,
        "macro_f1_note": "average over classes with defined F1 only; see per_class for undefined ones",
        "per_class": per_class,
        "confusion_matrix": {g: dict(row) for g, row in confusion.items()},
        "false_reversal_count": false_reversal_count,
        "false_reversal_rate": round(false_reversal_count / n, 4) if n else 0.0,
        "false_reversal_rate_denominator": n,
        "stance_reversed_recall_status": (
            "undefined_not_estimable_zero_positives_in_gold"
            if per_class["STANCE_REVERSED"]["support_gold"] == 0 else "estimable"
        ),
    }


def comparability_metrics(predicted_same_proposition: list[str], gold_same_proposition: list[str]) -> dict:
    """Binary YES/NO comparability accuracy/F1; UNCERTAIN pairs reported separately."""
    paired = [(p, g) for p, g in zip(predicted_same_proposition, gold_same_proposition)]
    binary = [(p, g) for p, g in paired if g in {"YES", "NO"}]
    uncertain_gold = sum(g == "UNCERTAIN" for _, g in paired)
    if not binary:
        return {"n_binary": 0, "accuracy": "undefined", "f1": "undefined", "n_gold_uncertain_excluded": uncertain_gold}
    pred, gold = [p for p, _ in binary], [g for _, g in binary]
    accuracy = sum(p == g for p, g in zip(pred, gold)) / len(binary)
    yes_metrics = _class_prf1(pred, gold, "YES")
    return {"n_binary": len(binary), "accuracy": round(accuracy, 4),
            "f1_positive_class_YES": yes_metrics["f1"],
            "precision_YES": yes_metrics["precision"], "recall_YES": yes_metrics["recall"],
            "n_gold_uncertain_excluded": uncertain_gold}


def stance_metrics(predicted_stances: list[str], gold_stances: list[str], gold_determinable: list[str]) -> dict:
    """Stance accuracy/F1, restricted to sides where gold itself has a determinate stance."""
    filtered = [(p, g) for p, g, det in zip(predicted_stances, gold_stances, gold_determinable)
                if det == "YES" and g in {"FAVOR", "AGAINST"}]
    if not filtered:
        return {"n": 0, "accuracy": "undefined"}
    pred, gold = [p for p, _ in filtered], [g for _, g in filtered]
    accuracy = sum(p == g for p, g in zip(pred, gold)) / len(filtered)
    favor_metrics = _class_prf1(pred, gold, "FAVOR")
    return {"n": len(filtered), "accuracy": round(accuracy, 4), "f1_FAVOR": favor_metrics["f1"]}


def output_quality_metrics(rows: list[dict]) -> dict:
    total = len(rows)
    malformed = sum(row["malformed_output"] for row in rows)
    valid_rate = round((total - malformed) / total, 4) if total else 0.0
    return {"total_calls": total, "malformed_output_count": malformed,
            "valid_output_rate": valid_rate, "schema_failure_rate": round(1 - valid_rate, 4)}


# --------------------------------------------------------------------------
# Manifest — freezes the experiment configuration. Never includes the key.
# --------------------------------------------------------------------------

def _git_commit(root: Path) -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True,
                              text=True, timeout=5, check=True).stdout.strip()
    except Exception:
        return "unavailable"


def build_manifest(root: Path, models: list[str], gold_pair_count: int, expansion_pair_count: int) -> dict:
    return {
        "experiment_version": EXPERIMENT_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "prompt_end_to_end_version": "v1",
        "prompt_end_to_end_sha256": prompt_sha256(root / END_TO_END_PROMPT_PATH),
        "prompt_structured_version": "v1",
        "prompt_structured_sha256": prompt_sha256(root / STRUCTURED_PROMPT_PATH),
        "models": models,
        "temperature": DEFAULT_TEMPERATURE,
        "seed": DEFAULT_SEED,
        "provider": "deepinfra",
        "gold_pair_count": gold_pair_count,
        "expansion_pair_count": expansion_pair_count,
        "relation_derivation_version": "voxlab.agreement.derive_relation",
        "false_reversal_definition": (
            "count of predictions == STANCE_REVERSED where gold_relation != STANCE_REVERSED; "
            "denominator is fixed at the full gold pair count, defined before any run"
        ),
        "git_commit": _git_commit(root),
    }


# --------------------------------------------------------------------------
# Pairwise analysis and inter-model agreement (expansion set only).
# --------------------------------------------------------------------------

def pairwise_gate_table(
    pair_ids: list[str], model: str, gold: dict[str, dict],
    end_to_end_by_pair: dict[str, dict], structured_by_pair: dict[str, dict],
) -> list[dict]:
    rows = []
    for pid in pair_ids:
        g, e2e, struct = gold[pid], end_to_end_by_pair[pid], structured_by_pair[pid]
        without, with_ = relation_without_gate(struct), relation_with_gate(struct)
        rows.append({
            "pair_id": pid, "model": model, "relation_gold": g["derived_relation"],
            "baseline_a_relation": e2e["relation_normalized"],
            "structured_without_gate_relation": without,
            "structured_with_gate_relation": with_,
            "stance_determinable_a": struct["stance_determinable_a_normalized"],
            "stance_determinable_b": struct["stance_determinable_b_normalized"],
            "target_proposition_a": struct["target_proposition_a"],
            "target_proposition_b": struct["target_proposition_b"],
            "same_proposition": struct["same_proposition_normalized"],
            "stance_a": struct["stance_a_normalized"], "stance_b": struct["stance_b_normalized"],
            "A_correct": e2e["relation_normalized"] == g["derived_relation"],
            "B_correct": without == g["derived_relation"],
            "C_correct": with_ == g["derived_relation"],
            "gate_effect": gate_effect(g["derived_relation"], without, with_),
            "malformed_output": e2e["malformed_output"] or struct["malformed_output"],
        })
    return rows


def gate_effect_summary(rows: list[dict]) -> dict:
    counts = collections.Counter(row["gate_effect"] for row in rows)
    return {effect: counts.get(effect, 0) for effect in GATE_EFFECTS}


def inter_model_agreement(rows_model_1: list[dict], rows_model_2: list[dict]) -> dict:
    """Agreement between two LLMs on the UNLABELED expansion set.

    Explicitly not human agreement, not gold agreement, not a validation
    signal. Must never be used to promote a pair to gold.
    """
    by_pair_1 = {r["pair_id"]: r for r in rows_model_1}
    by_pair_2 = {r["pair_id"]: r for r in rows_model_2}
    shared = sorted(set(by_pair_1) & set(by_pair_2))
    same_prop_1 = [by_pair_1[p]["same_proposition_normalized"] for p in shared]
    same_prop_2 = [by_pair_2[p]["same_proposition_normalized"] for p in shared]
    stance_a_1 = [by_pair_1[p]["stance_a_normalized"] for p in shared]
    stance_a_2 = [by_pair_2[p]["stance_a_normalized"] for p in shared]
    relation_1 = [relation_with_gate(by_pair_1[p]) for p in shared]
    relation_2 = [relation_with_gate(by_pair_2[p]) for p in shared]
    return {
        "label": "INTER_MODEL_AGREEMENT",
        "note": ("Agreement between two LLMs on the unlabeled expansion set. "
                "Never human agreement, never gold agreement, never a validation "
                "signal. Must not be used to promote any pair to gold."),
        "n_pairs": len(shared),
        "same_proposition_agreement": categorical_agreement(same_prop_1, same_prop_2),
        "stance_a_agreement": categorical_agreement(stance_a_1, stance_a_2),
        "relation_with_gate_agreement": categorical_agreement(relation_1, relation_2),
    }


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------

def run_gold(root: Path, model: str) -> tuple[dict[str, dict], dict[str, dict]]:
    """Run both LLM conditions on the 18 gold pairs. Returns keyed by pair_id."""
    pairs = load_blind_pairs_from_gold(root)
    end_to_end, structured = {}, {}
    for pair in pairs:
        pid = pair["pair_id"]
        end_to_end[pid] = parse_end_to_end(completion_text(call_end_to_end(root, pair, model)))
        structured[pid] = parse_structured(completion_text(call_structured(root, pair, model)))
    return end_to_end, structured


def run_expansion(root: Path, model: str, annotator: int = 1) -> tuple[dict[str, dict], dict[str, dict]]:
    """Run the SAME frozen conditions on the 29 expansion pairs. No gold exists."""
    pairs = load_blind_pairs_from_expansion(root, annotator)
    end_to_end, structured = {}, {}
    for pair in pairs:
        pid = pair["pair_id"]
        end_to_end[pid] = parse_end_to_end(completion_text(call_end_to_end(root, pair, model)))
        structured[pid] = parse_structured(completion_text(call_structured(root, pair, model)))
    return end_to_end, structured


def _structured_csv_row(pid: str, model: str, struct: dict) -> dict:
    row = {"pair_id": pid, "model": model,
           "target_proposition_a": struct["target_proposition_a"],
           "target_proposition_b": struct["target_proposition_b"],
           "malformed_output": struct["malformed_output"],
           "malformed_fields": "|".join(struct["malformed_fields"])}
    for field in STRUCTURED_CATEGORICAL_FIELDS:
        row[f"{field}_raw"] = struct[f"{field}_raw"]
        row[f"{field}_valid"] = struct[f"{field}_valid"]
        row[f"{field}_normalized"] = struct[f"{field}_normalized"]
    return row


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    models = ["Qwen/Qwen2.5-72B-Instruct", "meta-llama/Llama-3.3-70B-Instruct-Turbo"]

    gold_truth = load_gold_truth(root)
    gold_pair_ids = sorted(gold_truth)
    expansion_pairs = load_blind_pairs_from_expansion(root)
    expansion_pair_ids = [p["pair_id"] for p in expansion_pairs]

    manifest = build_manifest(root, models, len(gold_pair_ids), len(expansion_pair_ids))
    out = root / "data" / "processed"
    (out / "automatic_experiment_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    e2e_rows, structured_rows, ablation_rows, pairwise_rows = [], [], [], []
    metrics_by_model: dict[str, dict] = {}
    expansion_structured_by_model: dict[str, dict[str, dict]] = {}
    expansion_e2e_rows: list[dict] = []

    for model in models:
        e2e_by_pair, structured_by_pair = run_gold(root, model)
        for pid in gold_pair_ids:
            e2e_rows.append({"pair_id": pid, "model": model, **e2e_by_pair[pid]})
            structured_rows.append(_structured_csv_row(pid, model, structured_by_pair[pid]))
            without = relation_without_gate(structured_by_pair[pid])
            with_ = relation_with_gate(structured_by_pair[pid])
            ablation_rows.append({
                "pair_id": pid, "model": model, "relation_gold": gold_truth[pid]["derived_relation"],
                "relation_without_gate": without, "relation_with_gate": with_,
                "gate_effect": gate_effect(gold_truth[pid]["derived_relation"], without, with_),
            })
        pairwise_rows.extend(pairwise_gate_table(gold_pair_ids, model, gold_truth, e2e_by_pair, structured_by_pair))

        gold_relations = [gold_truth[pid]["derived_relation"] for pid in gold_pair_ids]
        e2e_predicted = [e2e_by_pair[pid]["relation_normalized"] for pid in gold_pair_ids]
        without_predicted = [relation_without_gate(structured_by_pair[pid]) for pid in gold_pair_ids]
        with_predicted = [relation_with_gate(structured_by_pair[pid]) for pid in gold_pair_ids]
        gold_same_proposition = [gold_truth[pid]["same_proposition"] for pid in gold_pair_ids]
        predicted_same_proposition = [structured_by_pair[pid]["same_proposition_normalized"] for pid in gold_pair_ids]

        metrics_by_model[model] = {
            "end_to_end": relation_metrics(e2e_predicted, gold_relations),
            "structured_without_gate": relation_metrics(without_predicted, gold_relations),
            "structured_with_gate": relation_metrics(with_predicted, gold_relations),
            "comparability_gate": comparability_metrics(predicted_same_proposition, gold_same_proposition),
            "output_quality": {
                "end_to_end": output_quality_metrics(list(e2e_by_pair.values())),
                "structured": output_quality_metrics(list(structured_by_pair.values())),
            },
            "gate_effect_summary": gate_effect_summary(
                [row for row in pairwise_rows if row["model"] == model]
            ),
        }

        exp_e2e_by_pair, exp_structured_by_pair = run_expansion(root, model)
        expansion_structured_by_model[model] = exp_structured_by_pair
        for pid in expansion_pair_ids:
            struct = exp_structured_by_pair[pid]
            expansion_e2e_rows.append({
                "pair_id": pid, "model": model,
                "relation_end_to_end": exp_e2e_by_pair[pid]["relation_normalized"],
                "relation_structured_without_gate": relation_without_gate(struct),
                "relation_structured_with_gate": relation_with_gate(struct),
                "stance_determinable_a": struct["stance_determinable_a_normalized"],
                "stance_determinable_b": struct["stance_determinable_b_normalized"],
                "target_proposition_a": struct["target_proposition_a"],
                "target_proposition_b": struct["target_proposition_b"],
                "same_proposition": struct["same_proposition_normalized"],
                "stance_a": struct["stance_a_normalized"], "stance_b": struct["stance_b_normalized"],
                "malformed_output": exp_e2e_by_pair[pid]["malformed_output"] or struct["malformed_output"],
                "label_source": "MODEL_PREDICTION",
            })

    write_csv(out / "gold18_end_to_end_predictions.csv", e2e_rows, list(e2e_rows[0]))
    write_csv(out / "gold18_structured_predictions.csv", structured_rows, list(structured_rows[0]))
    write_csv(out / "gold18_gate_ablation.csv", ablation_rows, list(ablation_rows[0]))
    write_csv(out / "gold18_pairwise_analysis.csv", pairwise_rows, list(pairwise_rows[0]))
    (out / "gold18_metrics.json").write_text(
        json.dumps(metrics_by_model, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_csv(out / "expansion29_model_predictions.csv", expansion_e2e_rows, list(expansion_e2e_rows[0]))

    if len(models) == 2:
        agreement = inter_model_agreement(
            [{"pair_id": pid, **expansion_structured_by_model[models[0]][pid]} for pid in expansion_pair_ids],
            [{"pair_id": pid, **expansion_structured_by_model[models[1]][pid]} for pid in expansion_pair_ids],
        )
        (out / "expansion29_intermodel_agreement.json").write_text(
            json.dumps(agreement, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps(metrics_by_model, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
