import json
import unittest
from pathlib import Path
from unittest import mock

from voxlab import proposition_canonicalization as pc


ROOT = Path(__file__).resolve().parents[1]


def item(stance_x, stance_y, relation, source="s"):
    return {"source": source, "pair_id": "p", "side": "a", "model": "", "proposition_x": "x",
            "stance_x": stance_x, "proposition_y": "y", "stance_y": stance_y, "consensus_relation": relation,
            "aligned_stance_y": pc.aligned_stance_y({"stance_y": stance_y}, relation)}


class RealignmentTests(unittest.TestCase):

    def test_swaps_only_when_annotator_saw_later_side_first(self):
        preds = [{"pair_id": "p1", "stance_a": "FAVOR", "stance_b": "AGAINST", "same_proposition": "NO"},
                 {"pair_id": "p2", "stance_a": "FAVOR", "stance_b": "AGAINST", "same_proposition": "NO"}]
        ref = [{"pair_id": "p1", "annotator_1_display_a_source_side": "a"},
               {"pair_id": "p2", "annotator_1_display_a_source_side": "b"}]
        out = {r["pair_id"]: r for r in pc.realign_expansion_predictions(preds, ref)}
        self.assertEqual((out["p1"]["stance_a"], out["p1"]["stance_b"]), ("FAVOR", "AGAINST"))
        self.assertEqual((out["p2"]["stance_a"], out["p2"]["stance_b"]), ("AGAINST", "FAVOR"))
        self.assertEqual(out["p2"]["same_proposition"], "NO")
        self.assertEqual(preds[1]["stance_a"], "FAVOR")

    def test_unknown_side_raises(self):
        with self.assertRaises(ValueError):
            pc.realign_expansion_predictions([{"pair_id": "p"}], [{"pair_id": "p", "annotator_1_display_a_source_side": ""}])

    def test_realigned_expansion_texts_match_gold(self):
        """After realignment, the model's side a must be the gold's (chronological) side a."""
        model_rows, gold = pc.model_predictions_chronological(ROOT)
        exp_rows = [r for r in model_rows if r["gold_round"] == "expansion"]
        self.assertEqual(len(exp_rows), 58)
        packet = {r["pair_id"]: r for r in pc.read_csv(ROOT / "data/annotations/expansion_annotator_1.csv")}
        ref = {r["pair_id"]: r for r in pc.read_csv(ROOT / "data/annotations/expansion_semantic_pilot_reference.csv")}
        for pid, row in packet.items():
            chronological_a = row["text_a"] if ref[pid]["annotator_1_display_a_source_side"] == "a" else row["text_b"]
            self.assertEqual(chronological_a.strip(), gold[pid]["text_a"].strip())


class ItemCollectionTests(unittest.TestCase):

    def test_indeterminate_or_empty_is_skipped(self):
        self.assertIsNone(pc._item("s", "p", "a", "", "x", "UNCERTAIN", "y", "FAVOR"))
        self.assertIsNone(pc._item("s", "p", "a", "", "", "FAVOR", "y", "FAVOR"))
        self.assertIsNotNone(pc._item("s", "p", "a", "", "x", "FAVOR", "y", "AGAINST"))

    def test_real_counts_match_documented_agreement(self):
        items = pc.collect_items(ROOT)
        counts = {}
        for i in items:
            counts[i["source"]] = counts.get(i["source"], 0) + 1
        self.assertEqual(counts["human_human_pilot"], 34)
        self.assertEqual(counts["human_human_expansion"], 55)
        self.assertEqual(counts["within_pair_gold"], 12)

    def test_includes_agreements_not_only_disagreements(self):
        items = [i for i in pc.collect_items(ROOT) if i["source"] == "human_human_expansion"]
        self.assertGreater(sum(i["stance_x"] == i["stance_y"] for i in items), 0)
        self.assertEqual(sum(i["stance_x"] != i["stance_y"] for i in items), 8)


class JudgmentTests(unittest.TestCase):

    def test_parse_valid_and_malformed(self):
        self.assertEqual(pc.parse_judgment(json.dumps({"relation": "DIFFERENT"}))["relation"], "DIFFERENT")
        bad = pc.parse_judgment(json.dumps({"relation": "SAME"}))
        self.assertTrue(bad["malformed_output"])
        self.assertEqual(bad["relation"], "UNCERTAIN")
        self.assertTrue(pc.parse_judgment("nope")["malformed_output"])

    def test_consensus_requires_unanimity(self):
        self.assertEqual(pc.consensus_relation(["OPPOSITE_POLARITY", "OPPOSITE_POLARITY"]), "OPPOSITE_POLARITY")
        self.assertEqual(pc.consensus_relation(["OPPOSITE_POLARITY", "EQUIVALENT"]), "UNCERTAIN")

    def test_only_opposite_polarity_flips(self):
        self.assertEqual(pc.aligned_stance_y({"stance_y": "FAVOR"}, "OPPOSITE_POLARITY"), "AGAINST")
        for relation in ("EQUIVALENT", "DIFFERENT", "UNCERTAIN"):
            self.assertEqual(pc.aligned_stance_y({"stance_y": "FAVOR"}, relation), "FAVOR")

    def test_prompt_never_contains_stances(self):
        prompt = pc.render(ROOT, "Prop X", "Prop Y")
        self.assertIn("Prop X", prompt)
        self.assertNotIn("FAVOR ou AGAINST", prompt)


class MetricsTests(unittest.TestCase):

    def test_transitions_capture_hidden_disagreements(self):
        rows = [item("FAVOR", "AGAINST", "OPPOSITE_POLARITY"),   # framing artifact -> agree
                item("FAVOR", "FAVOR", "OPPOSITE_POLARITY"),     # hidden disagreement
                item("FAVOR", "AGAINST", "DIFFERENT"),           # residual, different proposition
                item("FAVOR", "FAVOR", "EQUIVALENT")]
        metrics = pc.source_metrics(rows)
        self.assertEqual(metrics["transitions"], {"disagree->agree": 1, "agree->disagree": 1,
                                                  "disagree->disagree": 1, "agree->agree": 1})
        self.assertEqual(metrics["residual_disagreements_by_relation"], {"OPPOSITE_POLARITY": 1, "DIFFERENT": 1})

    def test_within_pair_flip_turns_maintained_into_reversed(self):
        rows = [item("FAVOR", "FAVOR", "OPPOSITE_POLARITY"), item("FAVOR", "FAVOR", "EQUIVALENT")]
        metrics = pc.within_pair_metrics(rows)
        self.assertEqual(metrics["relation_before"], {"STANCE_MAINTAINED": 2})
        self.assertEqual(metrics["relation_after_alignment"], {"STANCE_REVERSED": 1, "STANCE_MAINTAINED": 1})
        self.assertEqual(len(metrics["opposite_polarity_pairs"]), 1)


class NetworkSafetyTests(unittest.TestCase):

    def test_dry_run_sends_nothing(self):
        with mock.patch("voxlab.synthetic_stress.chat_completion") as call:
            result = pc.run(ROOT, execute=False)
        call.assert_not_called()
        self.assertEqual(result["mode"], "DRY_RUN_NO_REQUESTS_SENT")
        self.assertEqual(result["total_calls"], 2 * result["unique_proposition_pairs"])


if __name__ == "__main__":
    unittest.main()
