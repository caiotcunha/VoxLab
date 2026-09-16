import unittest

from voxlab.agreement import (analyze, canonical_answers, categorical_agreement,
                              derive_relation, validate_response)
from voxlab.semantic_pilot import RESPONSE_FIELDS


def complete_row(pair_id: str, side_a: str = "FAVOR", side_b: str = "FAVOR") -> dict:
    row = {field: "" for field in RESPONSE_FIELDS}
    row.update({"pair_id": pair_id, "stance_determinable_a": "YES", "stance_determinable_b": "YES",
                "target_proposition_a": "O imposto deve subir.", "target_proposition_b": "O imposto deve subir.",
                "same_proposition": "YES", "stance_a": side_a, "stance_b": side_b})
    for field in RESPONSE_FIELDS:
        if "confidence" in field:
            row[field] = "MEDIUM"
    return row


class RelationTests(unittest.TestCase):
    def test_derive_relation_all_requested_branches(self):
        cases = [
            (("NO", "YES", "YES", "", "FAVOR"), "INSUFFICIENT_EVIDENCE"),
            (("UNCERTAIN", "YES", "YES", "", "FAVOR"), "RELATION_UNCERTAIN"),
            (("YES", "YES", "NO", "FAVOR", "AGAINST"), "INCOMPARABLE"),
            (("YES", "YES", "UNCERTAIN", "FAVOR", "FAVOR"), "RELATION_UNCERTAIN"),
            (("YES", "YES", "YES", "FAVOR", "FAVOR"), "STANCE_MAINTAINED"),
            (("YES", "YES", "YES", "AGAINST", "AGAINST"), "STANCE_MAINTAINED"),
            (("YES", "YES", "YES", "FAVOR", "AGAINST"), "STANCE_REVERSED"),
            (("YES", "YES", "YES", "AGAINST", "FAVOR"), "STANCE_REVERSED"),
            (("YES", "YES", "YES", "FAVOR", "UNCERTAIN"), "RELATION_UNCERTAIN"),
        ]
        for args, expected in cases:
            with self.subTest(args=args):
                self.assertEqual(derive_relation(*args), expected)

    def test_blank_packets_do_not_generate_metrics(self):
        blank = {field: "" for field in RESPONSE_FIELDS}
        blank["pair_id"] = "p"
        reference = [{"pair_id": "p", "annotator_1_display_a_source_side": "a",
                      "annotator_2_display_a_source_side": "b"}]
        self.assertIsNone(analyze([blank], [blank], reference))

    def test_presentation_swap_restores_source_sides(self):
        row = complete_row("p", "AGAINST", "FAVOR")
        restored = canonical_answers(row, "b")
        self.assertEqual((restored["stance_a"], restored["stance_b"]), ("FAVOR", "AGAINST"))

    def test_completed_synthetic_packets_get_stage_metrics(self):
        a = complete_row("p", "FAVOR", "AGAINST")
        b = complete_row("p", "AGAINST", "FAVOR")
        ref = [{"pair_id": "p", "annotator_1_display_a_source_side": "a",
                "annotator_2_display_a_source_side": "b"}]
        self.assertTrue(validate_response(a))
        result = analyze([a], [b], ref)
        self.assertEqual(result["derived_relation"]["raw_agreement"], 1.0)
        self.assertEqual(result["stance"]["n"], 2)

    def test_kappa_single_class_reports_prevalence(self):
        result = categorical_agreement(["YES", "YES"], ["YES", "YES"])
        self.assertIsNone(result["cohens_kappa"])
        self.assertIn("KAPPA_UNDEFINED", result["prevalence_warning"])


if __name__ == "__main__":
    unittest.main()
