"""Exploratory comparability baselines for the adjudicated VoxLab pilot.

The 18-pair pilot is development evidence, not a held-out benchmark. Scores
use only source text/topic fields. Human target propositions and notes are
copied to the diagnostic table solely for qualitative review.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
from pathlib import Path

from .audit import cosine, tfidf_vectors, tokens, write_csv
from .semantic_pilot import read_csv


SCORE_INPUT_FIELDS = ("topic_a", "topic_b", "evidence_a", "evidence_b", "text_a", "text_b")
DIAGNOSTIC_FIELDS = [
    "pair_id", "gold_same_proposition", "binary_evaluation_label", "derived_relation",
    "candidate_topic_similarity", "candidate_threshold_0_10_prediction",
    "evidence_tfidf_cosine", "speech_tfidf_cosine", "evidence_token_jaccard",
    "oracle_stance_no_gate_relation", "no_gate_invalid_relation", "no_gate_false_reversal",
    "target_proposition_a", "target_proposition_b", "comparability_notes",
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def binary_label(same_proposition: str) -> str:
    """Map adjudication to the strict binary gate; preserve uncertainty as exclusion."""
    if same_proposition == "YES":
        return "COMPARABLE"
    if same_proposition == "NO":
        return "INCOMPARABLE"
    if same_proposition == "UNCERTAIN":
        return "EXCLUDED_UNCERTAIN"
    raise ValueError(f"Unknown same_proposition label: {same_proposition!r}")


def safe_div(numerator: int | float, denominator: int | float) -> float:
    """Use the conventional zero_division=0 policy for classification metrics."""
    return numerator / denominator if denominator else 0.0


def f1(precision: float, recall: float) -> float:
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def binary_metrics(gold: list[str], predicted: list[str]) -> dict:
    """Return transparent binary metrics with COMPARABLE as the positive class."""
    if len(gold) != len(predicted) or not gold:
        raise ValueError("Binary metrics require equally sized, non-empty inputs")
    allowed = {"COMPARABLE", "INCOMPARABLE"}
    if set(gold) - allowed or set(predicted) - allowed:
        raise ValueError("Binary metrics received a non-binary label")
    tp = sum(g == p == "COMPARABLE" for g, p in zip(gold, predicted))
    tn = sum(g == p == "INCOMPARABLE" for g, p in zip(gold, predicted))
    fp = sum(g == "INCOMPARABLE" and p == "COMPARABLE" for g, p in zip(gold, predicted))
    fn = sum(g == "COMPARABLE" and p == "INCOMPARABLE" for g, p in zip(gold, predicted))
    precision_pos = safe_div(tp, tp + fp)
    recall_pos = safe_div(tp, tp + fn)
    precision_neg = safe_div(tn, tn + fn)
    recall_neg = safe_div(tn, tn + fp)
    f1_pos, f1_neg = f1(precision_pos, recall_pos), f1(precision_neg, recall_neg)
    macro_f1 = (f1_pos + f1_neg) / 2
    balanced_accuracy = (recall_pos + recall_neg) / 2
    return {
        "n": len(gold),
        "confusion": {"tp": tp, "tn": tn, "fp": fp, "fn": fn},
        "accuracy": round((tp + tn) / len(gold), 4),
        "balanced_accuracy": round(balanced_accuracy, 4),
        "macro_f1": round(macro_f1, 4),
        "comparable_precision": round(precision_pos, 4),
        "comparable_recall": round(recall_pos, 4),
        "comparable_f1": round(f1_pos, 4),
        "zero_division_policy": 0,
    }


def roc_auc(gold: list[str], scores: list[float]) -> float | None:
    """Compute ROC AUC as pairwise ranking probability, assigning 0.5 to ties."""
    if len(gold) != len(scores):
        raise ValueError("ROC AUC inputs have different lengths")
    positive = [score for label, score in zip(gold, scores) if label == "COMPARABLE"]
    negative = [score for label, score in zip(gold, scores) if label == "INCOMPARABLE"]
    if not positive or not negative:
        return None
    wins = sum(1 if pos > neg else 0.5 if pos == neg else 0 for pos in positive for neg in negative)
    return round(wins / (len(positive) * len(negative)), 4)


def pairwise_tfidf_scores(rows: list[dict[str, str]], field: str) -> dict[str, float]:
    documents = {}
    for row in rows:
        for side in "ab":
            documents[f"{row['pair_id']}:{side}"] = row[f"{field}_{side}"]
    vectors = tfidf_vectors(documents)
    return {
        row["pair_id"]: cosine(vectors[f"{row['pair_id']}:a"], vectors[f"{row['pair_id']}:b"])
        for row in rows
    }


def token_jaccard(first: str, second: str) -> float:
    a, b = set(tokens(first)), set(tokens(second))
    return len(a & b) / len(a | b) if a or b else 0.0


def score_summary(gold: list[str], scores: list[float]) -> dict:
    output = {}
    for label in ("COMPARABLE", "INCOMPARABLE"):
        values = [score for target, score in zip(gold, scores) if target == label]
        output[label] = {
            "n": len(values),
            "min": round(min(values), 6),
            "mean": round(sum(values) / len(values), 6),
            "max": round(max(values), 6),
        }
    return output


def analyze_pilot(root: Path) -> tuple[dict, list[dict[str, str]], dict]:
    annotations = root / "data" / "annotations"
    processed = root / "data" / "processed"
    gold_path = annotations / "semantic_pilot_gold.csv"
    consensus_path = annotations / "semantic_pilot_consensus.csv"
    candidate_path = processed / "candidate_pairs.csv"
    rows = read_csv(gold_path)
    candidates = {row["pair_id"]: row for row in read_csv(candidate_path)}
    if len(rows) != len({row["pair_id"] for row in rows}):
        raise ValueError("Gold contains duplicate pair IDs")
    if any(row["label_source"] != "HUMAN_CONSENSUS" for row in rows):
        raise ValueError("Pilot baseline requires human-consensus gold")
    consensus_hash = sha256(consensus_path)
    if any(row["consensus_input_sha256"] != consensus_hash for row in rows):
        raise ValueError("Gold provenance hash does not match the current consensus")
    missing_candidates = sorted({row["pair_id"] for row in rows} - set(candidates))
    if missing_candidates:
        raise ValueError(f"Gold pair IDs missing from candidate table: {missing_candidates}")

    evidence_tfidf = pairwise_tfidf_scores(rows, "evidence")
    speech_tfidf = pairwise_tfidf_scores(rows, "text")
    diagnostic = []
    for row in rows:
        pair_id = row["pair_id"]
        label = binary_label(row["same_proposition"])
        topic_score = float(candidates[pair_id]["topic_similarity"])
        no_gate_relation = (
            "STANCE_MAINTAINED" if row["stance_a"] == row["stance_b"] else "STANCE_REVERSED"
        )
        diagnostic.append({
            "pair_id": pair_id,
            "gold_same_proposition": row["same_proposition"],
            "binary_evaluation_label": label,
            "derived_relation": row["derived_relation"],
            "candidate_topic_similarity": f"{topic_score:.6f}",
            "candidate_threshold_0_10_prediction": (
                "COMPARABLE" if topic_score >= 0.10 else "INCOMPARABLE"
            ),
            "evidence_tfidf_cosine": f"{evidence_tfidf[pair_id]:.6f}",
            "speech_tfidf_cosine": f"{speech_tfidf[pair_id]:.6f}",
            "evidence_token_jaccard": f"{token_jaccard(row['evidence_a'], row['evidence_b']):.6f}",
            "oracle_stance_no_gate_relation": no_gate_relation,
            "no_gate_invalid_relation": "true" if row["same_proposition"] != "YES" else "false",
            "no_gate_false_reversal": (
                "true" if row["same_proposition"] != "YES" and no_gate_relation == "STANCE_REVERSED" else "false"
            ),
            "target_proposition_a": row["target_proposition_a"],
            "target_proposition_b": row["target_proposition_b"],
            "comparability_notes": row["comparability_notes"],
        })

    evaluated = [row for row in diagnostic if row["binary_evaluation_label"] != "EXCLUDED_UNCERTAIN"]
    gold = [row["binary_evaluation_label"] for row in evaluated]
    topic_scores = [float(row["candidate_topic_similarity"]) for row in evaluated]
    evidence_scores = [float(row["evidence_tfidf_cosine"]) for row in evaluated]
    speech_scores = [float(row["speech_tfidf_cosine"]) for row in evaluated]
    jaccard_scores = [float(row["evidence_token_jaccard"]) for row in evaluated]

    report = {
        "status": "EXPLORATORY_DEVELOPMENT_PILOT_NOT_HELD_OUT",
        "input_sha256": {
            "semantic_pilot_gold.csv": sha256(gold_path),
            "semantic_pilot_consensus.csv": consensus_hash,
            "candidate_pairs.csv": sha256(candidate_path),
        },
        "label_policy": {
            "positive": "same_proposition=YES -> COMPARABLE",
            "negative": "same_proposition=NO -> INCOMPARABLE",
            "excluded_primary_binary_metrics": "same_proposition=UNCERTAIN",
            "automatic_feature_fields": list(SCORE_INPUT_FIELDS),
            "diagnostic_only_human_fields": ["target_proposition_a", "target_proposition_b", "comparability_notes"],
        },
        "counts": {
            "pilot_pairs": len(rows),
            "binary_evaluated": len(evaluated),
            "comparable": gold.count("COMPARABLE"),
            "incomparable": gold.count("INCOMPARABLE"),
            "uncertain_excluded": len(rows) - len(evaluated),
        },
        "fixed_prediction_baselines": {
            "always_incomparable": binary_metrics(gold, ["INCOMPARABLE"] * len(gold)),
            "always_comparable_no_gate": binary_metrics(gold, ["COMPARABLE"] * len(gold)),
            "candidate_topic_tfidf_threshold_0_10": {
                **binary_metrics(gold, ["COMPARABLE" if score >= 0.10 else "INCOMPARABLE" for score in topic_scores]),
                "warning": "Candidate-retrieval cutoff, not a tuned comparability threshold.",
            },
        },
        "ranking_baselines_without_threshold_tuning": {
            "candidate_topic_tfidf": {"roc_auc": roc_auc(gold, topic_scores), "scores": score_summary(gold, topic_scores)},
            "evidence_tfidf": {"roc_auc": roc_auc(gold, evidence_scores), "scores": score_summary(gold, evidence_scores)},
            "speech_tfidf": {"roc_auc": roc_auc(gold, speech_scores), "scores": score_summary(gold, speech_scores)},
            "evidence_token_jaccard": {"roc_auc": roc_auc(gold, jaccard_scores), "scores": score_summary(gold, jaccard_scores)},
        },
        "oracle_stance_without_comparability_gate_ablation": {
            "description": "Uses adjudicated human stances, then compares polarity for every pair while ignoring same_proposition.",
            "relations_issued": len(rows),
            "invalid_relations_on_noncomparable_or_uncertain_pairs": sum(
                row["no_gate_invalid_relation"] == "true" for row in diagnostic
            ),
            "predicted_reversals": sum(
                row["oracle_stance_no_gate_relation"] == "STANCE_REVERSED" for row in diagnostic
            ),
            "false_reversals_on_noncomparable_or_uncertain_pairs": sum(
                row["no_gate_false_reversal"] == "true" for row in diagnostic
            ),
            "true_reversals_in_gold": sum(row["derived_relation"] == "STANCE_REVERSED" for row in rows),
        },
        "limitations": [
            "The pilot was used to design the protocol and is not a held-out test set.",
            "No threshold was optimized because in-sample tuning would be optimistic.",
            "Two uncertain pairs are excluded from primary binary metrics and retained in diagnostics.",
            "The pilot contains no true stance reversal, so reversal recall cannot be estimated.",
        ],
    }
    manifest = {
        "artifact": "data/annotations/semantic_pilot_gold.csv",
        "sha256": sha256(gold_path),
        "rows": len(rows),
        "unique_pair_ids": len({row["pair_id"] for row in rows}),
        "schema": list(rows[0]),
        "label_source_values": sorted({row["label_source"] for row in rows}),
        "consensus_artifact": "data/annotations/semantic_pilot_consensus.csv",
        "consensus_sha256": consensus_hash,
        "usage": "DEVELOPMENT_PILOT_NOT_FINAL_TEST",
    }
    return report, diagnostic, manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    report, diagnostic, manifest = analyze_pilot(args.root)
    processed = args.root / "data" / "processed"
    write_csv(processed / "comparability_pilot_diagnostics.csv", diagnostic, DIAGNOSTIC_FIELDS)
    (processed / "comparability_pilot_baselines.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (processed / "semantic_pilot_gold_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
