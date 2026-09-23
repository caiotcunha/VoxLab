import collections
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from voxlab.expansion import (
    DEFAULT_ACTOR_CAP,
    EXPANSION_CANDIDATE_FIELDS,
    HUMAN_REVIEW_FIELDS,
    PROVENANCE_REVIEW_FIELDS,
    apply_actor_cap,
    assign_similarity_strata,
    assign_temporal_stratum,
    build_expansion_rows,
    build_provenance_template,
    expansion_speech_candidates,
    find_reusable_provenance,
    is_pilot_excluded,
    load_gold_exclusions,
    pilot_sanity_check,
    validate_provenance_review,
    write_review_template_if_safe,
)
from voxlab.audit import write_csv
from voxlab.semantic_pilot import read_csv


ROOT = Path(__file__).resolve().parents[1]

GOLD_IDS = {
    "263f772b51bf1354", "d4e87de87b4f3431", "24c599750bdd544f", "8f79764e69daadf2",
    "af4d70f0c140e9c9", "d4c07b40fb424a0c", "0138e27cd0f53d95", "2e42e8583aea6939",
    "3459768d16f576e5", "2a22c99d1d3a678c", "ebcdef50abd4418f", "d3769de977ace19d",
    "36fb1e1240a12ac4", "36e4b11ff6345a11", "de54c782d361768c", "4cffd4e8a3906c01",
    "e001ebac1d8033f1", "e6a308550846aa5f",
}


def _make_candidate(pair_id, actor_id, hid_a, hid_b, pub_a, pub_b, sim, gap, topic="regulacao"):
    return {
        "pair_id": pair_id,
        "actor_id": actor_id,
        "actor_name": actor_id.title(),
        "hearing_id_a": hid_a,
        "hearing_id_b": hid_b,
        "publication_date_a": pub_a,
        "publication_date_b": pub_b,
        "gap_publication_days": str(gap),
        "topic_similarity": str(sim),
        "topic_a": topic,
        "topic_b": topic,
        # These silver fields must NOT affect selection; we include them to verify isolation.
        "stance_silver_a": "A FAVOR",
        "stance_silver_b": "CONTRA",
        "proposition_silver_a": "prop",
        "proposition_silver_b": "prop",
    }


class GoldExclusionTests(unittest.TestCase):

    def test_no_gold_pair_id_in_expansion(self):
        gold_ids, gold_canonical = load_gold_exclusions(ROOT)
        candidates = read_csv(ROOT / "data/processed/candidate_pairs.csv")
        rows, _ = build_expansion_rows(candidates, gold_ids, gold_canonical, frozenset(), DEFAULT_ACTOR_CAP)
        eligible = [r for r in rows if r["eligible_for_expansion"] == "true"]
        eligible_ids = {r["pair_id"] for r in eligible}
        self.assertTrue(eligible_ids.isdisjoint(GOLD_IDS),
                        f"Gold pair(s) leaked into expansion: {eligible_ids & GOLD_IDS}")

    def test_ab_and_ba_treated_as_same_pair(self):
        """A pair with swapped hearing IDs must also be excluded when its counterpart is gold."""
        import hashlib
        actor = "test actor"
        hid_a, hid_b = "100", "200"
        # Compute the forward pair_id (same convention as audit.py)
        forward_id = hashlib.sha256(f"{actor}|{hid_a}|{hid_b}".encode()).hexdigest()[:16]
        # Reversed pair: B-A ordering
        reverse_id = hashlib.sha256(f"{actor}|{hid_b}|{hid_a}".encode()).hexdigest()[:16]

        gold_ids = frozenset({forward_id})
        # Build gold_canonical from the forward pair
        from voxlab.expansion import _canonical_hearing_pair
        gold_canonical = frozenset({_canonical_hearing_pair(actor, hid_a, hid_b)})

        # A candidate with reversed order should also be excluded
        reversed_candidate = _make_candidate(reverse_id, actor, hid_b, hid_a,
                                             "2024-01-01", "2024-02-01", 0.5, 31)
        self.assertTrue(is_pilot_excluded(reversed_candidate, gold_ids, gold_canonical))

    def test_pilot_excluded_flag_is_true_for_gold_ids(self):
        gold_ids, gold_canonical = load_gold_exclusions(ROOT)
        candidates = read_csv(ROOT / "data/processed/candidate_pairs.csv")
        rows, _ = build_expansion_rows(candidates, gold_ids, gold_canonical, frozenset(), DEFAULT_ACTOR_CAP)
        by_id = {r["pair_id"]: r for r in rows}
        for gid in GOLD_IDS:
            self.assertIn(gid, by_id, f"Gold pair {gid} not found in output at all")
            self.assertEqual(by_id[gid]["pilot_excluded"], "true",
                             f"Gold pair {gid} should have pilot_excluded=true")
            self.assertEqual(by_id[gid]["eligible_for_expansion"], "false")


