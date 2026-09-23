import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from voxlab.agreement import (analyze, canonical_answers, categorical_agreement,
                              check_packet_integrity, compare_pair_rows,
                              derive_relation, read_annotation_csv,
                              validate_response, write_adjudication_queue)
from voxlab.audit import write_csv
from voxlab.semantic_pilot import DISPLAY_FIELDS, RESPONSE_FIELDS, read_csv


ROOT = Path(__file__).resolve().parents[1]


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

    def test_windows_1252_semicolon_csv_is_read_without_rewriting(self):
        with TemporaryDirectory() as folder:
            file = Path(folder) / "annotator.csv"
            header = ";".join(DISPLAY_FIELDS + RESPONSE_FIELDS)
            values = ["p"] + [""] * (len(DISPLAY_FIELDS + RESPONSE_FIELDS) - 1)
            values[(DISPLAY_FIELDS + RESPONSE_FIELDS).index("annotation_notes_a")] = "ação"
            file.write_bytes((header + "\n" + ";".join(values) + "\n").encode("cp1252"))
            self.assertEqual(read_annotation_csv(file)[0]["annotation_notes_a"], "ação")

    def test_filled_packets_match_original_text_after_presentation_normalization(self):
        folder = ROOT / "data/annotations"
        packets = {number: read_annotation_csv(folder / f"semantic_pilot_annotator_{number}.csv") for number in (1, 2)}
        reference = read_csv(folder / "semantic_pilot_reference.csv")
        check_packet_integrity(ROOT, packets, reference)
        changed = {number: [dict(row) for row in rows] for number, rows in packets.items()}
        changed[1][0]["text_a"] = "Alterado"
        with self.assertRaises(ValueError):
            check_packet_integrity(ROOT, changed, reference)

    def test_pair_comparison_keeps_target_propositions_for_adjudication(self):
        a = complete_row("p", "FAVOR", "AGAINST")
        b = complete_row("p", "AGAINST", "FAVOR")
        ref = [{"pair_id": "p", "actor_name": "Pessoa", "event_date_a": "2024-01-01",
                "event_date_b": "2024-02-01", "event_type_code_a": "PUBLIC_HEARING",
                "event_type_code_b": "PUBLIC_HEARING", "evidence_a": "A", "evidence_b": "B",
                "annotator_1_display_a_source_side": "a", "annotator_2_display_a_source_side": "b"}]
        row = compare_pair_rows([a], [b], ref)[0]
        self.assertEqual(row["target_proposition_1_a"], a["target_proposition_a"])
        self.assertEqual(row["target_proposition_2_a"], b["target_proposition_b"])
        self.assertEqual(row["derived_relation_disagreement"], "false")

    def test_adjudication_queue_does_not_overwrite_human_decision(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "queue.csv"
            comparison = [{"pair_id": "p", "adjudication_reasons": "FREE_TEXT_PROPOSITION_REVIEW"}]
            write_adjudication_queue(path, comparison)
            rows = read_csv(path)
            rows[0]["adjudication_status"] = "RESOLVED"
            write_csv(path, rows, list(rows[0]))
            write_adjudication_queue(path, comparison)
            self.assertEqual(read_csv(path)[0]["adjudication_status"], "RESOLVED")
            with self.assertRaises(FileExistsError):
                write_adjudication_queue(path, [{"pair_id": "p", "adjudication_reasons": "CHANGED"}])


if __name__ == "__main__":
    unittest.main()
