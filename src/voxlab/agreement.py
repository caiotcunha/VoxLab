"""Agreement analysis for completed independent human semantic annotations.

The blank pilot packets intentionally yield no metrics. Run this module only
after both annotators have filled their own CSVs.
"""

from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import hashlib
import io
import json
from pathlib import Path

from .audit import read_jsonl, write_csv
from .semantic_pilot import DISPLAY_FIELDS, RESPONSE_FIELDS, annotation_rows, read_csv

DETERMINABILITY = {"YES", "NO", "UNCERTAIN"}
SAME_PROPOSITION = {"YES", "NO", "UNCERTAIN"}
STANCE = {"FAVOR", "AGAINST", "UNCERTAIN"}
CONFIDENCE = {"LOW", "MEDIUM", "HIGH"}


def read_annotation_csv(path: Path) -> list[dict[str, str]]:
    """Read UTF-8/comma or a spreadsheet's Windows-1252/semicolon export."""
    content = path.read_bytes()
    try:
        decoded = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        decoded = content.decode("cp1252")
    header = decoded.splitlines()[0]
    if header.startswith("pair_id;"):
        delimiter = ";"
    elif header.startswith("pair_id,"):
        delimiter = ","
    else:
        raise ValueError(f"Unrecognized annotation delimiter/header in {path}")
    rows = list(csv.DictReader(io.StringIO(decoded, newline=""), delimiter=delimiter))
    if not rows or list(rows[0]) != DISPLAY_FIELDS + RESPONSE_FIELDS:
        raise ValueError(f"Annotation columns differ from the pilot template: {path}")
    if any(None in row or any(value is None for value in row.values()) for row in rows):
        raise ValueError(f"Malformed CSV row in {path}")
    return rows


def normalized_display_value(field: str, value: str) -> str:
    """Accept presentation-only newline and spreadsheet date formatting."""
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    if field.startswith("date_") and "/" in value:
        value = dt.datetime.strptime(value, "%d/%m/%Y").date().isoformat()
    return value


def check_packet_integrity(root: Path, packets: dict[int, list[dict[str, str]]], reference: list[dict[str, str]]) -> None:
    """Ensure annotators saw the prepared source text and pair mappings."""
    folder = root / "data" / "annotations"
    ids = {row["pair_id"] for row in reference}
    source_pairs = [row for row in read_csv(folder / "pilot_pairs_validated.csv") if row["pair_id"] in ids]
    lds = {str(row["id"]): row for row in read_jsonl(root / "PublicHearingBR_LDS.jsonl")}
    for annotator, packet in packets.items():
        generated, mapping = annotation_rows(source_pairs, lds, annotator)
        if [row["pair_id"] for row in packet] != [row["pair_id"] for row in generated]:
            raise ValueError(f"Pair IDs/order changed in annotator {annotator} packet")
        by_ref = {row["pair_id"]: row for row in reference}
        for actual, expected in zip(packet, generated):
            pid = actual["pair_id"]
            if by_ref[pid][f"annotator_{annotator}_display_a_source_side"] != mapping[pid]:
                raise ValueError(f"Presentation mapping changed for {pid}")
            for field in DISPLAY_FIELDS:
                if normalized_display_value(field, actual[field]) != normalized_display_value(field, expected[field]):
                    raise ValueError(f"Prepared text/metadata changed in annotator {annotator}, {pid}, {field}")


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


ADJUDICATION_FIELDS = [
    "proposition_equivalent_after_review_a", "proposition_equivalent_after_review_b",
    "adjudicated_stance_determinable_a", "adjudicated_stance_determinable_b",
    "adjudicated_target_proposition_a", "adjudicated_target_proposition_b",
    "adjudicated_same_proposition", "adjudicated_stance_a", "adjudicated_stance_b",
    "adjudication_status", "adjudicator_notes",
]