class TemporalOrderTests(unittest.TestCase):

    def test_delta_uses_publication_dates_not_event_dates(self):
        """delta_publication_days must come from gap_publication_days, never from an event date."""
        row = _make_candidate("aaa1", "actor x", "1", "2", "2024-01-01", "2024-03-15", 0.3, 74)
        rows, _ = build_expansion_rows([row], frozenset(), frozenset(), frozenset(), 10)
        target = next(r for r in rows if r["pair_id"] == "aaa1")
        self.assertEqual(target["delta_publication_days"], 74)
        # Fields named event_date must NOT be filled by expansion.py
        self.assertNotIn("event_date_earlier", target)
        self.assertNotIn("event_date_later", target)

    def test_earlier_is_a_and_later_is_b(self):
        """hearing_id_earlier corresponds to hearing_id_a (chronologically first by pub date)."""
        row = _make_candidate("bbb2", "actor y", "10", "20", "2023-06-01", "2024-01-01", 0.2, 214)
        rows, _ = build_expansion_rows([row], frozenset(), frozenset(), frozenset(), 10)
        target = next(r for r in rows if r["pair_id"] == "bbb2")
        self.assertEqual(target["hearing_id_earlier"], "10")
        self.assertEqual(target["hearing_id_later"], "20")


class StratificationTests(unittest.TestCase):

    def test_strata_derived_from_distribution_not_fixed_thresholds(self):
        pairs = [
            {"pair_id": f"p{i}", "tfidf_similarity": str(0.10 + i * 0.01)}
            for i in range(10)
        ]
        strata = assign_similarity_strata(pairs)
        counts = collections.Counter(strata.values())
        # With 10 pairs: bottom 6 = LOW, next 3 = MEDIUM, top 1 = HIGH
        self.assertEqual(counts["LOW"], 6)
        self.assertEqual(counts["MEDIUM"], 3)
        self.assertEqual(counts["HIGH"], 1)

    def test_similarity_strata_cover_all_eligible(self):
        gold_ids, gold_canonical = load_gold_exclusions(ROOT)
        candidates = read_csv(ROOT / "data/processed/candidate_pairs.csv")
        rows, funnel = build_expansion_rows(candidates, gold_ids, gold_canonical, frozenset(), DEFAULT_ACTOR_CAP)
        eligible = [r for r in rows if r["pilot_excluded"] == "false"]
        missing_stratum = [r["pair_id"] for r in eligible if not r.get("similarity_stratum")]
        self.assertEqual(missing_stratum, [], "Eligible pairs missing similarity_stratum")

    def test_temporal_stratum_values(self):
        self.assertEqual(assign_temporal_stratum(0), "SHORT")
        self.assertEqual(assign_temporal_stratum(30), "SHORT")
        self.assertEqual(assign_temporal_stratum(31), "MEDIUM")
        self.assertEqual(assign_temporal_stratum(180), "MEDIUM")
        self.assertEqual(assign_temporal_stratum(181), "LONG")
        self.assertEqual(assign_temporal_stratum(1000), "LONG")


class ActorCapTests(unittest.TestCase):

    def test_actor_cap_respected_or_documented(self):
        gold_ids, gold_canonical = load_gold_exclusions(ROOT)
        candidates = read_csv(ROOT / "data/processed/candidate_pairs.csv")
        rows, funnel = build_expansion_rows(candidates, gold_ids, gold_canonical, frozenset(), DEFAULT_ACTOR_CAP)
        eligible = [r for r in rows if r["eligible_for_expansion"] == "true"]
        actor_counts = collections.Counter(r["actor_id"] for r in eligible)
        violators = {actor: count for actor, count in actor_counts.items() if count > DEFAULT_ACTOR_CAP}
        self.assertEqual(violators, {},
                         f"Actor cap exceeded without documentation: {violators}")

    def test_actor_cap_apply_selects_deterministically(self):
        pairs = [
            {"pair_id": f"p{i}", "actor_id": "same actor", "delta_publication_days": 100 + i,
             "tfidf_similarity": str(0.2 - i * 0.01)}
            for i in range(5)
        ]
        selected, capped = apply_actor_cap(pairs, cap=2)
        self.assertEqual(len(selected), 2)
        self.assertEqual(len(capped), 3)
        # Should prefer highest similarity (first two in sorted order)
        self.assertEqual({p["pair_id"] for p in selected}, {"p0", "p1"})

    def test_capped_pairs_not_in_eligible(self):
        gold_ids, gold_canonical = load_gold_exclusions(ROOT)
        candidates = read_csv(ROOT / "data/processed/candidate_pairs.csv")
        rows, _ = build_expansion_rows(candidates, gold_ids, gold_canonical, frozenset(), DEFAULT_ACTOR_CAP)
        capped = [r for r in rows if r["exclusion_reason"] == "actor_cap_exceeded"]
        for r in capped:
            self.assertEqual(r["eligible_for_expansion"], "false")
            self.assertEqual(r["pilot_excluded"], "false")


