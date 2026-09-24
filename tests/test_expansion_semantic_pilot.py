import unittest
import json
from pathlib import Path

from voxlab.audit import read_jsonl
from voxlab.expansion_semantic_pilot import eligible_expansion_pairs, reshape_to_pilot_pair
from voxlab.semantic_pilot import DISPLAY_FIELDS, RESPONSE_FIELDS, annotation_rows, read_csv


ROOT = Path(__file__).resolve().parents[1]

KNOWN_INVALID_EXPANSION_PAIRS = {
    "3d382d16e23d6fe6", "e8fa709c49d4cf21", "7d09d414bbbcee5f",
    "57626a6d567bbd22", "d336204af6200b5c",
}


def _review_row(pair_id="p1", actor_name="Fulano de Tal"):
    row = {"pair_id": pair_id, "actor_name": actor_name}
    for side in ("earlier", "later"):
        row.update({
            f"source_record_id_{side}": "1" if side == "earlier" else "2",
            f"speech_start_{side}": "0",
            f"speech_end_{side}": "20",
            f"evidence_start_{side}": "5",
            f"evidence_end_{side}": "10",
            f"event_type_{side}": "Audiência Pública",
            f"event_date_{side}": "2024-01-01",
            f"speech_text_{side}": "aaaaabbbbbcccccddddd",
            f"evidence_text_{side}": "bbbbb",
        })
    return row


class ReshapeTests(unittest.TestCase):

    def test_earlier_later_map_to_a_b(self):
        reshaped = reshape_to_pilot_pair(_review_row())
        self.assertEqual(reshaped["source_record_id_a"], "1")
        self.assertEqual(reshaped["source_record_id_b"], "2")
        self.assertNotIn("source_record_id_earlier", reshaped)
        self.assertNotIn("source_record_id_later", reshaped)

    def test_evidence_text_field_renamed_to_evidence(self):
        """The pilot's blind_side reads evidence_{side}, not evidence_text_{side}."""
        reshaped = reshape_to_pilot_pair(_review_row())
        self.assertEqual(reshaped["evidence_a"], "bbbbb")
        self.assertEqual(reshaped["evidence_b"], "bbbbb")
        self.assertNotIn("evidence_text_a", reshaped)

    def test_reshaped_pair_is_directly_consumable_by_pilot_blind_side(self):
        from voxlab.semantic_pilot import blind_side
        reshaped = reshape_to_pilot_pair(_review_row())
        lds = {"1": {"transcricao": "aaaaabbbbbcccccddddd", "metadados": {"assunto": "Tema"}},
               "2": {"transcricao": "aaaaabbbbbcccccddddd", "metadados": {"assunto": "Tema"}}}
        row = blind_side(reshaped, "a", lds)
        self.assertEqual(row["context_before"] + row["evidence"] + row["context_after"], row["text"])


class EligibilityTests(unittest.TestCase):

    def test_only_derived_validated_pairs_are_eligible(self):
        eligible = eligible_expansion_pairs(ROOT)
        eligible_ids = {p["pair_id"] for p in eligible}
        self.assertEqual(len(eligible), 29)
        self.assertTrue(eligible_ids.isdisjoint(KNOWN_INVALID_EXPANSION_PAIRS),
                        "INVALID expansion pairs must never reach annotation")

    def test_eligible_pairs_are_reshaped_to_a_b_shape(self):
        eligible = eligible_expansion_pairs(ROOT)
        for pair in eligible:
            for field in ("source_record_id_a", "source_record_id_b",
                          "speech_text_a", "speech_text_b", "evidence_a", "evidence_b"):
                self.assertIn(field, pair)


class AnnotationPacketTests(unittest.TestCase):
    """End-to-end check against the real, already-generated expansion round."""

    def test_generated_packets_same_ids_different_order_blank_responses(self):
        eligible = eligible_expansion_pairs(ROOT)
        lds = {str(row["id"]): row for row in read_jsonl(ROOT / "PublicHearingBR_LDS.jsonl")}
        packet_1, _ = annotation_rows(eligible, lds, 1)
        packet_2, _ = annotation_rows(eligible, lds, 2)
        self.assertEqual({r["pair_id"] for r in packet_1}, {r["pair_id"] for r in packet_2})
        self.assertNotEqual([r["pair_id"] for r in packet_1], [r["pair_id"] for r in packet_2])
        for packet in (packet_1, packet_2):
            for row in packet:
                for field in RESPONSE_FIELDS:
                    self.assertEqual(row[field], "")

    def test_written_annotator_files_match_reference_pair_ids(self):
        folder = ROOT / "data" / "annotations"
        reference = read_csv(folder / "expansion_semantic_pilot_reference.csv")
        for annotator in (1, 2):
            packet = read_csv(folder / f"expansion_annotator_{annotator}.csv")
            self.assertEqual({r["pair_id"] for r in packet}, {r["pair_id"] for r in reference})
            self.assertEqual(list(packet[0]), DISPLAY_FIELDS + RESPONSE_FIELDS)

    def test_reference_records_presentation_mapping_for_both_annotators(self):
        folder = ROOT / "data" / "annotations"
        reference = read_csv(folder / "expansion_semantic_pilot_reference.csv")
        for row in reference:
            self.assertIn(row["annotator_1_display_a_source_side"], {"a", "b"})
            self.assertIn(row["annotator_2_display_a_source_side"], {"a", "b"})

    def test_no_silver_or_gold_fields_in_annotator_packets(self):
        folder = ROOT / "data" / "annotations"
        forbidden = {"stance_silver_a", "stance_silver_b", "relation_gold",
                    "derived_relation", "label_source"}
        for annotator in (1, 2):
            packet = read_csv(folder / f"expansion_annotator_{annotator}.csv")
            self.assertTrue(forbidden.isdisjoint(set(packet[0])))

    def test_readiness_report_records_generated_packets(self):
        report = json.loads(
            (ROOT / "data/processed/expansion_provenance_readiness.json").read_text(encoding="utf-8")
        )
        self.assertTrue(report["semantic_packets_generated"])
        self.assertEqual(report["semantic_packet_pairs"], 29)
        self.assertEqual(len(report["semantic_packet_files"]), 3)


if __name__ == "__main__":
    unittest.main()