def compare_pair_rows(first: list[dict[str, str]], second: list[dict[str, str]], reference: list[dict[str, str]]) -> list[dict[str, str]]:
    """Expose both independent judgments in source chronology; leave gold blank."""
    by_first = {row["pair_id"]: row for row in first}
    by_second = {row["pair_id"]: row for row in second}
    output = []
    for ref in reference:
        pid = ref["pair_id"]
        a = canonical_answers(by_first[pid], ref["annotator_1_display_a_source_side"])
        b = canonical_answers(by_second[pid], ref["annotator_2_display_a_source_side"])
        relation_a = derive_relation(a["stance_determinable_a"], a["stance_determinable_b"],
                                     a["same_proposition"], a["stance_a"], a["stance_b"])
        relation_b = derive_relation(b["stance_determinable_a"], b["stance_determinable_b"],
                                     b["same_proposition"], b["stance_a"], b["stance_b"])
        row = {"pair_id": pid, "actor_name_reference_only": ref["actor_name"],
               "annotator_1_display_a_source_side": ref["annotator_1_display_a_source_side"],
               "annotator_2_display_a_source_side": ref["annotator_2_display_a_source_side"],
               "event_date_a": ref["event_date_a"], "event_date_b": ref["event_date_b"],
               "event_type_a": ref["event_type_code_a"], "event_type_b": ref["event_type_code_b"],
               "evidence_a": ref["evidence_a"], "evidence_b": ref["evidence_b"]}
        for annotator, answers in ((1, a), (2, b)):
            for side in "ab":
                for key in ("stance_determinable", "target_proposition", "stance",
                            "determinability_confidence", "proposition_confidence", "stance_confidence", "annotation_notes"):
                    row[f"{key}_{annotator}_{side}"] = answers[f"{key}_{side}"]
            for key in ("same_proposition", "comparability_confidence", "comparability_notes"):
                row[f"{key}_{annotator}"] = answers[key]
        row["derived_relation_1"], row["derived_relation_2"] = relation_a, relation_b
        det_sides = [side for side in "ab" if a[f"stance_determinable_{side}"] != b[f"stance_determinable_{side}"]]
        stance_sides = [side for side in "ab" if a[f"stance_determinable_{side}"] == b[f"stance_determinable_{side}"] == "YES"
                        and a[f"stance_{side}"] != b[f"stance_{side}"]]
        same_diff = (a["same_proposition"] != b["same_proposition"] if
                     all(a[f"stance_determinable_{side}"] == b[f"stance_determinable_{side}"] == "YES" for side in "ab")
                     else False)
        row.update({"determinability_disagreement_sides": "|".join(det_sides),
                    "stance_disagreement_sides": "|".join(stance_sides),
                    "same_proposition_disagreement": "true" if same_diff else "false",
                    "derived_relation_disagreement": "true" if relation_a != relation_b else "false"})
        reasons = ["FREE_TEXT_PROPOSITION_REVIEW"]
        if det_sides:
            reasons.append("DETERMINABILITY_DISAGREEMENT")
        if same_diff:
            reasons.append("COMPARABILITY_DISAGREEMENT")
        if stance_sides:
            reasons.append("STANCE_DISAGREEMENT")
        if relation_a != relation_b:
            reasons.append("RELATION_DISAGREEMENT")
        row["adjudication_reasons"] = "|".join(reasons)
        output.append(row)
    return output


def write_adjudication_queue(path: Path, comparison: list[dict[str, str]]) -> None:
    """Create a blank adjudication queue without replacing human decisions."""
    rows = [{**row, **{field: "" for field in ADJUDICATION_FIELDS}} for row in comparison]
    if path.exists():
        prior = read_csv(path)
        if any(old.get(field, "") for old in prior for field in ADJUDICATION_FIELDS):
            if len(prior) != len(rows) or any({key: value for key, value in old.items() if key not in ADJUDICATION_FIELDS} != current
                                              for old, current in zip(prior, comparison)):
                raise FileExistsError("Existing adjudication decisions cannot be overwritten")
            return
        if prior == rows:
            return
    write_csv(path, rows, list(rows[0]))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    project_root = parser.parse_args().root
    root = project_root / "data" / "annotations"
    first = read_annotation_csv(root / "semantic_pilot_annotator_1.csv")
    second = read_annotation_csv(root / "semantic_pilot_annotator_2.csv")
    reference = read_csv(root / "semantic_pilot_reference.csv")
    check_packet_integrity(project_root, {1: first, 2: second}, reference)
    result = analyze(first, second, reference)
    if result is None:
        print("PENDING: both independent annotation files must be completed before computing agreement.")
    else:
        result["input_sha256"] = {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                                  for name in ("semantic_pilot_annotator_1.csv", "semantic_pilot_annotator_2.csv",
                                               "semantic_pilot_reference.csv")}
        comparison = compare_pair_rows(first, second, reference)
        write_csv(root / "semantic_annotation_comparison.csv", comparison, list(comparison[0]))
        write_adjudication_queue(root / "semantic_adjudication_queue.csv", comparison)
        output = project_root / "data" / "processed" / "semantic_agreement.json"
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