class SilverGoldIsolationTests(unittest.TestCase):

    def test_no_silver_or_gold_label_field_in_expansion_output(self):
        """expansion_candidate_pairs.csv must not expose stance_silver or relation_gold."""
        forbidden = {"stance_silver_a", "stance_silver_b", "proposition_silver_a",
                     "proposition_silver_b", "relation_gold", "derived_relation",
                     "stance_gold_a", "stance_gold_b"}
        self.assertTrue(forbidden.isdisjoint(set(EXPANSION_CANDIDATE_FIELDS)),
                        f"Forbidden fields in output schema: {forbidden & set(EXPANSION_CANDIDATE_FIELDS)}")

    def test_silver_fields_in_input_do_not_affect_selection(self):
        """Two candidates identical except stance_silver must produce the same selection outcome."""
        base = _make_candidate("x1", "actor z", "10", "20", "2023-01-01", "2023-03-01", 0.25, 59)
        variant = dict(base)
        variant["pair_id"] = "x2"
        variant["hearing_id_a"] = "30"
        variant["hearing_id_b"] = "40"
        variant["stance_silver_a"] = "CONTRA"
        variant["stance_silver_b"] = "A FAVOR"

        rows, _ = build_expansion_rows([base, variant], frozenset(), frozenset(), frozenset(), 10)
        # Both should be eligible — silver label must not influence selection
        eligible_ids = {r["pair_id"] for r in rows if r["eligible_for_expansion"] == "true"}
        self.assertIn("x1", eligible_ids)
        self.assertIn("x2", eligible_ids)


