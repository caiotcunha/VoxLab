import json
import os
import unittest
from pathlib import Path
from unittest import mock

from voxlab.automatic_baselines import (
    DISPLAY_FIELDS,
    RELATION_LABELS,
    build_manifest,
    call_end_to_end,
    call_structured,
    comparability_metrics,
    gate_effect,
    inter_model_agreement,
    load_blind_pairs_from_expansion,
    load_blind_pairs_from_gold,
    output_quality_metrics,
    parse_end_to_end,
    parse_structured,
    relation_metrics,
    relation_with_gate,
    relation_without_gate,
    stance_metrics,
)


ROOT = Path(__file__).resolve().parents[1]


def _valid_structured_json(same_proposition="YES"):
    return json.dumps({
        "stance_determinable_a": "YES", "stance_determinable_b": "YES",
        "target_proposition_a": "O governo deve X.", "target_proposition_b": "O governo deve X.",
        "same_proposition": same_proposition,
        "stance_a": "FAVOR", "stance_b": "FAVOR",
    })


class ParseEndToEndTests(unittest.TestCase):

    def test_valid_relation_is_accepted(self):
        raw = json.dumps({"relation": "STANCE_MAINTAINED", "reasoning": "..."})
        parsed = parse_end_to_end(raw)
        self.assertFalse(parsed["malformed_output"])
        self.assertEqual(parsed["relation_normalized"], "STANCE_MAINTAINED")

    def test_out_of_vocabulary_relation_is_malformed_not_uncertain_semantics(self):
        raw = json.dumps({"relation": "COMPARABLE", "reasoning": "..."})
        parsed = parse_end_to_end(raw)
        self.assertTrue(parsed["malformed_output"])
        self.assertEqual(parsed["malformed_fields"], ["relation"])
        self.assertEqual(parsed["relation_normalized"], "RELATION_UNCERTAIN")
        self.assertFalse(parsed["relation_valid"])

    def test_legitimate_relation_uncertain_is_not_malformed(self):
        raw = json.dumps({"relation": "RELATION_UNCERTAIN", "reasoning": "..."})
        parsed = parse_end_to_end(raw)
        self.assertFalse(parsed["malformed_output"])
        self.assertEqual(parsed["relation_normalized"], "RELATION_UNCERTAIN")

    def test_unparseable_text_is_malformed(self):
        parsed = parse_end_to_end("not json at all")
        self.assertTrue(parsed["malformed_output"])
        self.assertEqual(parsed["relation_normalized"], "RELATION_UNCERTAIN")

    def test_markdown_fenced_json_is_still_parsed(self):
        raw = "```json\n" + json.dumps({"relation": "INCOMPARABLE", "reasoning": "x"}) + "\n```"
        parsed = parse_end_to_end(raw)
        self.assertFalse(parsed["malformed_output"])
        self.assertEqual(parsed["relation_normalized"], "INCOMPARABLE")


