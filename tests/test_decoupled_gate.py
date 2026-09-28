import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from voxlab import decoupled_gate as dg


ROOT = Path(__file__).resolve().parents[1]


def ext(det="YES", question="Q?", stance="FAVOR"):
    return {"determinable": det, "question": question, "stance": stance, "malformed": False}


def response(text, cost=0.01):
    return {"choices": [{"message": {"content": text}}], "usage": {"estimated_cost": cost}}


class ParsingTests(unittest.TestCase):

    def test_extraction(self):
        parsed = dg.parse_extraction(json.dumps({"stance_determinable": "YES", "target_question": " X? ",
                                                 "stance": "AGAINST"}))
        self.assertEqual((parsed["question"], parsed["stance"], parsed["malformed"]), ("X?", "AGAINST", False))
        self.assertTrue(dg.parse_extraction("no json")["malformed"])
        self.assertTrue(dg.parse_extraction(json.dumps({"stance_determinable": "YES", "stance": ""}))["malformed"])
        self.assertFalse(dg.parse_extraction(json.dumps({"stance_determinable": "NO", "target_question": "",
                                                         "stance": ""}))["malformed"])

    def test_comparison(self):
        self.assertEqual(dg.parse_comparison(json.dumps({"relation": "DIFFERENT"}))["relation"], "DIFFERENT")
        bad = dg.parse_comparison(json.dumps({"relation": "SAME"}))
        self.assertTrue(bad["malformed"])
        self.assertEqual(bad["relation"], "UNCERTAIN")

    def test_empty_content_from_reasoning_model_is_malformed(self):
        self.assertEqual(dg.content({"choices": [{"message": {"content": None}}]}), "")
        self.assertTrue(dg.parse_extraction("")["malformed"])


class DerivationTests(unittest.TestCase):

    def test_opposite_polarity_flips_b_and_keeps_same_question(self):
        rel = dg.decoupled_relation(ext(stance="FAVOR"), ext(stance="FAVOR"), {"relation": "OPPOSITE_POLARITY"})
        self.assertEqual(rel["D_decoupled_gate"], "STANCE_REVERSED")
        self.assertEqual(rel["D_forced_comparability"], "STANCE_MAINTAINED")

    def test_equivalent_and_different(self):
        self.assertEqual(dg.decoupled_relation(ext(), ext(stance="AGAINST"), {"relation": "EQUIVALENT"})
                         ["D_decoupled_gate"], "STANCE_REVERSED")
        self.assertEqual(dg.decoupled_relation(ext(), ext(stance="AGAINST"), {"relation": "DIFFERENT"})
                         ["D_decoupled_gate"], "INCOMPARABLE")
        self.assertEqual(dg.decoupled_relation(ext(), ext(), {"relation": "UNCERTAIN"})
                         ["D_decoupled_gate"], "RELATION_UNCERTAIN")

    def test_undeterminable_side_skips_comparison(self):
        a, b = ext(), ext(det="NO", question="", stance="UNCERTAIN")
        self.assertFalse(dg.needs_comparison(a, b))
        self.assertEqual(dg.decoupled_relation(a, b, None)["D_decoupled_gate"], "INSUFFICIENT_EVIDENCE")

    def test_side_key_depends_only_on_side_content(self):
        pair = {"event_a": "e", "date_a": "d", "topic_a": "t", "text_a": "x",
                "event_b": "e", "date_b": "d", "topic_b": "t", "text_b": "x"}
        self.assertEqual(dg.side_key(dg.side_record(pair, "a")), dg.side_key(dg.side_record(pair, "b")))


class PromptBlindingTests(unittest.TestCase):

    def test_extraction_sees_one_side_and_comparison_sees_no_speech(self):
        side = {"event": "E", "date": "D", "topic": "T", "text": "FALA UNICA"}
        self.assertIn("FALA UNICA", dg.render_extract(ROOT, side))
        compare = dg.render_compare(ROOT, "Pergunta um?", "Pergunta dois?")
        self.assertIn("Pergunta um?", compare)
        self.assertNotIn("Fala literal", compare)


class ItemTests(unittest.TestCase):

    def test_items_cover_gold_and_accepted_counterfactuals(self):
        items = dg.load_items(ROOT)
        kinds = {(i["kind"], i["split"]) for i in items}
        self.assertEqual(len(items), 86)
        self.assertEqual(kinds, {("natural", "dev"), ("natural", "test"), ("synthetic", "dev"), ("synthetic", "test")})


class CallerTests(unittest.TestCase):

    def test_cap_stops_new_calls_but_cache_still_served(self):
        with tempfile.TemporaryDirectory() as tmp:
            caller = dg.Caller(Path(tmp), execute=True, max_cost=0.015)
            with mock.patch("voxlab.decoupled_gate.chat_completion", return_value=response("{}", 0.01)) as call:
                caller.call("extract", "m/x", "k1", "p")
                caller.call("extract", "m/x", "k2", "p")
                with self.assertRaises(dg.BudgetExceeded):
                    caller.call("extract", "m/x", "k3", "p")
                self.assertIsNotNone(caller.call("extract", "m/x", "k1", "p"))
            self.assertEqual(call.call_count, 2)

    def test_big_models_get_room_for_reasoning(self):
        with tempfile.TemporaryDirectory() as tmp:
            caller = dg.Caller(Path(tmp), execute=True, max_cost=1)
            with mock.patch("voxlab.decoupled_gate.chat_completion", return_value=response("{}")) as call:
                caller.call("extract", dg.BIG_MODELS[0], "k", "p")
                caller.call("extract", dg.V1_MODELS[0], "k", "p")
            self.assertEqual(call.call_args_list[0].kwargs["max_tokens"], dg.REASONING_MAX_TOKENS)
            self.assertIsNone(call.call_args_list[1].kwargs["max_tokens"])

    def test_dry_run_sends_nothing(self):
        with mock.patch("voxlab.decoupled_gate.chat_completion") as call:
            result = dg.run(ROOT, execute=False, max_cost=1, models=dg.V1_MODELS + dg.BIG_MODELS)
        call.assert_not_called()
        self.assertEqual(result["mode"], "DRY_RUN_NO_REQUESTS_SENT")


if __name__ == "__main__":
    unittest.main()