class ProvenanceTemplateTests(unittest.TestCase):

    def test_review_fields_are_empty_in_template(self):
        blank_fields = [
            "same_actor_verified", "actor_identity_basis",
            "event_id_earlier", "event_id_later",
            "event_date_earlier", "event_date_later",
            "event_verified_earlier", "event_verified_later",
            "speech_verified_earlier", "speech_verified_later",
            "evidence_verified_earlier", "evidence_verified_later",
            "validation_status", "review_notes",
        ]
        gold_ids, gold_canonical = load_gold_exclusions(ROOT)
        candidates = read_csv(ROOT / "data/processed/candidate_pairs.csv")
        rows, _ = build_expansion_rows(candidates, gold_ids, gold_canonical, frozenset(), DEFAULT_ACTOR_CAP)
        template = build_provenance_template(rows)
        self.assertTrue(len(template) > 0, "Template should have at least one row")
        for row in template:
            for field in blank_fields:
                self.assertEqual(row[field], "",
                                 f"Field {field} must be empty in provenance template, got: {row[field]!r}")

    def test_template_contains_only_eligible_pairs(self):
        gold_ids, gold_canonical = load_gold_exclusions(ROOT)
        candidates = read_csv(ROOT / "data/processed/candidate_pairs.csv")
        rows, _ = build_expansion_rows(candidates, gold_ids, gold_canonical, frozenset(), DEFAULT_ACTOR_CAP)
        template = build_provenance_template(rows)
        template_ids = {r["pair_id"] for r in template}
        # Must not include gold pairs
        self.assertTrue(template_ids.isdisjoint(GOLD_IDS))
        # Must not include actor-capped pairs
        for row in rows:
            if row["exclusion_reason"] == "actor_cap_exceeded":
                self.assertNotIn(row["pair_id"], template_ids)

    def test_template_source_trace_reconstructs_candidate_summary(self):
        gold_ids, gold_canonical = load_gold_exclusions(ROOT)
        candidates = read_csv(ROOT / "data/processed/candidate_pairs.csv")
        rows, _ = build_expansion_rows(candidates, gold_ids, gold_canonical, frozenset(), DEFAULT_ACTOR_CAP)
        template = build_provenance_template(rows, candidates)
        source = {row["pair_id"]: row for row in candidates}
        for row in template:
            candidate = source[row["pair_id"]]
            self.assertEqual(row["source_record_id_earlier"], candidate["hearing_id_a"])
            self.assertEqual(row["source_actor_index_earlier"], candidate["source_actor_index_a"])
            self.assertEqual(row["source_opinion_index_earlier"], candidate["source_opinion_index_a"])
            self.assertEqual(row["source_summary_earlier"], candidate["text_a"])
            self.assertTrue(all(row[field] == "" for field in HUMAN_REVIEW_FIELDS))

    def test_blank_review_is_reported_as_unresolved(self):
        report, rows = validate_provenance_review(
            ROOT, read_csv(ROOT / "data/annotations/expansion_provenance_review.csv")
        )
        self.assertEqual(report["decision"], "PROVENANCE_REVIEW_REQUIRED")
        self.assertEqual(report["derived_status_distribution"], {"UNRESOLVED": 34})
        self.assertEqual(report["integrity_failures"], 0)
        self.assertTrue(all(row["integrity_status"] == "PENDING" for row in rows))

    def test_template_writer_refuses_to_overwrite_human_review(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "review.csv"
            row = {field: "" for field in PROVENANCE_REVIEW_FIELDS}
            row["pair_id"] = "p"
            write_review_template_if_safe(path, [row])
            saved = read_csv(path)
            saved[0]["same_actor_verified"] = "true"
            write_csv(path, saved, PROVENANCE_REVIEW_FIELDS)
            with self.assertRaises(FileExistsError):
                write_review_template_if_safe(path, [row])

    def test_prior_validated_manifestations_are_reused_only_by_exact_source_key(self):
        review = read_csv(ROOT / "data/annotations/expansion_provenance_review.csv")
        reusable = find_reusable_provenance(ROOT, review)
        self.assertEqual(len(reusable), 8)
        self.assertEqual(len({row["pair_id"] for row in reusable}), 7)
        self.assertTrue(all(row["reuse_status"] == "EXACT_MANIFESTATION_PREVIOUSLY_VALIDATED"
                            for row in reusable))
        self.assertTrue(all(row["speech_text"] and row["evidence_text"] for row in reusable))

    def test_speech_candidates_are_review_aids_with_literal_offsets(self):
        review = read_csv(ROOT / "data/annotations/expansion_provenance_review.csv")
        candidates = expansion_speech_candidates(ROOT, review)
        self.assertTrue(candidates)
        self.assertTrue(all(row["evidence_text"] and int(row["evidence_start"]) < int(row["evidence_end"])
                            for row in candidates))
        self.assertTrue(all("verified" not in key for row in candidates for key in row))


class FunnelConsistencyTests(unittest.TestCase):

    def test_funnel_counts_are_consistent(self):
        gold_ids, gold_canonical = load_gold_exclusions(ROOT)
        candidates = read_csv(ROOT / "data/processed/candidate_pairs.csv")
        rows, funnel = build_expansion_rows(candidates, gold_ids, gold_canonical, frozenset(), DEFAULT_ACTOR_CAP)
        total = funnel["stage_1_total_candidates"]
        excluded = funnel["stage_2_gold_excluded"]
        eligible = funnel["stage_3_eligible_pool"]
        capped = funnel["stage_4_actor_cap_removed"]
        selected = funnel["stage_5_selected_for_expansion"]
        self.assertEqual(total, excluded + eligible, "total != gold_excluded + eligible_pool")
        self.assertEqual(eligible, capped + selected, "eligible_pool != actor_cap_removed + selected")


class PilotSanityCheckTests(unittest.TestCase):

    def test_all_gold_pairs_retrieved_at_threshold_0_10(self):
        """The TF-IDF retriever must recover all 18 gold pairs at threshold 0.10."""
        candidates = read_csv(ROOT / "data/processed/candidate_pairs.csv")
        result = pilot_sanity_check(frozenset(GOLD_IDS), candidates)
        not_retrieved = [r for r in result if r["retrieved_at_threshold_0_10"] != "true"]
        self.assertEqual(not_retrieved, [],
                         f"Gold pairs not retrieved at 0.10: {[r['pair_id'] for r in not_retrieved]}")

    def test_sanity_check_does_not_use_derived_relation(self):
        """pilot_sanity_check output must not contain stance or relation fields."""
        candidates = read_csv(ROOT / "data/processed/candidate_pairs.csv")
        result = pilot_sanity_check(frozenset(GOLD_IDS), candidates)
        for row in result:
            self.assertNotIn("derived_relation", row)
            self.assertNotIn("stance_silver", row)


if __name__ == "__main__":
    unittest.main()