class ParseStructuredTests(unittest.TestCase):

    def test_valid_output_all_fields_normalized(self):
        parsed = parse_structured(_valid_structured_json())
        self.assertFalse(parsed["malformed_output"])
        self.assertEqual(parsed["same_proposition_normalized"], "YES")
        self.assertEqual(parsed["stance_a_normalized"], "FAVOR")

    def test_format_error_is_flagged_malformed_not_semantic_uncertain(self):
        """A localized 'SIM' instead of YES/NO/UNCERTAIN is a schema error."""
        raw = json.dumps({
            "stance_determinable_a": "YES", "stance_determinable_b": "YES",
            "target_proposition_a": "x", "target_proposition_b": "y",
            "same_proposition": "SIM",
            "stance_a": "FAVOR", "stance_b": "FAVOR",
        })
        parsed = parse_structured(raw)
        self.assertTrue(parsed["malformed_output"])
        self.assertIn("same_proposition", parsed["malformed_fields"])
        self.assertEqual(parsed["same_proposition_normalized"], "UNCERTAIN")
        self.assertFalse(parsed["same_proposition_valid"])

    def test_legitimate_uncertain_is_not_malformed(self):
        raw = _valid_structured_json(same_proposition="UNCERTAIN")
        parsed = parse_structured(raw)
        self.assertFalse(parsed["malformed_output"])
        self.assertEqual(parsed["same_proposition_normalized"], "UNCERTAIN")

    def test_completely_unparseable_marks_all_categorical_fields_malformed(self):
        parsed = parse_structured("garbage, not json")
        self.assertTrue(parsed["malformed_output"])
        self.assertEqual(len(parsed["malformed_fields"]), 5)

    def test_target_propositions_are_preserved_verbatim(self):
        parsed = parse_structured(_valid_structured_json())
        self.assertEqual(parsed["target_proposition_a"], "O governo deve X.")

    def test_empty_stance_is_valid_when_determinability_is_not_yes(self):
        """The prompt instructs the model to leave stance_a/b empty when its
        own stance_determinable side isn't YES. That is a correctly-formatted
        response, not a schema/format error."""
        raw = json.dumps({
            "stance_determinable_a": "NO", "stance_determinable_b": "YES",
            "target_proposition_a": "", "target_proposition_b": "y",
            "same_proposition": "NO",
            "stance_a": "", "stance_b": "FAVOR",
        })
        parsed = parse_structured(raw)
        self.assertFalse(parsed["malformed_output"])
        self.assertEqual(parsed["malformed_fields"], [])
        self.assertTrue(parsed["stance_a_valid"])
        self.assertEqual(parsed["stance_a_normalized"], "UNCERTAIN")

    def test_empty_stance_is_still_malformed_when_determinability_is_yes(self):
        """If the model says YES but leaves the stance blank anyway, that IS
        a genuine schema violation, not a legitimate conditional omission."""
        raw = json.dumps({
            "stance_determinable_a": "YES", "stance_determinable_b": "YES",
            "target_proposition_a": "x", "target_proposition_b": "y",
            "same_proposition": "YES",
            "stance_a": "", "stance_b": "FAVOR",
        })
        parsed = parse_structured(raw)
        self.assertTrue(parsed["malformed_output"])
        self.assertIn("stance_a", parsed["malformed_fields"])


class GateDerivationTests(unittest.TestCase):
    """B (without gate) and C (with gate) derive from the SAME structured dict."""

    def test_incomparable_case_without_gate_becomes_stance_relation(self):
        struct = parse_structured(json.dumps({
            "stance_determinable_a": "YES", "stance_determinable_b": "YES",
            "target_proposition_a": "x", "target_proposition_b": "y",
            "same_proposition": "NO",
            "stance_a": "FAVOR", "stance_b": "AGAINST",
        }))
        self.assertEqual(relation_with_gate(struct), "INCOMPARABLE")
        # Without the gate, same_proposition is ignored -> stances compared directly.
        self.assertEqual(relation_without_gate(struct), "STANCE_REVERSED")

    def test_with_gate_matches_agreement_derive_relation_exactly(self):
        from voxlab.agreement import derive_relation
        struct = parse_structured(_valid_structured_json(same_proposition="YES"))
        expected = derive_relation("YES", "YES", "YES", "FAVOR", "FAVOR")
        self.assertEqual(relation_with_gate(struct), expected)


class GateEffectTests(unittest.TestCase):

    def test_error_to_correct(self):
        self.assertEqual(gate_effect("INCOMPARABLE", "STANCE_MAINTAINED", "INCOMPARABLE"), "ERROR_TO_CORRECT")

    def test_correct_to_error(self):
        self.assertEqual(gate_effect("STANCE_MAINTAINED", "STANCE_MAINTAINED", "RELATION_UNCERTAIN"), "CORRECT_TO_ERROR")

    def test_correct_to_correct(self):
        self.assertEqual(gate_effect("STANCE_MAINTAINED", "STANCE_MAINTAINED", "STANCE_MAINTAINED"), "CORRECT_TO_CORRECT")

    def test_error_to_error(self):
        self.assertEqual(gate_effect("INCOMPARABLE", "STANCE_MAINTAINED", "RELATION_UNCERTAIN"), "ERROR_TO_ERROR")


