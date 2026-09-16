"""Prepare a blind human annotation pilot from two documentary reviews.

The second review is an input. This module never manufactures a review,
semantic response, or gold label. Run from the repository root with
``PYTHONPATH=src python3 -m voxlab.semantic_pilot``.
"""

from __future__ import annotations

import argparse
import csv
import random
import re
from pathlib import Path

from .audit import normalize_actor, read_jsonl, write_csv

EVENT_TYPES = {
    "Audiência Pública": "PUBLIC_HEARING",
    "Reunião de Comparecimento de Ministro(a)": "MINISTER_APPEARANCE",
    "Audiência Pública e Deliberação": "PUBLIC_HEARING_WITH_DELIBERATION",
    "Seminário": "SEMINAR",
}
SEEDS = {1: 4311, 2: 9877}
REVIEW_COLUMNS = ("event", "date", "actor", "speech", "evidence")
RESPONSE_FIELDS = [
    "stance_determinable_a", "stance_determinable_b",
    "target_proposition_a", "target_proposition_b", "same_proposition",
    "stance_a", "stance_b",
    "determinability_confidence_a", "determinability_confidence_b",
    "proposition_confidence_a", "proposition_confidence_b",
    "comparability_confidence", "stance_confidence_a", "stance_confidence_b",
    "annotation_notes_a", "annotation_notes_b", "comparability_notes",
]
DISPLAY_FIELDS = [
    "pair_id", "event_a", "date_a", "topic_a", "text_a", "context_before_a", "evidence_a", "context_after_a",
    "event_b", "date_b", "topic_b", "text_b", "context_before_b", "evidence_b", "context_after_b",
    "blinding_warning",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def first_review_values(pair: dict[str, str], side: str) -> dict[str, str]:
    return {
        "event": pair[f"event_verified_{side}"],
        "date": pair[f"hearing_date_verified_{side}"],
        "actor": pair[f"actor_verified_{side}"],
        "speech": pair[f"speech_verified_{side}"],
        "evidence": pair[f"evidence_verified_{side}"],
    }


def agreement_status(first: dict[str, str], second: dict[str, str]) -> str:
    """Compare documentary decisions without replacing either review."""
    if all(first[k] == second[k] == "true" for k in REVIEW_COLUMNS):
        return "AGREE_VALID"
    if any({first[k], second[k]} == {"true", "false"} for k in REVIEW_COLUMNS):
        return "DISAGREE"
    if any(first[k] == second[k] == "false" for k in REVIEW_COLUMNS):
        return "AGREE_INVALID"
    return "UNKNOWN"


def compare_reviews(pairs: list[dict[str, str]], reviews: list[dict[str, str]]) -> list[dict[str, str]]:
    """Return one comparison per side of each initially validated pair."""
    keys = [(r["pair_id"], r["side"]) for r in reviews]
    if len(keys) != len(set(keys)):
        raise ValueError("Duplicate pair side in second provenance review")
    lookup = dict(zip(keys, reviews))
    expected = {(p["pair_id"], side) for p in pairs if p["validation_status"] == "VALIDATED" for side in "ab"}
    if set(lookup) != expected:
        raise ValueError("Second provenance review must cover exactly both sides of every initially validated pair")
    output = []
    for pair in pairs:
        if pair["validation_status"] != "VALIDATED":
            continue
        for side in "ab":
            review = lookup[(pair["pair_id"], side)]
            if review["source_record_id"] != pair[f"source_record_id_{side}"]:
                raise ValueError("Second review source record mismatch")
            first = first_review_values(pair, side)
            second = {key: review[f"{key}_confirmed"] for key in REVIEW_COLUMNS}
            if any(value not in {"true", "false", "unknown"} for value in (*first.values(), *second.values())):
                raise ValueError("Documentary judgments must be true, false, or unknown")
            output.append({"pair_id": pair["pair_id"], "side": side,
                           "source_record_id": review["source_record_id"],
                           **{f"review_1_{key}": first[key] for key in REVIEW_COLUMNS},
                           **{f"review_2_{key}": second[key] for key in REVIEW_COLUMNS},
                           "agreement_status": agreement_status(first, second),
                           "review_2_reviewer": review["reviewer"],
                           "review_2_confidence": review["reviewer_confidence"],
                           "review_2_notes": review["reviewer_notes"]})
    return output


def eligible_pairs(pairs: list[dict[str, str]], comparisons: list[dict[str, str]]) -> list[dict[str, str]]:
    by_pair: dict[str, dict[str, str]] = {}
    for row in comparisons:
        by_pair.setdefault(row["pair_id"], {})[row["side"]] = row["agreement_status"]
    return [pair for pair in pairs if pair["validation_status"] == "VALIDATED" and
            by_pair.get(pair["pair_id"], {}).get("a") ==
            by_pair.get(pair["pair_id"], {}).get("b") == "AGREE_VALID"]


def blind_side(pair: dict[str, str], source_side: str, lds: dict[str, dict]) -> dict[str, str]:
    """Preserve the complete original turn and separately expose its evidence."""
    rid = pair[f"source_record_id_{source_side}"]
    transcript = lds[rid]["transcricao"]
    speech_start = int(pair[f"speech_start_{source_side}"])
    speech_end = int(pair[f"speech_end_{source_side}"])
    evidence_start = int(pair[f"evidence_start_{source_side}"])
    evidence_end = int(pair[f"evidence_end_{source_side}"])
    if not speech_start <= evidence_start < evidence_end <= speech_end:
        raise ValueError("Evidence lies outside speech")
    speech = transcript[speech_start:speech_end]
    evidence = transcript[evidence_start:evidence_end]
    if speech != pair[f"speech_text_{source_side}"] or evidence != pair[f"evidence_{source_side}"]:
        raise ValueError("Transcript offsets no longer reconstruct the reviewed text")
    before = transcript[speech_start:evidence_start]
    after = transcript[evidence_end:speech_end]
    return {"event": EVENT_TYPES.get(pair[f"event_type_{source_side}"], "OTHER"),
            "date": pair[f"event_date_{source_side}"],
            "topic": lds[rid]["metadados"]["assunto"],
            "text": speech, "context_before": before, "evidence": evidence,
            "context_after": after}


def blinding_warning(pair: dict[str, str], sides: tuple[dict[str, str], dict[str, str]]) -> str:
    """Flag likely incidental identifiers without editing original speech."""
    actor = normalize_actor(pair["actor_name"])
    name_parts = [part for part in actor.split() if len(part) >= 5]
    combined = " ".join(item["topic"] + " " + item["text"] for item in sides)
    normalized = normalize_actor(combined)
    warnings = []
    if (actor and actor in normalized) or any(re.search(rf"\b{re.escape(part)}\b", normalized) for part in name_parts):
        warnings.append("POSSIBLE_ACTOR_NAME_IN_ORIGINAL_TEXT")
    if re.search(r"\b(?:Deputad[ao]|Senador(?:a)?|Ministr[oa]|Presidente)\b", combined, re.I):
        warnings.append("POSSIBLE_POLITICAL_ROLE_IN_ORIGINAL_TEXT")
    if re.search(r"\b(?:PT|PL|PSOL|MDB|PSD|PSB|PCdoB|União Brasil|Republicanos|Progressistas)\b", combined):
        warnings.append("POSSIBLE_PARTY_IN_ORIGINAL_TEXT")
    return "|".join(warnings)


def annotation_rows(pairs: list[dict[str, str]], lds: dict[str, dict], annotator: int) -> tuple[list[dict], dict[str, str]]:
    """Shuffle pairs and presentation sides with a documented fixed seed."""
    rng = random.Random(SEEDS[annotator])
    order = list(pairs)
    rng.shuffle(order)
    rows = []
    mapping = {}
    for pair in order:
        source_a = "b" if rng.getrandbits(1) else "a"
        source_b = "a" if source_a == "b" else "b"
        a, b = blind_side(pair, source_a, lds), blind_side(pair, source_b, lds)
        mapping[pair["pair_id"]] = source_a
        row = {"pair_id": pair["pair_id"],
               **{f"{key}_a": value for key, value in a.items()},
               **{f"{key}_b": value for key, value in b.items()},
               "blinding_warning": blinding_warning(pair, (a, b)),
               **{key: "" for key in RESPONSE_FIELDS}}
        rows.append(row)
    return rows, mapping


def write_annotation_if_safe(path: Path, rows: list[dict]) -> None:
    """Never overwrite a person's responses or silently change their packet."""
    if path.exists():
        if read_csv(path) != rows:
            raise FileExistsError(f"Existing annotation file differs from generated packet: {path}")
        return
    write_csv(path, rows, DISPLAY_FIELDS + RESPONSE_FIELDS)


def build(root: Path) -> dict[str, int]:
    folder = root / "data" / "annotations"
    pairs = read_csv(folder / "pilot_pairs_validated.csv")
    reviews = read_csv(folder / "provenance_review_2.csv")
    comparisons = compare_reviews(pairs, reviews)
    eligible = eligible_pairs(pairs, comparisons)
    if not eligible:
        raise ValueError("No pair survived both documentary reviews")
    lds = {str(row["id"]): row for row in read_jsonl(root / "PublicHearingBR_LDS.jsonl")}
    packets, mappings = {}, {}
    for annotator in (1, 2):
        packets[annotator], mappings[annotator] = annotation_rows(eligible, lds, annotator)
    if {row["pair_id"] for row in packets[1]} != {row["pair_id"] for row in packets[2]}:
        raise AssertionError("Annotator packets have different pair IDs")
    for annotator in (1, 2):
        write_annotation_if_safe(folder / f"semantic_pilot_annotator_{annotator}.csv", packets[annotator])
    comparison_lookup = {(r["pair_id"], r["side"]): r for r in comparisons}
    reference = []
    for pair in eligible:
        row = dict(pair)
        row.update({"event_type_code_a": EVENT_TYPES.get(pair["event_type_a"], "OTHER"),
                    "event_type_code_b": EVENT_TYPES.get(pair["event_type_b"], "OTHER"),
                    "topic_a": lds[pair["source_record_id_a"]]["metadados"]["assunto"],
                    "topic_b": lds[pair["source_record_id_b"]]["metadados"]["assunto"],
                    "chronological_source_side": "a",
                    "annotator_1_display_a_source_side": mappings[1][pair["pair_id"]],
                    "annotator_2_display_a_source_side": mappings[2][pair["pair_id"]]})
        for side in "ab":
            comparison = comparison_lookup[(pair["pair_id"], side)]
            row[f"review_2_status_{side}"] = comparison["agreement_status"]
            row[f"review_2_notes_{side}"] = comparison["review_2_notes"]
            for key in REVIEW_COLUMNS:
                row[f"review_2_{key}_{side}"] = comparison[f"review_2_{key}"]
        reference.append(row)
    # The reference can contain identifying details; do not include it in blind files.
    reference_path = folder / "semantic_pilot_reference.csv"
    if not reference_path.exists() or read_csv(reference_path) != reference:
        # The annotation packets were checked above and still have blank responses.
        write_csv(reference_path, reference, list(reference[0]))
    write_csv(folder / "provenance_agreement.csv", comparisons, list(comparisons[0]))
    eligible_rows = [{"pair_id": p["pair_id"],
                      "event_type_a": EVENT_TYPES.get(p["event_type_a"], "OTHER"),
                      "event_type_b": EVENT_TYPES.get(p["event_type_b"], "OTHER"),
                      "provenance_status": "AGREE_VALID_BOTH_SIDES"} for p in eligible]
    write_csv(folder / "semantic_pilot_eligible_pairs.csv", eligible_rows,
              ["pair_id", "event_type_a", "event_type_b", "provenance_status"])
    return {"initially_validated": sum(p["validation_status"] == "VALIDATED" for p in pairs),
            "reviewed_sides": len(comparisons),
            "disagreed_sides": sum(r["agreement_status"] == "DISAGREE" for r in comparisons),
            "eligible_pairs": len(eligible)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    print(build(parser.parse_args().root))


if __name__ == "__main__":
    main()
