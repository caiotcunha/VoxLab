import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from voxlab import question_gate as qg


ROOT = Path(__file__).resolve().parents[1]


class ItemTests(unittest.TestCase):

    def test_splits_follow_gold_round_and_hide_labels(self):
        gold = qg.load_gold(ROOT)
        dev = qg.natural_items(gold, "pilot")
        test = qg.natural_items(gold, "expansion")
        self.assertEqual((len(dev), len(test)), (18, 29))
        self.assertFalse({i["item_id"] for i in dev} & {i["item_id"] for i in test})
        for item in dev + test:
            self.assertEqual(set(item["pair"]), set(qg.DISPLAY_FIELDS))
            self.assertNotIn("derived_relation", item["pair"])

    def test_synthetic_items_are_accepted_only_and_split_by_source(self):
        gold = qg.load_gold(ROOT)
        dev = qg.synthetic_items(ROOT, gold, "pilot")
        test = qg.synthetic_items(ROOT, gold, "expansion")
        self.assertEqual(len(dev) + len(test), 39)
        pilot_ids = {r["pair_id"] for r in gold if r["gold_round"] == "pilot"}
        self.assertTrue(all(i["source_pair_id"] in pilot_ids for i in dev))
        self.assertTrue(all(i["source_pair_id"] not in pilot_ids for i in test))
        self.assertTrue(all(i["pair"]["pair_id"].startswith("syn_") for i in dev + test))

    def test_v1_references_cover_all_natural_pairs(self):
        refs = qg.v1_natural_predictions(ROOT)
        gold = qg.load_gold(ROOT)
        for model in qg.EVALUATED_MODELS:
            for row in gold:
                self.assertIn((model, row["pair_id"]), refs)


class FreezeTests(unittest.TestCase):

    def make_root(self, tmp: str) -> Path:
        root = Path(tmp)
        (root / "prompts").mkdir()
        (root / qg.PROMPT_PATH).write_text("prompt v2", encoding="utf-8")
        (root / qg.OUT_DIR).mkdir(parents=True)
        return root

    def test_test_split_blocked_without_freeze(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError):
                qg.check_freeze(self.make_root(tmp))

    def test_changed_prompt_blocks_test_split(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_root(tmp)
            sha = qg.prompt_sha256(root / qg.PROMPT_PATH)
            (root / qg.OUT_DIR / "question_gate_dev_metrics.json").write_text(json.dumps({"prompt_sha256": sha}))
            with mock.patch.object(qg, "_git_commit", return_value="x"):
                qg.freeze(root)
            qg.check_freeze(root)
            (root / qg.PROMPT_PATH).write_text("prompt v2 edited", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                qg.check_freeze(root)

    def test_freeze_requires_dev_results_with_same_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_root(tmp)
            with self.assertRaises(RuntimeError):
                qg.freeze(root)
            (root / qg.OUT_DIR / "question_gate_dev_metrics.json").write_text(json.dumps({"prompt_sha256": "old"}))
            with self.assertRaises(RuntimeError):
                qg.freeze(root)


class MetricsTests(unittest.TestCase):

    def test_natural_metrics_compare_v1_and_v2(self):
        rows = [{"model": "m", "gold_relation": "STANCE_MAINTAINED", "gold_same_proposition": "YES",
                 "v1_A_end_to_end": "STANCE_MAINTAINED", "v1_C_structured_with_gate": "INCOMPARABLE",
                 "v2_C_question_gate": "STANCE_MAINTAINED", "v2_same_proposition": "YES", "v2_malformed_output": False},
                {"model": "m", "gold_relation": "INCOMPARABLE", "gold_same_proposition": "NO",
                 "v1_A_end_to_end": "STANCE_MAINTAINED", "v1_C_structured_with_gate": "INCOMPARABLE",
                 "v2_C_question_gate": "INCOMPARABLE", "v2_same_proposition": "NO", "v2_malformed_output": False}]
        metrics = qg.natural_metrics(rows)["m"]
        self.assertEqual(metrics["relation"]["v2_C_question_gate"]["accuracy"], 1.0)
        self.assertEqual(metrics["relation"]["v1_C_structured_with_gate"]["accuracy"], 0.5)
        self.assertEqual(metrics["v2_comparability"]["recall_YES"], 1.0)


class NetworkSafetyTests(unittest.TestCase):

    def test_dry_run_sends_nothing(self):
        with mock.patch("voxlab.synthetic_stress.chat_completion") as call:
            result = qg.run_split(ROOT, "dev", execute=False)
        call.assert_not_called()
        self.assertEqual(result["mode"], "DRY_RUN_NO_REQUESTS_SENT")
        self.assertEqual(result["calls"], 2 * (18 + 16))

    def test_prompt_keeps_v1_schema(self):
        prompt = (ROOT / qg.PROMPT_PATH).read_text(encoding="utf-8")
        for key in ("stance_determinable_a", "target_proposition_b", "same_proposition", "stance_b"):
            self.assertIn(f'"{key}"', prompt)


if __name__ == "__main__":
    unittest.main()