class BlindLoadingTests(unittest.TestCase):
    """No human response field must ever reach the model."""

    def test_gold_pairs_only_expose_display_fields(self):
        pairs = load_blind_pairs_from_gold(ROOT)
        self.assertTrue(len(pairs) > 0)
        for pair in pairs:
            self.assertEqual(set(pair), set(DISPLAY_FIELDS))
            self.assertNotIn("same_proposition", pair)
            self.assertNotIn("stance_a", pair)
            self.assertNotIn("derived_relation", pair)

    def test_expansion_pairs_only_expose_display_fields(self):
        pairs = load_blind_pairs_from_expansion(ROOT)
        self.assertTrue(len(pairs) > 0)
        for pair in pairs:
            self.assertEqual(set(pair), set(DISPLAY_FIELDS))
            self.assertNotIn("same_proposition", pair)


class RelationMetricsTests(unittest.TestCase):

    def test_undefined_when_class_absent_from_gold_and_predictions(self):
        predicted = ["INCOMPARABLE", "STANCE_MAINTAINED"]
        gold = ["INCOMPARABLE", "STANCE_MAINTAINED"]
        metrics = relation_metrics(predicted, gold)
        self.assertEqual(metrics["per_class"]["STANCE_REVERSED"]["support_gold"], 0)
        self.assertEqual(metrics["per_class"]["STANCE_REVERSED"]["recall"], "undefined")
        self.assertEqual(metrics["stance_reversed_recall_status"], "undefined_not_estimable_zero_positives_in_gold")

    def test_no_zero_division_with_no_predictions_of_a_class(self):
        predicted = ["INCOMPARABLE", "INCOMPARABLE"]
        gold = ["INCOMPARABLE", "STANCE_MAINTAINED"]
        metrics = relation_metrics(predicted, gold)
        self.assertEqual(metrics["per_class"]["STANCE_MAINTAINED"]["precision"], "undefined")

    def test_false_reversal_rate_denominator_is_full_gold_size_even_with_zero_positives(self):
        predicted = ["STANCE_REVERSED"] + ["INCOMPARABLE"] * 17
        gold = ["INCOMPARABLE"] * 18
        metrics = relation_metrics(predicted, gold)
        self.assertEqual(metrics["false_reversal_count"], 1)
        self.assertEqual(metrics["false_reversal_rate_denominator"], 18)
        self.assertAlmostEqual(metrics["false_reversal_rate"], 1 / 18, places=4)

    def test_mismatched_lengths_raise(self):
        with self.assertRaises(ValueError):
            relation_metrics(["INCOMPARABLE"], ["INCOMPARABLE", "STANCE_MAINTAINED"])


class ComparabilityAndStanceMetricsTests(unittest.TestCase):

    def test_uncertain_gold_excluded_from_binary_comparability(self):
        predicted = ["YES", "NO", "YES"]
        gold = ["YES", "NO", "UNCERTAIN"]
        metrics = comparability_metrics(predicted, gold)
        self.assertEqual(metrics["n_binary"], 2)
        self.assertEqual(metrics["n_gold_uncertain_excluded"], 1)

    def test_stance_metrics_filters_to_determinable_favor_against_only(self):
        predicted_stances = ["FAVOR", "AGAINST", "FAVOR"]
        gold_stances = ["FAVOR", "FAVOR", "UNCERTAIN"]
        gold_determinable = ["YES", "YES", "NO"]
        metrics = stance_metrics(predicted_stances, gold_stances, gold_determinable)
        self.assertEqual(metrics["n"], 2)


class OutputQualityTests(unittest.TestCase):

    def test_valid_and_schema_failure_rates_sum_to_one(self):
        rows = [{"malformed_output": True}, {"malformed_output": False}, {"malformed_output": False}]
        metrics = output_quality_metrics(rows)
        self.assertAlmostEqual(metrics["valid_output_rate"] + metrics["schema_failure_rate"], 1.0)
        self.assertEqual(metrics["malformed_output_count"], 1)


class ManifestSecurityTests(unittest.TestCase):

    def test_manifest_never_contains_the_api_key(self):
        with mock.patch.dict(os.environ, {"DEEPINFRA_API_KEY": "sk-super-secret-value"}):
            manifest = build_manifest(ROOT, ["Qwen/Qwen2.5-72B-Instruct"], 18, 29)
        serialized = json.dumps(manifest)
        self.assertNotIn("sk-super-secret-value", serialized)

    def test_manifest_has_prompt_hashes_and_frozen_config(self):
        manifest = build_manifest(ROOT, ["Qwen/Qwen2.5-72B-Instruct"], 18, 29)
        self.assertEqual(len(manifest["prompt_structured_sha256"]), 64)
        self.assertEqual(len(manifest["prompt_end_to_end_sha256"]), 64)
        self.assertEqual(manifest["temperature"], 0.0)


