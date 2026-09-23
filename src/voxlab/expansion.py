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

from .audit import write_csv
from .semantic_pilot import read_csv

DEFAULT_ACTOR_CAP = 2

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

PROVENANCE_REVIEW_FIELDS = EXPANSION_CANDIDATE_FIELDS + [
    "same_actor_verified", "actor_identity_basis",
    "event_id_earlier", "event_id_later",
    "event_date_earlier", "event_date_later",
    "event_verified_earlier", "event_verified_later",
    "speech_verified_earlier", "speech_verified_later",
    "evidence_verified_earlier", "evidence_verified_later",
    "validation_status", "review_notes",
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


def build_provenance_template(expansion_rows: list[dict]) -> list[dict]:
    """Return blank provenance review rows for eligible pairs only."""
    blank = {f: "" for f in [
        "same_actor_verified", "actor_identity_basis",
        "event_id_earlier", "event_id_later",
        "event_date_earlier", "event_date_later",
        "event_verified_earlier", "event_verified_later",
        "speech_verified_earlier", "speech_verified_later",
        "evidence_verified_earlier", "evidence_verified_later",
        "validation_status", "review_notes",
    ]}
    return [
        {**{field: row.get(field, "") for field in EXPANSION_CANDIDATE_FIELDS}, **blank}
        for row in expansion_rows
        if row["eligible_for_expansion"] == "true"
    ]


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

    template = build_provenance_template(expansion_rows)
    write_csv(out_annotations / "expansion_provenance_review.csv", template, PROVENANCE_REVIEW_FIELDS)

    print(json.dumps(funnel, ensure_ascii=False, indent=2))
    print(f"\nPilot sanity check ({len(sanity)} gold pairs):")
    for r in sanity:
        print(f"  {r['pair_id']} tfidf={r['tfidf_similarity']} retrieved@0.10={r['retrieved_at_threshold_0_10']}")


if __name__ == "__main__":
    main()
