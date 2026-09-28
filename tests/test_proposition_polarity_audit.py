import json
import unittest
from pathlib import Path
from unittest import mock

from voxlab.proposition_polarity_audit import (
    call_polarity_check,
    collect_all_cases,
    human_human_expansion_cases,
    model_vs_gold_cases,
    parse_polarity_response,
    run_audit,
)


ROOT = Path(__file__).resolve().parents[1]


class ParseResponseTests(unittest.TestCase):

    def test_valid_yes_is_not_malformed(self):
        raw = json.dumps({"same_claim_opposite_polarity": "YES", "reasoning": "x"})
        parsed = parse_polarity_response(raw)
        self.assertFalse(parsed["malformed_output"])
        self.assertEqual(parsed["same_claim_opposite_polarity_normalized"], "YES")

    def test_out_of_vocabulary_is_malformed_not_uncertain_semantics(self):
        raw = json.dumps({"same_claim_opposite_polarity": "MAYBE", "reasoning": "x"})
        parsed = parse_polarity_response(raw)
        self.assertTrue(parsed["malformed_output"])
        self.assertEqual(parsed["same_claim_opposite_polarity_normalized"], "UNCERTAIN")

    def test_legitimate_uncertain_is_not_malformed(self):
        raw = json.dumps({"same_claim_opposite_polarity": "UNCERTAIN", "reasoning": "x"})
        parsed = parse_polarity_response(raw)
        self.assertFalse(parsed["malformed_output"])

    def test_unparseable_text_is_malformed(self):
        parsed = parse_polarity_response("not json")
        self.assertTrue(parsed["malformed_output"])


class HumanHumanCaseExtractionTests(unittest.TestCase):

    def test_real_expansion_comparison_yields_known_case_count(self):
        cases = human_human_expansion_cases(ROOT)
        self.assertEqual(len(cases), 8)
        for case in cases:
            self.assertEqual(case["source"], "human_human_expansion")
            self.assertIn(case["side"], ("a", "b"))
            self.assertNotEqual(case["stance_x"], case["stance_y"])

    def test_missing_file_returns_empty_not_error(self):
        with_missing = Path("/nonexistent/root/for/test")
        self.assertEqual(human_human_expansion_cases(with_missing), [])


class ModelVsGoldCaseExtractionTests(unittest.TestCase):

    def test_pilot_and_expansion_case_counts(self):
        pilot = model_vs_gold_cases(
            ROOT, Path("data/processed/gold18_pairwise_analysis.csv"),
            Path("data/annotations/semantic_pilot_gold.csv"), "model_vs_gold_pilot")
        expansion = model_vs_gold_cases(
            ROOT, Path("data/processed/expansion29_model_predictions.csv"),
            Path("data/annotations/expansion_semantic_gold.csv"), "model_vs_gold_expansion")
        self.assertEqual(len(pilot), 9)
        self.assertEqual(len(expansion), 13)
        for case in pilot + expansion:
            self.assertNotEqual(case["stance_x"], case["stance_y"])
            self.assertIn(case["stance_x"], {"FAVOR", "AGAINST"})
            self.assertIn(case["stance_y"], {"FAVOR", "AGAINST"})

    def test_missing_files_return_empty_not_error(self):
        result = model_vs_gold_cases(
            Path("/nonexistent"), Path("a.csv"), Path("b.csv"), "x")
        self.assertEqual(result, [])


class CollectAllCasesTests(unittest.TestCase):

    def test_total_matches_all_three_sources(self):
        cases = collect_all_cases(ROOT)
        self.assertEqual(len(cases), 30)

    def test_never_reads_gold_or_silver_label_fields_beyond_proposition_and_stance(self):
        cases = collect_all_cases(ROOT)
        forbidden = {"derived_relation", "relation_gold", "label_source"}
        for case in cases:
            self.assertTrue(forbidden.isdisjoint(case.keys()))


class ResumeCacheTests(unittest.TestCase):

    def test_call_polarity_check_reuses_cached_raw_without_network(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cached_dir = root / "data" / "processed" / "llm_raw_outputs"
            cached_dir.mkdir(parents=True)
            case = {"pair_id": "p1", "side": "a", "source": "human_human_expansion", "model": "",
                    "proposition_x": "X deve subir", "stance_x": "FAVOR",
                    "proposition_y": "X nao deve subir", "stance_y": "AGAINST"}
            cached_response = {"choices": [{"message": {"content":
                json.dumps({"same_claim_opposite_polarity": "YES", "reasoning": "negacao"})}}]}
            path = cached_dir / "polarity_audit_Qwen_Qwen2.5-72B-Instruct_p1_a_human_human_expansion.json"
            path.write_text(json.dumps(cached_response), encoding="utf-8")
            with mock.patch("voxlab.proposition_polarity_audit.chat_completion") as mocked:
                result = call_polarity_check(root, case)
            mocked.assert_not_called()
            self.assertEqual(result["same_claim_opposite_polarity_normalized"], "YES")


class RunAuditSummaryTests(unittest.TestCase):

    def test_summary_never_treats_diagnostic_as_gold_correction(self):
        """The summary's interpretation text must disclaim itself as diagnostic only."""
        with mock.patch("voxlab.proposition_polarity_audit.call_polarity_check") as mocked:
            mocked.return_value = {"same_claim_opposite_polarity_raw": "YES",
                                   "same_claim_opposite_polarity_valid": True,
                                   "same_claim_opposite_polarity_normalized": "YES",
                                   "malformed_output": False, "reasoning": "x"}
            rows, summary = run_audit(ROOT)
        self.assertEqual(len(rows), 30)
        self.assertIn("never", summary["interpretation"].lower())
        self.assertEqual(summary["total_disagreement_cases_examined"], 30)
        self.assertEqual(sum(s["n"] for s in summary["by_source"].values()), 30)


if __name__ == "__main__":
    unittest.main()