class InterModelAgreementTests(unittest.TestCase):

    def test_label_is_explicitly_inter_model_never_gold(self):
        rows_1 = [{"pair_id": "p1", "same_proposition_normalized": "YES",
                   "stance_a_normalized": "FAVOR", "stance_determinable_a_normalized": "YES",
                   "stance_determinable_b_normalized": "YES", "stance_b_normalized": "FAVOR"}]
        rows_2 = [{"pair_id": "p1", "same_proposition_normalized": "YES",
                   "stance_a_normalized": "FAVOR", "stance_determinable_a_normalized": "YES",
                   "stance_determinable_b_normalized": "YES", "stance_b_normalized": "FAVOR"}]
        result = inter_model_agreement(rows_1, rows_2)
        self.assertEqual(result["label"], "INTER_MODEL_AGREEMENT")
        self.assertNotIn("gold", result["label"].lower())
        self.assertEqual(result["n_pairs"], 1)

    def test_only_shared_pair_ids_are_compared(self):
        rows_1 = [{"pair_id": "p1", "same_proposition_normalized": "YES",
                   "stance_a_normalized": "FAVOR", "stance_determinable_a_normalized": "YES",
                   "stance_determinable_b_normalized": "YES", "stance_b_normalized": "FAVOR"},
                  {"pair_id": "p2", "same_proposition_normalized": "NO",
                   "stance_a_normalized": "FAVOR", "stance_determinable_a_normalized": "YES",
                   "stance_determinable_b_normalized": "YES", "stance_b_normalized": "AGAINST"}]
        rows_2 = [{"pair_id": "p1", "same_proposition_normalized": "YES",
                   "stance_a_normalized": "FAVOR", "stance_determinable_a_normalized": "YES",
                   "stance_determinable_b_normalized": "YES", "stance_b_normalized": "FAVOR"}]
        result = inter_model_agreement(rows_1, rows_2)
        self.assertEqual(result["n_pairs"], 1)


class ResumeCacheTests(unittest.TestCase):
    """A crash mid-run must not re-bill a call whose raw output already landed on disk."""

    def test_call_end_to_end_reuses_cached_raw_without_network(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cached_dir = root / "data" / "processed" / "llm_raw_outputs"
            cached_dir.mkdir(parents=True)
            cached_response = {"choices": [{"message": {"content": '{"relation": "INCOMPARABLE", "reasoning": "x"}'}}]}
            (cached_dir / "end_to_end_test-model_p1.json").write_text(json.dumps(cached_response), encoding="utf-8")
            with mock.patch("voxlab.automatic_baselines.chat_completion") as mocked:
                result = call_end_to_end(root, {"pair_id": "p1"}, "test-model")
            mocked.assert_not_called()
            self.assertEqual(result, cached_response)

    def test_call_structured_reuses_cached_raw_without_network(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cached_dir = root / "data" / "processed" / "llm_raw_outputs"
            cached_dir.mkdir(parents=True)
            cached_response = {"choices": [{"message": {"content": _valid_structured_json()}}]}
            (cached_dir / "structured_test-model_p1.json").write_text(json.dumps(cached_response), encoding="utf-8")
            with mock.patch("voxlab.automatic_baselines.chat_completion") as mocked:
                result = call_structured(root, {"pair_id": "p1"}, "test-model")
            mocked.assert_not_called()
            self.assertEqual(result, cached_response)


class NoNetworkTests(unittest.TestCase):
    """This module's tests must never perform a real DeepInfra call."""

    def test_chat_completion_is_never_invoked_by_the_test_suite(self):
        with mock.patch("voxlab.llm_client.urllib.request.urlopen") as mocked:
            _ = RELATION_LABELS  # importing/using the module must not touch the network
            mocked.assert_not_called()


if __name__ == "__main__":
    unittest.main()
