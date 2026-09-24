"""Prepare blind human annotation packets for the expansion (second) round.

Reuses the pilot's exact taxonomy, blinding, and per-annotator seeded
shuffle (`semantic_pilot.annotation_rows`) unchanged, so the two rounds stay
directly comparable. Only pairs with derived_validation_status == VALIDATED
in `expansion_provenance_review.csv` advance. This module never manufactures
a review, semantic response, or gold label.

Run from the repository root:
    PYTHONPATH=src python3 -m voxlab.expansion_semantic_pilot
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .audit import read_jsonl, write_csv
from .expansion import validate_provenance_review
from .semantic_pilot import (annotation_rows, read_csv,
                             write_annotation_if_safe)

EARLIER_LATER_TO_AB = (("earlier", "a"), ("later", "b"))
RESHAPED_SIDE_FIELDS = (
    "source_record_id", "speech_start", "speech_end",
    "evidence_start", "evidence_end", "event_type", "event_date", "speech_text",
)


def reshape_to_pilot_pair(review_row: dict[str, str]) -> dict[str, str]:
    """Rename earlier/later -> a/b and evidence_text -> evidence, so the
    pilot's `blind_side`/`blinding_warning`/`annotation_rows` apply unchanged."""
    out = {"pair_id": review_row["pair_id"], "actor_name": review_row["actor_name"]}
    for side, suffix in EARLIER_LATER_TO_AB:
        for field in RESHAPED_SIDE_FIELDS:
            out[f"{field}_{suffix}"] = review_row[f"{field}_{side}"]
        out[f"evidence_{suffix}"] = review_row[f"evidence_text_{side}"]
    return out


def eligible_expansion_pairs(root: Path) -> list[dict[str, str]]:
    """Validated expansion pairs, reshaped to the pilot's a/b field names."""
    review_rows = read_csv(root / "data" / "annotations" / "expansion_provenance_review.csv")
    _, readiness = validate_provenance_review(root, review_rows)
    validated_ids = {r["pair_id"] for r in readiness if r["derived_validation_status"] == "VALIDATED"}
    by_id = {row["pair_id"]: row for row in review_rows}
    return [reshape_to_pilot_pair(by_id[pid]) for pid in sorted(validated_ids)]


def build(root: Path) -> dict[str, int]:
    eligible = eligible_expansion_pairs(root)
    if not eligible:
        raise ValueError("No validated expansion pair available for annotation")
    lds = {str(row["id"]): row for row in read_jsonl(root / "PublicHearingBR_LDS.jsonl")}
    folder = root / "data" / "annotations"

    packets, mappings = {}, {}
    for annotator in (1, 2):
        packets[annotator], mappings[annotator] = annotation_rows(eligible, lds, annotator)
    if {row["pair_id"] for row in packets[1]} != {row["pair_id"] for row in packets[2]}:
        raise AssertionError("Annotator packets have different pair IDs")
    for annotator in (1, 2):
        write_annotation_if_safe(folder / f"expansion_annotator_{annotator}.csv", packets[annotator])

    reference = []
    for pair in eligible:
        row = dict(pair)
        row.update({
            "chronological_source_side": "a",
            "annotator_1_display_a_source_side": mappings[1][pair["pair_id"]],
            "annotator_2_display_a_source_side": mappings[2][pair["pair_id"]],
        })
        reference.append(row)
    # The reference exposes source_record_id, which is identifying; never ship it blind.
    reference_path = folder / "expansion_semantic_pilot_reference.csv"
    if not reference_path.exists() or read_csv(reference_path) != reference:
        write_csv(reference_path, reference, list(reference[0]))

    readiness_path = root / "data" / "processed" / "expansion_provenance_readiness.json"
    if readiness_path.exists():
        readiness = json.loads(readiness_path.read_text(encoding="utf-8"))
        readiness.update({
            "semantic_packets_generated": True,
            "semantic_packet_pairs": len(eligible),
            "semantic_packet_files": [
                "data/annotations/expansion_annotator_1.csv",
                "data/annotations/expansion_annotator_2.csv",
                "data/annotations/expansion_semantic_pilot_reference.csv",
            ],
        })
        readiness_path.write_text(
            json.dumps(readiness, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    return {
        "validated_pairs": len(eligible),
        "annotator_1_pairs": len(packets[1]),
        "annotator_2_pairs": len(packets[2]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    print(build(parser.parse_args().root))


if __name__ == "__main__":
    main()
