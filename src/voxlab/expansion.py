"""Expand the VoxLab candidate pool for a second round of human annotation.

Excludes the 18 gold pilot pairs (A-B and B-A), stratifies the remaining
candidates by topic similarity and temporal gap, applies a per-actor cap,
and produces a blank provenance review template. No silver or gold stance
labels are used for selection.

Run from the repository root:
    PYTHONPATH=src python3 -m voxlab.expansion
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import math
from pathlib import Path

from .audit import read_jsonl, write_csv
from .provenance import (containing_turn, identity_status, parse_turns, read_official_events,
                         speaker_matches_actor, speech_candidates)
from .semantic_pilot import read_csv

DEFAULT_ACTOR_CAP = 2
MIN_VALIDATED_EXPANSION_PAIRS = 20

EXPANSION_CANDIDATE_FIELDS = [
    "pair_id", "actor_id", "actor_name",
    "hearing_id_earlier", "hearing_id_later",
    "publication_date_earlier", "publication_date_later",
    "delta_publication_days",
    "topic_earlier", "topic_later",
    "tfidf_similarity",
    "similarity_stratum", "temporal_stratum",
    "actor_in_gold_pilot",
    "pilot_excluded",
    "eligible_for_expansion", "exclusion_reason",
]

SOURCE_TRACE_FIELDS = [
    f"{field}_{side}"
    for side in ("earlier", "later")
    for field in ("source_record_id", "source_actor_index", "source_opinion_index", "source_summary")
]
SIDE_REVIEW_FIELDS = [
    f"{field}_{side}"
    for side in ("earlier", "later")
    for field in (
        "event_id", "event_source", "event_type", "event_description", "event_start", "event_date",
        "event_verified", "date_verified", "actor_marker_name", "actor_marker_verified",
        "speech_text", "speech_start", "speech_end", "turn_attribution_verified",
        "evidence_text", "evidence_start", "evidence_end", "summary_support_reviewed",
        "speech_verified", "evidence_verified", "side_review_notes",
    )
]
PAIR_REVIEW_FIELDS = [
    "same_actor_verified", "actor_identity_basis", "validation_status", "reviewer", "review_notes",
]
HUMAN_REVIEW_FIELDS = SIDE_REVIEW_FIELDS + PAIR_REVIEW_FIELDS
PROVENANCE_REVIEW_FIELDS = EXPANSION_CANDIDATE_FIELDS + SOURCE_TRACE_FIELDS + HUMAN_REVIEW_FIELDS
READINESS_FIELDS = [
    "pair_id", "declared_validation_status", "derived_validation_status",
    "integrity_status", "missing_review_fields", "issues",
    "distinct_events_verified", "temporal_order_verified", "input_sides_swapped",
]
REUSABLE_PROVENANCE_FIELDS = [
    "pair_id", "side", "source_record_id", "source_actor_index", "source_opinion_index",
    "prior_pair_id", "prior_side", "reuse_status", "event_id", "event_source", "event_type",
    "event_description", "event_start", "event_date", "actor_marker_name",
    "speech_text", "speech_start", "speech_end", "evidence_text", "evidence_start", "evidence_end",
    "summary_support_reviewed", "review_note",
]


def _canonical_hearing_pair(actor_id: str, hid_a: str, hid_b: str) -> frozenset[str]:
    """Unordered key for (actor, hearing_a, hearing_b) to detect A-B / B-A duplicates."""
    return frozenset({f"{actor_id}|{hid_a}", f"{actor_id}|{hid_b}"})


def load_gold_exclusions(root: Path) -> tuple[frozenset[str], frozenset[frozenset]]:
    """Return the set of gold pair_ids and the set of canonical hearing pairs to exclude."""
    gold_path = root / "data" / "annotations" / "semantic_pilot_gold.csv"
    candidates_path = root / "data" / "processed" / "candidate_pairs.csv"

    gold_ids: set[str] = set()
    if gold_path.exists():
        for row in read_csv(gold_path):
            gold_ids.add(row["pair_id"])

    canonical_pairs: set[frozenset] = set()
    if candidates_path.exists():
        for row in read_csv(candidates_path):
            if row["pair_id"] in gold_ids:
                canonical_pairs.add(
                    _canonical_hearing_pair(row["actor_id"], row["hearing_id_a"], row["hearing_id_b"])
                )
    return frozenset(gold_ids), frozenset(canonical_pairs)


def is_pilot_excluded(row: dict, gold_ids: frozenset[str], gold_canonical: frozenset[frozenset]) -> bool:
    if row["pair_id"] in gold_ids:
        return True
    rev_id = hashlib.sha256(
        f"{row['actor_id']}|{row['hearing_id_b']}|{row['hearing_id_a']}".encode()
    ).hexdigest()[:16]
    if rev_id in gold_ids:
        return True
    canonical = _canonical_hearing_pair(row["actor_id"], row["hearing_id_a"], row["hearing_id_b"])
    return canonical in gold_canonical


def assign_similarity_strata(pairs: list[dict]) -> dict[str, str]:
    """Assign LOW/MEDIUM/HIGH by quantiles of the actual distribution.

    Uses 60th and 90th percentile cuts over the eligible pool so thresholds
    are derived from real data, not fixed values.
    """
    if not pairs:
        return {}
    ordered = sorted(pairs, key=lambda p: (float(p["tfidf_similarity"]), p["pair_id"]))
    n = len(ordered)
    low_cut = math.floor(n * 0.60)
    med_cut = math.floor(n * 0.90)
    strata: dict[str, str] = {}
    for i, p in enumerate(ordered):
        if i < low_cut:
            strata[p["pair_id"]] = "LOW"
        elif i < med_cut:
            strata[p["pair_id"]] = "MEDIUM"
        else:
            strata[p["pair_id"]] = "HIGH"
    return strata


def assign_temporal_stratum(delta_days: int) -> str:
    if delta_days <= 30:
        return "SHORT"
    if delta_days <= 180:
        return "MEDIUM"
    return "LONG"


def load_gold_actor_ids(root: Path) -> frozenset[str]:
    ref_path = root / "data" / "annotations" / "semantic_pilot_reference.csv"
    if not ref_path.exists():
        return frozenset()
    return frozenset(r["actor_id"] for r in read_csv(ref_path))


def apply_actor_cap(
    eligible: list[dict], cap: int
) -> tuple[list[dict], list[dict]]:
    """Select up to `cap` pairs per actor, preferring highest similarity then longest gap.

    Returns (selected, capped_out). Deterministic: ties broken by pair_id.
    """
    sorted_pairs = sorted(
        eligible,
        key=lambda p: (-float(p["tfidf_similarity"]), -int(p["delta_publication_days"]), p["pair_id"]),
    )
    actor_counts: dict[str, int] = collections.defaultdict(int)
    selected: list[dict] = []
    capped_out: list[dict] = []
    for p in sorted_pairs:
        if actor_counts[p["actor_id"]] < cap:
            selected.append(p)
            actor_counts[p["actor_id"]] += 1
        else:
            capped_out.append(p)
    return selected, capped_out


def build_expansion_rows(
    candidates: list[dict],
    gold_ids: frozenset[str],
    gold_canonical: frozenset[frozenset],
    gold_actor_ids: frozenset[str],
    actor_cap: int,
) -> tuple[list[dict], dict]:
    """Build expansion candidate rows and return (rows, funnel_counts).

    Funnel counts record survivorship at each filter stage.
    """
    # Stage 1: all candidates
    total = len(candidates)

    # Stage 2: tag pilot_excluded
    pool: list[dict] = []
    excluded_pilot: list[dict] = []
    for row in candidates:
        base = {
            "pair_id": row["pair_id"],
            "actor_id": row["actor_id"],
            "actor_name": row["actor_name"],
            "hearing_id_earlier": row["hearing_id_a"],
            "hearing_id_later": row["hearing_id_b"],
            "publication_date_earlier": row["publication_date_a"],
            "publication_date_later": row["publication_date_b"],
            "delta_publication_days": int(row["gap_publication_days"]),
            "topic_earlier": row["topic_a"],
            "topic_later": row["topic_b"],
            "tfidf_similarity": row["topic_similarity"],
            "actor_in_gold_pilot": "true" if row["actor_id"] in gold_actor_ids else "false",
        }
        if is_pilot_excluded(row, gold_ids, gold_canonical):
            excluded_pilot.append({**base, "pilot_excluded": "true",
                                   "eligible_for_expansion": "false",
                                   "exclusion_reason": "gold_pilot"})
        else:
            pool.append({**base, "pilot_excluded": "false"})

    eligible_count = len(pool)

    # Stage 3: assign strata to eligible pool
    sim_strata = assign_similarity_strata(pool)
    for p in pool:
        p["similarity_stratum"] = sim_strata[p["pair_id"]]
        p["temporal_stratum"] = assign_temporal_stratum(p["delta_publication_days"])

    # Stage 4: apply actor cap
    selected, capped_out = apply_actor_cap(pool, actor_cap)
    selected_ids = {p["pair_id"] for p in selected}

    final_rows: list[dict] = []
    for p in pool:
        in_sample = p["pair_id"] in selected_ids
        final_rows.append({
            **p,
            "eligible_for_expansion": "true" if in_sample else "false",
            "exclusion_reason": "" if in_sample else "actor_cap_exceeded",
        })

    for p in excluded_pilot:
        final_rows.append({
            **p,
            "similarity_stratum": "",
            "temporal_stratum": "",
        })

    # Sort: eligible first by actor, then similarity desc; excluded after
    final_rows.sort(key=lambda r: (
        r["eligible_for_expansion"] != "true",
        r["pilot_excluded"] == "true",
        r["actor_id"],
        -float(r["tfidf_similarity"]),
    ))

    strata_dist = collections.Counter(p["similarity_stratum"] for p in pool)
    temporal_dist = collections.Counter(p["temporal_stratum"] for p in pool)
    funnel = {
        "stage_1_total_candidates": total,
        "stage_2_gold_excluded": len(excluded_pilot),
        "stage_3_eligible_pool": eligible_count,
        "stage_4_actor_cap_removed": len(capped_out),
        "stage_5_selected_for_expansion": len(selected),
        "actor_cap": actor_cap,
        "similarity_strata_in_eligible_pool": dict(sorted(strata_dist.items())),
        "temporal_strata_in_eligible_pool": dict(sorted(temporal_dist.items())),
        "actors_in_eligible_pool": len({p["actor_id"] for p in pool}),
        "actors_in_selected": len({p["actor_id"] for p in selected}),
        "actors_in_gold_pilot_and_selected": len(
            {p["actor_id"] for p in selected if p["actor_in_gold_pilot"] == "true"}
        ),
        "note_no_gold_silver_labels_used": (
            "Selection depends only on topic_similarity, delta_publication_days, and actor_id. "
            "No stance_silver, relation_gold, or LLM predictions were used."
        ),
    }
    return final_rows, funnel


def pilot_sanity_check(gold_ids: frozenset[str], candidates: list[dict]) -> list[dict]:
    """Retrospectively report TF-IDF retrieval scores for gold pairs.

    Verifies that the current retriever would have recovered each gold pair.
    Gold labels (derived_relation) are NOT used to adjust thresholds.
    """
    by_id = {r["pair_id"]: r for r in candidates}
    results = []
    for pid in sorted(gold_ids):
        if pid in by_id:
            row = by_id[pid]
            sim = float(row["topic_similarity"])
            results.append({
                "pair_id": pid,
                "actor_id": row["actor_id"],
                "tfidf_similarity": row["topic_similarity"],
                "retrieved_at_threshold_0_10": "true" if sim >= 0.10 else "false",
                "retrieved_at_threshold_0_05": "true" if sim >= 0.05 else "false",
                "note": "retrospective_only_no_threshold_optimization",
            })
        else:
            results.append({
                "pair_id": pid,
                "actor_id": "",
                "tfidf_similarity": "not_in_candidates",
                "retrieved_at_threshold_0_10": "false",
                "retrieved_at_threshold_0_05": "false",
                "note": "pair_id_not_found_in_candidate_pairs_csv",
            })
    return results


def build_provenance_template(
    expansion_rows: list[dict], source_candidates: list[dict] | None = None
) -> list[dict]:
    """Return source-traceable review rows, leaving every human decision blank."""
    source_by_id = {row["pair_id"]: row for row in (source_candidates or [])}
    output = []
    for row in expansion_rows:
        if row["eligible_for_expansion"] != "true":
            continue
        source = source_by_id.get(row["pair_id"], {})
        trace = {}
        for review_side, candidate_side in (("earlier", "a"), ("later", "b")):
            trace.update({
                f"source_record_id_{review_side}": source.get(f"hearing_id_{candidate_side}", ""),
                f"source_actor_index_{review_side}": source.get(f"source_actor_index_{candidate_side}", ""),
                f"source_opinion_index_{review_side}": source.get(f"source_opinion_index_{candidate_side}", ""),
                f"source_summary_{review_side}": source.get(f"text_{candidate_side}", ""),
            })
        output.append({
            **{field: row.get(field, "") for field in EXPANSION_CANDIDATE_FIELDS},
            **trace,
            **{field: "" for field in HUMAN_REVIEW_FIELDS},
        })
    return output


MACHINE_GENERATED_IDENTITY_BASIS = {
    "same_name_conflicting_state_metadata",
    "name_match_only_or_roles_not_equivalent",
}


def apply_conservative_identity_check(root: Path, review_rows: list[dict]) -> tuple[list[dict], int]:
    """Fill same_actor_verified/actor_identity_basis with the pilot's validated
    name+role heuristic (`provenance.identity_status`), the same function the
    original 25-pair pilot used for this exact field.

    Runs on a row when the field is blank, or when it still carries this same
    function's own "unknown" output from a prior run (recognized by its exact
    basis string) — so improving the heuristic can re-resolve those rows.
    Never touches a "true"/"false" value or a human-written basis, since those
    are final judgments. Returns (updated_rows, filled_count).
    """
    lds_by_id = {str(r["id"]): r for r in read_jsonl(root / "PublicHearingBR_LDS.jsonl")}

    def name_role(record_id: str, actor_index: str) -> tuple[str, str]:
        record = lds_by_id.get(record_id)
        if not record:
            return "", ""
        actors = record.get("metadados", {}).get("envolvidos", [])
        try:
            actor = actors[int(actor_index)]
        except (ValueError, IndexError, TypeError):
            return "", ""
        return actor.get("nome", ""), actor.get("cargo", "")

    def is_reevaluable(row: dict) -> bool:
        verified = row.get("same_actor_verified", "").strip()
        if not verified:
            return True
        basis = row.get("actor_identity_basis", "").strip()
        return verified == "unknown" and basis in MACHINE_GENERATED_IDENTITY_BASIS

    filled = 0
    updated = []
    for row in review_rows:
        row = dict(row)
        if is_reevaluable(row):
            name_a, role_a = name_role(row.get("source_record_id_earlier", ""),
                                       row.get("source_actor_index_earlier", ""))
            name_b, role_b = name_role(row.get("source_record_id_later", ""),
                                       row.get("source_actor_index_later", ""))
            if name_a and name_b:
                verified, basis = identity_status(name_a, role_a, name_b, role_b)
                if (verified, basis) != (row.get("same_actor_verified", ""), row.get("actor_identity_basis", "")):
                    filled += 1
                row["same_actor_verified"] = verified
                row["actor_identity_basis"] = basis
        updated.append(row)
    return updated, filled


def write_review_template_if_safe(path: Path, rows: list[dict]) -> None:
    """Upgrade a blank template, but never overwrite any human review value."""
    if path.exists():
        prior = read_csv(path)
        if any(row.get(field, "").strip() for row in prior for field in HUMAN_REVIEW_FIELDS):
            raise FileExistsError(f"Human provenance review already started; refusing to overwrite {path}")
    write_csv(path, rows, PROVENANCE_REVIEW_FIELDS)


def _derive_review_status(row: dict, integrity_ok: bool) -> str:
    required = [row.get("same_actor_verified", "")]
    for side in ("earlier", "later"):
        required.extend(row.get(f"{field}_{side}", "") for field in (
            "event_verified", "date_verified", "actor_marker_verified",
            "turn_attribution_verified", "summary_support_reviewed",
            "speech_verified", "evidence_verified",
        ))
    if any(value == "false" for value in required):
        return "INVALID"
    if integrity_ok and required and all(value == "true" for value in required):
        return "VALIDATED"
    if any(value == "true" for value in required):
        return "PARTIALLY_VALIDATED"
    return "UNRESOLVED"


def _normalize_official_metadata(value: str) -> str:
    """Normalize line endings changed by a CSV read/write round trip."""
    return (value or "").replace("\r\n", "\n").replace("\r", "\n")


def validate_provenance_review(root: Path, rows: list[dict]) -> tuple[dict, list[dict]]:
    """Validate documentary claims, literal offsets and readiness for semantic annotation."""
    candidates = {row["pair_id"]: row for row in read_csv(root / "data" / "processed" / "candidate_pairs.csv")}
    expected = {row["pair_id"] for row in read_csv(root / "data" / "processed" / "expansion_candidate_pairs.csv")
                if row["eligible_for_expansion"] == "true"}
    ids = [row["pair_id"] for row in rows]
    if len(ids) != len(set(ids)) or set(ids) != expected:
        raise ValueError("Expansion review must contain each eligible pair exactly once")
    raw = {str(row["id"]): row for row in read_jsonl(root / "PublicHearingBR_LDS.jsonl")}
    official = read_official_events(root)
    allowed_tri = {"", "true", "false", "unknown"}
    readiness = []
    for row in rows:
        pair_id = row["pair_id"]
        source = candidates[pair_id]
        issues = []
        for field in HUMAN_REVIEW_FIELDS:
            if (field.startswith(("event_verified_", "date_verified_", "actor_marker_verified_",
                                  "turn_attribution_verified_", "summary_support_reviewed_",
                                  "speech_verified_", "evidence_verified_")) or field == "same_actor_verified"):
                if row.get(field, "") not in allowed_tri:
                    issues.append(f"INVALID_TRI_VALUE:{field}")
        for review_side, candidate_side in (("earlier", "a"), ("later", "b")):
            expected_trace = {
                f"source_record_id_{review_side}": source[f"hearing_id_{candidate_side}"],
                f"source_actor_index_{review_side}": source[f"source_actor_index_{candidate_side}"],
                f"source_opinion_index_{review_side}": source[f"source_opinion_index_{candidate_side}"],
                f"source_summary_{review_side}": source[f"text_{candidate_side}"],
            }
            for field, expected_value in expected_trace.items():
                if row.get(field, "") != expected_value:
                    issues.append(f"SOURCE_TRACE_MISMATCH:{field}")

            record_id = expected_trace[f"source_record_id_{review_side}"]
            transcript = raw[record_id]["transcricao"]
            event_id = row.get(f"event_id_{review_side}", "")
            if row.get(f"event_verified_{review_side}") == "true":
                event = official.get(event_id)
                if not event:
                    issues.append(f"OFFICIAL_EVENT_NOT_FOUND:{review_side}")
                else:
                    official_values = {
                        f"event_source_{review_side}": event.get("uri", ""),
                        f"event_type_{review_side}": event.get("descricaoTipo", ""),
                        f"event_description_{review_side}": event.get("descricao", ""),
                        f"event_start_{review_side}": event.get("dataHoraInicio", ""),
                        f"event_date_{review_side}": event.get("dataHoraInicio", "")[:10],
                    }
                    for field, expected_value in official_values.items():
                        actual_value = row.get(field, "")
                        if (not actual_value or
                                _normalize_official_metadata(actual_value) !=
                                _normalize_official_metadata(expected_value)):
                            issues.append(f"OFFICIAL_EVENT_METADATA_MISMATCH:{field}")

            speech = row.get(f"speech_text_{review_side}", "")
            evidence = row.get(f"evidence_text_{review_side}", "")
            speech_start, speech_end = row.get(f"speech_start_{review_side}", ""), row.get(f"speech_end_{review_side}", "")
            evidence_start, evidence_end = row.get(f"evidence_start_{review_side}", ""), row.get(f"evidence_end_{review_side}", "")
            if row.get(f"speech_verified_{review_side}") == "true" or row.get(f"evidence_verified_{review_side}") == "true":
                try:
                    ss, se, es, ee = map(int, (speech_start, speech_end, evidence_start, evidence_end))
                except (TypeError, ValueError):
                    issues.append(f"INVALID_OR_MISSING_OFFSETS:{review_side}")
                else:
                    if not (0 <= ss <= es < ee <= se <= len(transcript)):
                        issues.append(f"INVALID_NESTED_SPANS:{review_side}")
                    else:
                        if transcript[ss:se] != speech:
                            issues.append(f"SPEECH_TEXT_OFFSET_MISMATCH:{review_side}")
                        if transcript[es:ee] != evidence:
                            issues.append(f"EVIDENCE_TEXT_OFFSET_MISMATCH:{review_side}")
                        turn = containing_turn(parse_turns(transcript), es, ee)
                        if (not turn or turn.text_start != ss or turn.text_end != se or
                                not speaker_matches_actor(turn.speaker_name, row["actor_name"])):
                            issues.append(f"SPEAKER_TURN_MISMATCH:{review_side}")
                        elif (row.get(f"actor_marker_verified_{review_side}") == "true" and
                              row.get(f"actor_marker_name_{review_side}", "") != turn.speaker_name):
                            issues.append(f"ACTOR_MARKER_NAME_MISMATCH:{review_side}")

        event_ids = [row.get(f"event_id_{side}", "") for side in ("earlier", "later")]
        event_starts = [row.get(f"event_start_{side}", "") for side in ("earlier", "later")]
        distinct = "true" if all(event_ids) and event_ids[0] != event_ids[1] else "false" if all(event_ids) else "unknown"
        if all(event_starts):
            temporal = "true" if event_starts[0] != event_starts[1] else "false"
            input_sides_swapped = "true" if event_starts[0] > event_starts[1] else "false"
        else:
            temporal, input_sides_swapped = "unknown", "unknown"
        if distinct == "false":
            issues.append("SAME_OFFICIAL_EVENT")
        if temporal == "false":
            issues.append("NON_CHRONOLOGICAL_EVENT_DATES")
        core_review = [row.get("same_actor_verified", "")]
        for side in ("earlier", "later"):
            core_review.extend(row.get(f"{field}_{side}", "") for field in (
                "event_verified", "date_verified", "actor_marker_verified", "turn_attribution_verified",
                "summary_support_reviewed", "speech_verified", "evidence_verified",
            ))
        required_review_fields = ["same_actor_verified", "actor_identity_basis", "validation_status", "reviewer"]
        required_review_fields.extend(
            f"{field}_{side}"
            for side in ("earlier", "later")
            for field in (
                "event_verified", "date_verified", "actor_marker_verified",
                "turn_attribution_verified", "summary_support_reviewed",
                "speech_verified", "evidence_verified",
            )
        )
        missing_review_fields = [
            field for field in required_review_fields if not row.get(field, "").strip()
        ]
        if core_review and all(value == "true" for value in core_review) and not row.get("reviewer", "").strip():
            issues.append("MISSING_REVIEWER")
        integrity_ok = not issues and distinct == temporal == "true"
        derived = _derive_review_status(row, integrity_ok)
        if row.get("validation_status", "") and row["validation_status"] != derived:
            issues.append("DECLARED_STATUS_DIFFERS_FROM_DERIVED_STATUS")
            integrity_ok = False
        readiness.append({
            "pair_id": pair_id,
            "declared_validation_status": row.get("validation_status", ""),
            "derived_validation_status": derived,
            "integrity_status": "PASS" if integrity_ok else "PENDING" if not issues else "FAIL",
            "missing_review_fields": "|".join(missing_review_fields),
            "issues": "|".join(issues),
            "distinct_events_verified": distinct,
            "temporal_order_verified": temporal,
            "input_sides_swapped": input_sides_swapped,
        })

    counts = collections.Counter(row["derived_validation_status"] for row in readiness)
    declared_counts = collections.Counter(row.get("validation_status", "") or "BLANK" for row in rows)
    validated = counts["VALIDATED"]
    final_decisions_complete = validated + counts["INVALID"] == len(rows)
    decision = (
        "READY_FOR_EXPANSION_ANNOTATION"
        if final_decisions_complete and validated >= MIN_VALIDATED_EXPANSION_PAIRS
        else "INSUFFICIENT_EXPANSION_CANDIDATES"
        if final_decisions_complete
        else "PROVENANCE_REVIEW_REQUIRED"
    )
    report = {
        "expected_pairs": len(expected),
        "review_rows": len(rows),
        "declared_status_distribution": dict(sorted(declared_counts.items())),
        "derived_status_distribution": dict(sorted(counts.items())),
        "integrity_failures": sum(row["integrity_status"] == "FAIL" for row in readiness),
        "documentary_integrity_failures": sum(
            any(
                issue and issue != "DECLARED_STATUS_DIFFERS_FROM_DERIVED_STATUS"
                for issue in row["issues"].split("|")
            )
            for row in readiness
        ),
        "declared_status_mismatches": sum(
            "DECLARED_STATUS_DIFFERS_FROM_DERIVED_STATUS" in row["issues"].split("|")
            for row in readiness
        ),
        "incomplete_review_rows": sum(bool(row["missing_review_fields"]) for row in readiness),
        "minimum_validated_pairs_for_annotation_round": MIN_VALIDATED_EXPANSION_PAIRS,
        "decision": decision,
        "semantic_packets_generated": False,
    }
    return report, readiness


def find_reusable_provenance(root: Path, review_rows: list[dict]) -> list[dict]:
    """Expose exact manifestations already validated in the first pilot for reviewer reuse."""
    prior = read_csv(root / "data" / "annotations" / "pilot_pairs_validated.csv")
    lookup = {}
    for row in prior:
        if row["validation_status"] != "VALIDATED":
            continue
        for side in "ab":
            if row[f"speech_verified_{side}"] != "true" or row[f"evidence_verified_{side}"] != "true":
                continue
            key = (row[f"source_record_id_{side}"], row[f"source_actor_index_{side}"],
                   row[f"source_opinion_index_{side}"])
            lookup[key] = (row, side)
    output = []
    for review in review_rows:
        for side in ("earlier", "later"):
            key = (review[f"source_record_id_{side}"], review[f"source_actor_index_{side}"],
                   review[f"source_opinion_index_{side}"])
            if key not in lookup:
                continue
            source, prior_side = lookup[key]
            output.append({
                "pair_id": review["pair_id"], "side": side,
                "source_record_id": key[0], "source_actor_index": key[1], "source_opinion_index": key[2],
                "prior_pair_id": source["pair_id"], "prior_side": prior_side,
                "reuse_status": "EXACT_MANIFESTATION_PREVIOUSLY_VALIDATED",
                "event_id": source[f"event_id_{prior_side}"],
                "event_source": source[f"event_source_{prior_side}"],
                "event_type": source[f"event_type_{prior_side}"],
                "event_description": source[f"event_description_{prior_side}"],
                "event_start": source[f"event_start_{prior_side}"],
                "event_date": source[f"event_date_{prior_side}"],
                "actor_marker_name": source[f"actor_marker_name_{prior_side}"],
                "speech_text": source[f"speech_text_{prior_side}"],
                "speech_start": source[f"speech_start_{prior_side}"],
                "speech_end": source[f"speech_end_{prior_side}"],
                "evidence_text": source[f"evidence_{prior_side}"],
                "evidence_start": source[f"evidence_start_{prior_side}"],
                "evidence_end": source[f"evidence_end_{prior_side}"],
                "summary_support_reviewed": source[f"summary_support_reviewed_{prior_side}"],
                "review_note": source[f"review_note_{prior_side}"],
            })
    return output


def expansion_speech_candidates(root: Path, review_rows: list[dict]) -> list[dict]:
    """Rank literal sentences in named turns as review aids, never as verified evidence."""
    raw = {str(row["id"]): row for row in read_jsonl(root / "PublicHearingBR_LDS.jsonl")}
    output = []
    for row in review_rows:
        for side in ("earlier", "later"):
            record_id = row[f"source_record_id_{side}"]
            pseudo = {
                "pair_id": row["pair_id"],
                f"actor_name_{side}": row["actor_name"],
                f"summary_{side}": row[f"source_summary_{side}"],
                f"source_record_id_{side}": record_id,
            }
            output.extend(speech_candidates(pseudo, side, raw[record_id]["transcricao"]))
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--actor-cap", type=int, default=DEFAULT_ACTOR_CAP,
                        help="Maximum pairs per actor in expansion sample (default: 2)")
    args = parser.parse_args()
    if args.actor_cap < 1:
        parser.error("--actor-cap must be >= 1")

    root = args.root
    gold_ids, gold_canonical = load_gold_exclusions(root)
    gold_actor_ids = load_gold_actor_ids(root)
    candidates = read_csv(root / "data" / "processed" / "candidate_pairs.csv")

    expansion_rows, funnel = build_expansion_rows(
        candidates, gold_ids, gold_canonical, gold_actor_ids, args.actor_cap
    )

    sanity = pilot_sanity_check(gold_ids, candidates)
    funnel["pilot_sanity_check"] = {
        "gold_pairs_checked": len(sanity),
        "retrieved_at_threshold_0_10": sum(
            r["retrieved_at_threshold_0_10"] == "true" for r in sanity
        ),
        "retrieved_at_threshold_0_05": sum(
            r["retrieved_at_threshold_0_05"] == "true" for r in sanity
        ),
        "note": "retrospective_only_labels_not_used_for_threshold_choice",
    }

    out_processed = root / "data" / "processed"
    out_annotations = root / "data" / "annotations"

    write_csv(out_processed / "expansion_candidate_pairs.csv", expansion_rows, EXPANSION_CANDIDATE_FIELDS)
    (out_processed / "expansion_funnel.json").write_text(
        json.dumps(funnel, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    template = build_provenance_template(expansion_rows, candidates)
    review_path = out_annotations / "expansion_provenance_review.csv"
    try:
        write_review_template_if_safe(review_path, template)
    except FileExistsError:
        # Preserve submitted human values and continue into validation.
        pass
    review_rows = read_csv(review_path)
    review_rows, identity_filled = apply_conservative_identity_check(root, review_rows)
    if identity_filled:
        write_csv(review_path, review_rows, PROVENANCE_REVIEW_FIELDS)
    review_report, readiness = validate_provenance_review(root, review_rows)
    review_report["identity_fields_auto_filled_this_run"] = identity_filled
    reusable = find_reusable_provenance(root, review_rows)
    speech_review_aids = expansion_speech_candidates(root, review_rows)
    review_report["previously_validated_manifestation_sides_available_for_reuse"] = len(reusable)
    review_report["pairs_with_reusable_provenance"] = len({row["pair_id"] for row in reusable})
    review_report["ranked_speech_candidates_for_manual_review"] = len(speech_review_aids)
    write_csv(out_processed / "expansion_provenance_readiness.csv", readiness, READINESS_FIELDS)
    write_csv(out_processed / "expansion_reusable_provenance.csv", reusable, REUSABLE_PROVENANCE_FIELDS)
    if speech_review_aids:
        write_csv(out_processed / "expansion_speech_candidates.csv", speech_review_aids, list(speech_review_aids[0]))
    (out_processed / "expansion_provenance_readiness.json").write_text(
        json.dumps(review_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(json.dumps(funnel, ensure_ascii=False, indent=2))
    print("\nProvenance review readiness:")
    print(json.dumps(review_report, ensure_ascii=False, indent=2))
    print(f"\nPilot sanity check ({len(sanity)} gold pairs):")
    for r in sanity:
        print(f"  {r['pair_id']} tfidf={r['tfidf_similarity']} retrieved@0.10={r['retrieved_at_threshold_0_10']}")


if __name__ == "__main__":
    main()
