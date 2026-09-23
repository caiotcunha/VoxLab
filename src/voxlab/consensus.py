"""Validate the human semantic consensus and materialize adjudicated pilot gold.

The source consensus CSV is never rewritten. A malformed pair set (missing or
duplicate IDs) produces a diagnostic report and blocks gold generation.
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

from .agreement import (canonical_answers, derive_relation, normalized_display_value,
                        read_annotation_csv, validate_response)
from .audit import read_jsonl, write_csv
from .semantic_pilot import (DISPLAY_FIELDS, RESPONSE_FIELDS, annotation_rows,
                             blind_side, blinding_warning, read_csv)


GOLD_METADATA_FIELDS = ["derived_relation", "label_source", "consensus_input_sha256"]
GOLD_FIELDS = DISPLAY_FIELDS + RESPONSE_FIELDS + GOLD_METADATA_FIELDS


def read_consensus(path: Path) -> list[dict[str, str]]:
    """Read the consensus as UTF-8 comma CSV while preserving embedded lines."""
    decoded = path.read_bytes().decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(decoded, newline="")))
    if not rows or list(rows[0]) != DISPLAY_FIELDS + RESPONSE_FIELDS:
        raise ValueError("Consensus columns differ from the semantic pilot template")
    if any(None in row or any(value is None for value in row.values()) for row in rows):
        raise ValueError("Malformed consensus CSV row")
    return rows


def repair_cp1252_controls(value: str) -> str:
    """Repair U+0080..U+009F characters introduced by a spreadsheet round-trip."""
    output = []
    for character in value:
        code = ord(character)
        if 0x80 <= code <= 0x9F:
            try:
                character = bytes([code]).decode("cp1252")
            except UnicodeDecodeError:
                pass
        output.append(character)
    return "".join(output)


def iso_date(value: str) -> str:
    if "/" in value:
        return dt.datetime.strptime(value, "%d/%m/%Y").date().isoformat()
    return value


def source_orientation(row: dict[str, str], reference: dict[str, str]) -> str:
    """Return which chronological source side was displayed as consensus A."""
    dates = (iso_date(row["date_a"]), iso_date(row["date_b"]))
    chronological = (reference["event_date_a"], reference["event_date_b"])
    if dates == chronological:
        return "a"
    if dates == chronological[::-1]:
        return "b"
    raise ValueError(f"Consensus dates do not match reference for {row['pair_id']}")


def check_display(row: dict[str, str], templates: dict[int, dict[str, dict[str, str]]]) -> list[tuple[int, str]]:
    """Identify prepared packet rows whose source fields match, independent of claimed ID."""
    matches = []
    for annotator, by_id in templates.items():
        for pair_id, expected in by_id.items():
            fields = [field for field in DISPLAY_FIELDS if field != "pair_id"]
            if all(repair_cp1252_controls(normalized_display_value(field, row[field])) ==
                   normalized_display_value(field, expected[field]) for field in fields):
                matches.append((annotator, pair_id))
    return matches


def relation_for(row: dict[str, str]) -> str:
    return derive_relation(row["stance_determinable_a"], row["stance_determinable_b"],
                           row["same_proposition"], row["stance_a"], row["stance_b"])


def analyze_consensus(root: Path) -> tuple[dict, list[dict[str, str]]]:
    folder = root / "data" / "annotations"
    consensus_path = folder / "semantic_pilot_consensus.csv"
    rows = read_consensus(consensus_path)
    reference_rows = read_csv(folder / "semantic_pilot_reference.csv")
    references = {row["pair_id"]: row for row in reference_rows}
    expected_ids = set(references)
    lds = {str(row["id"]): row for row in read_jsonl(root / "PublicHearingBR_LDS.jsonl")}
    templates = {}
    for annotator in (1, 2):
        generated, _ = annotation_rows(reference_rows, lds, annotator)
        templates[annotator] = {row["pair_id"]: row for row in generated}
    annotated = {annotator: {row["pair_id"]: row for row in read_annotation_csv(
        folder / f"semantic_pilot_annotator_{annotator}.csv")} for annotator in (1, 2)}

    ids = [row["pair_id"] for row in rows]
    counts = collections.Counter(ids)
    unknown = sorted(set(ids) - expected_ids)
    missing = sorted(expected_ids - set(ids))
    duplicates = {pid: count for pid, count in sorted(counts.items()) if count > 1}
    comparison = []
    control_rows = 0
    source_mismatches = []
    for number, row in enumerate(rows, 1):
        if row["pair_id"] not in references:
            continue
        if not validate_response(row):
            raise ValueError(f"Incomplete consensus response for {row['pair_id']}")
        display_matches = check_display(row, templates)
        matched_packets = [annotator for annotator, pair_id in display_matches if pair_id == row["pair_id"]]
        matched_other_ids = sorted({pair_id for _, pair_id in display_matches if pair_id != row["pair_id"]})
        control_repaired = any(repair_cp1252_controls(row[field]) != row[field] for field in DISPLAY_FIELDS)
        control_rows += control_repaired
        if not matched_packets:
            source_mismatches.append({"consensus_row": number, "claimed_pair_id": row["pair_id"],
                                      "content_matches_pair_ids": matched_other_ids})
            comparison.append({
                "consensus_row": number, "pair_id": row["pair_id"],
                "source_integrity_status": "MISMATCH", "content_matches_pair_ids": "|".join(matched_other_ids),
                "duplicate_pair_id": "true" if counts[row["pair_id"]] > 1 else "false",
                "matched_original_packet": "", "display_a_source_side": "",
                "cp1252_control_repair_needed_for_source_check": "true" if control_repaired else "false",
                "stance_determinable_consensus_a": "", "stance_determinable_consensus_b": "",
                "target_proposition_consensus_a": "", "target_proposition_consensus_b": "",
                "same_proposition_consensus": "", "stance_consensus_a": "", "stance_consensus_b": "",
                "derived_relation_consensus": "", "derived_relation_annotator_1": "",
                "derived_relation_annotator_2": "", "consensus_equals_annotator_1_relation": "",
                "consensus_equals_annotator_2_relation": "", "consensus_notes_a": row["annotation_notes_a"],
                "consensus_notes_b": row["annotation_notes_b"],
                "consensus_comparability_notes": row["comparability_notes"],
            })
            continue
        reference = references[row["pair_id"]]
        orientation = source_orientation(row, reference)
        canonical = canonical_answers(row, orientation)
        first = canonical_answers(annotated[1][row["pair_id"]], reference["annotator_1_display_a_source_side"])
        second = canonical_answers(annotated[2][row["pair_id"]], reference["annotator_2_display_a_source_side"])
        consensus_relation, first_relation, second_relation = map(relation_for, (canonical, first, second))
        comparison.append({
            "consensus_row": number, "pair_id": row["pair_id"], "duplicate_pair_id": "true" if counts[row["pair_id"]] > 1 else "false",
            "source_integrity_status": "MATCH", "content_matches_pair_ids": "",
            "matched_original_packet": "|".join(map(str, matched_packets)),
            "display_a_source_side": orientation, "cp1252_control_repair_needed_for_source_check": "true" if control_repaired else "false",
            "stance_determinable_consensus_a": canonical["stance_determinable_a"],
            "stance_determinable_consensus_b": canonical["stance_determinable_b"],
            "target_proposition_consensus_a": canonical["target_proposition_a"],
            "target_proposition_consensus_b": canonical["target_proposition_b"],
            "same_proposition_consensus": canonical["same_proposition"],
            "stance_consensus_a": canonical["stance_a"], "stance_consensus_b": canonical["stance_b"],
            "derived_relation_consensus": consensus_relation,
            "derived_relation_annotator_1": first_relation, "derived_relation_annotator_2": second_relation,
            "consensus_equals_annotator_1_relation": "true" if consensus_relation == first_relation else "false",
            "consensus_equals_annotator_2_relation": "true" if consensus_relation == second_relation else "false",
            "consensus_notes_a": canonical["annotation_notes_a"], "consensus_notes_b": canonical["annotation_notes_b"],
            "consensus_comparability_notes": canonical["comparability_notes"],
        })

    valid_comparison = [row for row in comparison if row["source_integrity_status"] == "MATCH"]
    row_relations = collections.Counter(row["derived_relation_consensus"] for row in valid_comparison)
    by_id: dict[str, list[dict[str, str]]] = collections.defaultdict(list)
    for row in valid_comparison:
        by_id[row["pair_id"]].append(row)
    duplicate_class_consistent = {pid: len({row["derived_relation_consensus"] for row in group}) == 1
                                  for pid, group in by_id.items() if len(group) > 1}
    valid_unique = {pid: group[0]["derived_relation_consensus"] for pid, group in by_id.items()
                    if len({row["derived_relation_consensus"] for row in group}) == 1}
    unique_relations = collections.Counter(valid_unique.values())
    valid_unique_rows = [group[0] for group in by_id.values()
                         if len({row["derived_relation_consensus"] for row in group}) == 1]
    determinability = collections.Counter(row[f"stance_determinable_consensus_{side}"]
                                          for row in valid_unique_rows for side in "ab")
    same_proposition = collections.Counter(row["same_proposition_consensus"] for row in valid_unique_rows)
    stances = collections.Counter(row[f"stance_consensus_{side}"] for row in valid_unique_rows for side in "ab")
    unambiguous = [row for row in valid_comparison if counts[row["pair_id"]] == 1]
    comparison_with_both = sum(row["consensus_equals_annotator_1_relation"] ==
                               row["consensus_equals_annotator_2_relation"] == "true" for row in unambiguous)
    comparison_with_first_only = sum(row["consensus_equals_annotator_1_relation"] == "true" and
                                     row["consensus_equals_annotator_2_relation"] == "false" for row in unambiguous)
    comparison_with_second_only = sum(row["consensus_equals_annotator_1_relation"] == "false" and
                                      row["consensus_equals_annotator_2_relation"] == "true" for row in unambiguous)
    comparison_with_neither = sum(row["consensus_equals_annotator_1_relation"] ==
                                  row["consensus_equals_annotator_2_relation"] == "false" for row in unambiguous)
    blocking = []
    if missing:
        blocking.append("MISSING_PAIR_ID")
    if duplicates:
        blocking.append("DUPLICATE_PAIR_ID")
    if unknown:
        blocking.append("UNKNOWN_PAIR_ID")
    if source_mismatches:
        blocking.append("SOURCE_CONTENT_MISMATCH")
    report = {
        "input_sha256": hashlib.sha256(consensus_path.read_bytes()).hexdigest(),
        "expected_pairs": len(expected_ids), "physical_consensus_rows": len(rows),
        "unique_known_pair_ids": len(set(ids) & expected_ids), "missing_pair_ids": missing,
        "duplicate_pair_ids": duplicates, "unknown_pair_ids": unknown,
        "source_content_mismatches": source_mismatches,
        "blocking_issues": blocking, "valid_for_gold_generation": not blocking,
        "all_responses_complete_and_schema_valid": len(comparison) == len(rows) and not unknown,
        "all_display_text_matches_claimed_pair": not source_mismatches and len(comparison) == len(rows) and not unknown,
        "source_valid_consensus_rows": len(valid_comparison),
        "rows_with_recoverable_cp1252_control_characters": control_rows,
        "valid_source_row_relation_distribution": dict(sorted(row_relations.items())),
        "relation_distribution": dict(sorted(unique_relations.items())),
        "determinability_side_distribution": dict(sorted(determinability.items())),
        "same_proposition_distribution": dict(sorted(same_proposition.items())),
        "stance_side_distribution": dict(sorted(stances.items())),
        "valid_consensus_pair_count": len(valid_unique),
        "duplicate_relation_class_consistent": duplicate_class_consistent,
        "consensus_relation_alignment": {
            "consensus_equals_both_annotators": comparison_with_both,
            "consensus_equals_annotator_1_only": comparison_with_first_only,
            "consensus_equals_annotator_2_only": comparison_with_second_only,
            "consensus_equals_neither": comparison_with_neither,
        },
        "interpretation": (
            "Blocking integrity issues prevent generation of an adjudicated gold dataset."
            if blocking else
            "Validated human consensus covers every expected pair and is ready for adjudicated pilot gold."
        ),
    }
    return report, comparison


def build_gold_rows(root: Path, report: dict) -> list[dict[str, str]]:
    """Build chronological, source-clean rows only from a validated human consensus."""
    if not report["valid_for_gold_generation"]:
        raise ValueError("Consensus integrity checks failed; gold generation is blocked")

    folder = root / "data" / "annotations"
    consensus = {row["pair_id"]: row for row in read_consensus(folder / "semantic_pilot_consensus.csv")}
    reference_rows = read_csv(folder / "semantic_pilot_reference.csv")
    lds = {str(row["id"]): row for row in read_jsonl(root / "PublicHearingBR_LDS.jsonl")}
    gold = []
    for reference in reference_rows:
        pair_id = reference["pair_id"]
        received = consensus[pair_id]
        canonical = canonical_answers(received, source_orientation(received, reference))
        side_a = blind_side(reference, "a", lds)
        side_b = blind_side(reference, "b", lds)
        row = {
            "pair_id": pair_id,
            **{f"{key}_a": value for key, value in side_a.items()},
            **{f"{key}_b": value for key, value in side_b.items()},
            "blinding_warning": blinding_warning(reference, (side_a, side_b)),
            **{field: canonical[field] for field in RESPONSE_FIELDS},
            "derived_relation": relation_for(canonical),
            "label_source": "HUMAN_CONSENSUS",
            "consensus_input_sha256": report["input_sha256"],
        }
        gold.append(row)
    return gold


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    root = parser.parse_args().root
    report, comparison = analyze_consensus(root)
    write_csv(root / "data" / "annotations" / "semantic_consensus_comparison.csv", comparison, list(comparison[0]))
    if report["valid_for_gold_generation"]:
        gold = build_gold_rows(root, report)
        gold_path = root / "data" / "annotations" / "semantic_pilot_gold.csv"
        write_csv(gold_path, gold, GOLD_FIELDS)
        report["gold_dataset"] = {
            "path": str(gold_path.relative_to(root)),
            "pair_count": len(gold),
            "label_source": "HUMAN_CONSENSUS",
            "sha256": hashlib.sha256(gold_path.read_bytes()).hexdigest(),
        }
    output = root / "data" / "processed" / "semantic_consensus_analysis.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
