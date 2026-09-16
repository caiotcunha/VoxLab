import csv
import unittest
from pathlib import Path

from voxlab.semantic_pilot import (DISPLAY_FIELDS, RESPONSE_FIELDS, agreement_status,
                                   annotation_rows, blind_side, eligible_pairs, read_csv)


ROOT = Path(__file__).resolve().parents[1]


class SemanticPilotTests(unittest.TestCase):
    def test_second_review_disagreement_excludes_pair(self):
        first = {key: "true" for key in ("event", "date", "actor", "speech", "evidence")}
        second = dict(first, evidence="false")
        self.assertEqual(agreement_status(first, second), "DISAGREE")
        pairs = [{"pair_id": "p", "validation_status": "VALIDATED"}]
        self.assertEqual(eligible_pairs(pairs, [{"pair_id": "p", "side": "a", "agreement_status": "AGREE_VALID"},
                                                {"pair_id": "p", "side": "b", "agreement_status": "DISAGREE"}]), [])

    def test_unknown_review_never_becomes_agreement(self):
        first = {key: "true" for key in ("event", "date", "actor", "speech", "evidence")}
        self.assertEqual(agreement_status(first, dict(first, date="unknown")), "UNKNOWN")

    def test_original_context_reconstructs_full_turn(self):
        pair = {"source_record_id_a": "1", "speech_start_a": "0", "speech_end_a": "21",
                "evidence_start_a": "7", "evidence_end_a": "14", "speech_text_a": "Before evidence after.",
                "evidence_a": "evidence", "event_type_a": "Audiência Pública", "event_date_a": "2024-01-02"}
        lds = {"1": {"transcricao": "Before evidence after.", "metadados": {"assunto": "Tema"}}}
        pair["speech_end_a"] = str(len(lds["1"]["transcricao"]))
        pair["evidence_end_a"] = str(7 + len("evidence"))
        row = blind_side(pair, "a", lds)
        self.assertEqual(row["context_before"] + row["evidence"] + row["context_after"], row["text"])

    def test_generated_blind_packets_same_ids_reproducible_no_answers_or_identifiers(self):
        a = read_csv(ROOT / "data/annotations/semantic_pilot_annotator_1.csv")
        b = read_csv(ROOT / "data/annotations/semantic_pilot_annotator_2.csv")
        self.assertEqual(len(a), len(b))
        self.assertEqual({r["pair_id"] for r in a}, {r["pair_id"] for r in b})
        self.assertNotEqual([r["pair_id"] for r in a], [r["pair_id"] for r in b])
        forbidden = {"actor_name", "actor_role", "party", "uf", "event_id_a", "event_id_b", "stance_silver"}
        self.assertTrue(forbidden.isdisjoint(a[0]))
        self.assertEqual(list(a[0]), DISPLAY_FIELDS + RESPONSE_FIELDS)
        for row in a + b:
            self.assertTrue(all(row[field] == "" for field in RESPONSE_FIELDS))
            for side in "ab":
                self.assertEqual(row[f"context_before_{side}"] + row[f"evidence_{side}"] + row[f"context_after_{side}"],
                                 row[f"text_{side}"])

    def test_randomization_reproducible(self):
        pairs = read_csv(ROOT / "data/annotations/semantic_pilot_reference.csv")
        from voxlab.audit import read_jsonl
        lds = {str(row["id"]): row for row in read_jsonl(ROOT / "PublicHearingBR_LDS.jsonl")}
        first, first_map = annotation_rows(pairs, lds, 1)
        second, second_map = annotation_rows(pairs, lds, 1)
        self.assertEqual(first, second)
        self.assertEqual(first_map, second_map)


if __name__ == "__main__":
    unittest.main()
