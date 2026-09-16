"""Agreement analysis for completed independent human semantic annotations.

The blank pilot packets intentionally yield no metrics. Run this module only
after both annotators have filled their own CSVs.
"""

from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path

from .semantic_pilot import RESPONSE_FIELDS, read_csv

DETERMINABILITY = {"YES", "NO", "UNCERTAIN"}
SAME_PROPOSITION = {"YES", "NO", "UNCERTAIN"}
STANCE = {"FAVOR", "AGAINST", "UNCERTAIN"}
CONFIDENCE = {"LOW", "MEDIUM", "HIGH"}


def derive_relation(
    stance_determinable_a: str,
    stance_determinable_b: str,
    same_proposition: str,
    stance_a: str,
    stance_b: str,
) -> str:
    """Derive a relation from elementary human judgments, without a model."""
    if "NO" in {stance_determinable_a, stance_determinable_b}:
        return "INSUFFICIENT_EVIDENCE"
    if stance_determinable_a != "YES" or stance_determinable_b != "YES":
        return "RELATION_UNCERTAIN"
    if same_proposition == "NO":
        return "INCOMPARABLE"
    if same_proposition != "YES":
        return "RELATION_UNCERTAIN"
    if stance_a not in {"FAVOR", "AGAINST"} or stance_b not in {"FAVOR", "AGAINST"}:
        return "RELATION_UNCERTAIN"
    return "STANCE_MAINTAINED" if stance_a == stance_b else "STANCE_REVERSED"


def validate_response(row: dict[str, str]) -> bool:
    """Return whether a row is complete; reject invalid or contradictory codes."""
    for side in "ab":
        det = row[f"stance_determinable_{side}"]
        if det and det not in DETERMINABILITY:
            raise ValueError(f"Invalid determinability for {row['pair_id']} {side}: {det}")
        confidence = row[f"determinability_confidence_{side}"]
        if confidence and confidence not in CONFIDENCE:
            raise ValueError("Invalid determinability confidence")
        prop = row[f"target_proposition_{side}"].strip()
        prop_conf = row[f"proposition_confidence_{side}"]
        stance = row[f"stance_{side}"]
        stance_conf = row[f"stance_confidence_{side}"]
        if prop_conf and prop_conf not in CONFIDENCE or stance_conf and stance_conf not in CONFIDENCE:
            raise ValueError("Invalid proposition or stance confidence")
        if stance and stance not in STANCE:
            raise ValueError("Invalid stance")
        if det != "YES" and (prop or prop_conf or stance or stance_conf):
            raise ValueError("Target proposition and stance require determinability YES")
    same = row["same_proposition"]
    if same and same not in SAME_PROPOSITION:
        raise ValueError("Invalid same_proposition value")
    if row["comparability_confidence"] and row["comparability_confidence"] not in CONFIDENCE:
        raise ValueError("Invalid comparability confidence")
    both_yes = row["stance_determinable_a"] == row["stance_determinable_b"] == "YES"
    if not both_yes and (same or row["comparability_confidence"]):
        raise ValueError("Comparability requires both manifestations to be determinable")
    if not all(row[f"stance_determinable_{side}"] in DETERMINABILITY and
               row[f"determinability_confidence_{side}"] in CONFIDENCE for side in "ab"):
        return False
    if any(row[f"stance_determinable_{side}"] == "YES" and not
           (row[f"target_proposition_{side}"].strip() and
            row[f"proposition_confidence_{side}"] in CONFIDENCE and
            row[f"stance_{side}"] in STANCE and row[f"stance_confidence_{side}"] in CONFIDENCE)
           for side in "ab"):
        return False
    if both_yes and not (same in SAME_PROPOSITION and row["comparability_confidence"] in CONFIDENCE):
        return False
    return True


def canonical_answers(row: dict[str, str], display_a_source_side: str) -> dict[str, str]:
    """Restore chronological/source A/B before comparing independent sheets."""
    if display_a_source_side not in {"a", "b"}:
        raise ValueError("Unknown presentation mapping")
    out = dict(row)
    if display_a_source_side == "b":
        for key in RESPONSE_FIELDS:
            if key.endswith("_a"):
                other = key[:-2] + "_b"
                if other in row:
                    out[key], out[other] = row[other], row[key]
    return out


