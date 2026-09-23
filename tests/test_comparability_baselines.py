import unittest
from pathlib import Path

from voxlab.comparability_baselines import (
    SCORE_INPUT_FIELDS,
    analyze_pilot,
    binary_label,
    binary_metrics,
    roc_auc,
)


ROOT = Path(__file__).resolve().parents[1]


class ComparabilityBaselineTests(unittest.TestCase):
    def test_binary_policy_excludes_uncertainty(self):
        self.assertEqual(binary_label("YES"), "COMPARABLE")
        self.assertEqual(binary_label("NO"), "INCOMPARABLE")
        self.assertEqual(binary_label("UNCERTAIN"), "EXCLUDED_UNCERTAIN")

    def test_binary_metrics_use_comparable_as_positive(self):
        metrics = binary_metrics(
            ["COMPARABLE", "COMPARABLE", "INCOMPARABLE", "INCOMPARABLE"],
            ["COMPARABLE", "INCOMPARABLE", "COMPARABLE", "INCOMPARABLE"],
        )
        self.assertEqual(metrics["confusion"], {"tp": 1, "tn": 1, "fp": 1, "fn": 1})
        self.assertEqual(metrics["balanced_accuracy"], 0.5)

    def test_roc_auc_counts_ties_as_half(self):
        self.assertEqual(roc_auc(
            ["COMPARABLE", "INCOMPARABLE", "INCOMPARABLE"], [0.8, 0.2, 0.8]
        ), 0.75)

    def test_human_propositions_are_not_scoring_features(self):
        self.assertNotIn("target_proposition_a", SCORE_INPUT_FIELDS)
        self.assertNotIn("target_proposition_b", SCORE_INPUT_FIELDS)
        self.assertNotIn("comparability_notes", SCORE_INPUT_FIELDS)

    def test_current_pilot_report_is_explicitly_exploratory(self):
        report, diagnostics, manifest = analyze_pilot(ROOT)
        self.assertEqual(report["status"], "EXPLORATORY_DEVELOPMENT_PILOT_NOT_HELD_OUT")
        self.assertEqual(report["counts"], {
            "pilot_pairs": 18, "binary_evaluated": 16, "comparable": 5,
            "incomparable": 11, "uncertain_excluded": 2,
        })
        ablation = report["oracle_stance_without_comparability_gate_ablation"]
        self.assertEqual(ablation["false_reversals_on_noncomparable_or_uncertain_pairs"], 2)
        self.assertEqual(ablation["true_reversals_in_gold"], 0)
        self.assertEqual(len(diagnostics), 18)
        self.assertEqual(manifest["usage"], "DEVELOPMENT_PILOT_NOT_FINAL_TEST")


if __name__ == "__main__":
    unittest.main()