def categorical_agreement(first: list[str], second: list[str]) -> dict:
    """Raw agreement and Cohen's kappa for paired categorical judgments."""
    if len(first) != len(second):
        raise ValueError("Unpaired judgments")
    n = len(first)
    if not n:
        return {"n": 0, "raw_agreement": None, "cohens_kappa": None,
                "annotator_1_counts": {}, "annotator_2_counts": {}, "prevalence_warning": "NO_SHARED_DECISIONS"}
    counts_a, counts_b = collections.Counter(first), collections.Counter(second)
    observed = sum(a == b for a, b in zip(first, second)) / n
    expected = sum(counts_a[k] * counts_b[k] for k in counts_a.keys() | counts_b.keys()) / n**2
    kappa = (observed - expected) / (1 - expected) if expected < 1 else None
    warnings = []
    if expected >= 1:
        warnings.append("KAPPA_UNDEFINED_SINGLE_SHARED_CLASS")
    if max(max(counts_a.values()), max(counts_b.values())) / n >= 0.8:
        warnings.append("DOMINANT_CLASS_AT_LEAST_80_PERCENT")
    if any(count == 1 for count in (*counts_a.values(), *counts_b.values())):
        warnings.append("SINGLETON_CLASS")
    return {"n": n, "raw_agreement": round(observed, 4),
            "cohens_kappa": round(kappa, 4) if kappa is not None else None,
            "annotator_1_counts": dict(sorted(counts_a.items())),
            "annotator_2_counts": dict(sorted(counts_b.items())),
            "prevalence_warning": "|".join(warnings)}


def analyze(first: list[dict[str, str]], second: list[dict[str, str]], reference: list[dict[str, str]]) -> dict | None:
    """Return metrics only after both complete packets have been submitted."""
    ids_1, ids_2, ids_ref = [{row["pair_id"] for row in group} for group in (first, second, reference)]
    if not (ids_1 == ids_2 == ids_ref) or len(first) != len(ids_1) or len(second) != len(ids_2):
        raise ValueError("Annotation packets/reference contain different or duplicate pair IDs")
    if not all([validate_response(row) for row in first + second]):
        return None
    by_first = {r["pair_id"]: r for r in first}
    by_second = {r["pair_id"]: r for r in second}
    det_1, det_2, same_1, same_2, stance_1, stance_2, rel_1, rel_2 = ([] for _ in range(8))
    for ref in reference:
        pid = ref["pair_id"]
        a = canonical_answers(by_first[pid], ref["annotator_1_display_a_source_side"])
        b = canonical_answers(by_second[pid], ref["annotator_2_display_a_source_side"])
        for side in "ab":
            det_1.append(a[f"stance_determinable_{side}"])
            det_2.append(b[f"stance_determinable_{side}"])
            if a[f"stance_determinable_{side}"] == b[f"stance_determinable_{side}"] == "YES":
                stance_1.append(a[f"stance_{side}"])
                stance_2.append(b[f"stance_{side}"])
        if all(a[f"stance_determinable_{side}"] == b[f"stance_determinable_{side}"] == "YES" for side in "ab"):
            same_1.append(a["same_proposition"])
            same_2.append(b["same_proposition"])
        rel_1.append(derive_relation(a["stance_determinable_a"], a["stance_determinable_b"],
                                     a["same_proposition"], a["stance_a"], a["stance_b"]))
        rel_2.append(derive_relation(b["stance_determinable_a"], b["stance_determinable_b"],
                                     b["same_proposition"], b["stance_a"], b["stance_b"]))
    return {"pair_count": len(reference), "determinability": categorical_agreement(det_1, det_2),
            "same_proposition": categorical_agreement(same_1, same_2),
            "stance": categorical_agreement(stance_1, stance_2),
            "derived_relation": categorical_agreement(rel_1, rel_2),
            "proposition_text": "Preserved in both CSVs for manual adjudication; no string kappa or automatic equivalence."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    root = parser.parse_args().root / "data" / "annotations"
    result = analyze(read_csv(root / "semantic_pilot_annotator_1.csv"),
                     read_csv(root / "semantic_pilot_annotator_2.csv"),
                     read_csv(root / "semantic_pilot_reference.csv"))
    if result is None:
        print("PENDING: both independent annotation files must be completed before computing agreement.")
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
