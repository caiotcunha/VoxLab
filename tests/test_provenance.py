import unittest

from voxlab.provenance import (compact_with_map, identity_status, locate_chunk,
                               ordered_pair, pair_validation, parse_turns,
                               speaker_matches_actor, validation_status)


def valid_row():
    row = {"event_verified_a": "true", "event_verified_b": "true",
           "event_id_a": "11", "event_id_b": "12",
           "event_start_a": "2024-01-02T10:00:00", "event_start_b": "2024-02-03T10:00:00",
           "hearing_date_a": "2024-01-02", "hearing_date_b": "2024-02-03",
           "hearing_date_verified_a": "true", "hearing_date_verified_b": "true",
           "same_actor_verified": "true", "speech_text_a": "First literal statement.",
           "speech_text_b": "Second literal statement.",
           "evidence_a": "First literal statement.", "evidence_b": "Second literal statement.",
           "_transcript_a": "First literal statement.", "_transcript_b": "Second literal statement.",
           "speech_start_a": 0, "speech_end_a": 24,
           "speech_start_b": 0, "speech_end_b": 25,
           "evidence_start_a": 0, "evidence_end_a": 24,
           "evidence_start_b": 0, "evidence_end_b": 25,
           "turn_attribution_verified_a": "true", "turn_attribution_verified_b": "true",
           "summary_support_reviewed_a": "true", "summary_support_reviewed_b": "true"}
    return row


class ProvenanceTests(unittest.TestCase):
    def test_publication_never_fills_hearing_date(self):
        row = valid_row()
        row.update({"publication_date_a": "2024-01-03", "hearing_date_a": "",
                    "hearing_date_verified_a": "unknown"})
        checked = pair_validation(row)
        self.assertEqual(checked["hearing_date_a"], "")
        self.assertEqual(checked["temporal_order_verified"], "unknown")

    def test_same_event_is_invalid(self):
        row = valid_row()
        row["event_id_b"] = row["event_id_a"]
        checked = pair_validation(row)
        self.assertEqual(checked["distinct_events_verified"], "false")
        self.assertEqual(checked["validation_status"], "INVALID")

    def test_temporal_order_requires_verified_dates(self):
        row = valid_row()
        row["hearing_date_verified_b"] = "unknown"
        self.assertEqual(pair_validation(row)["temporal_order_verified"], "unknown")

    def test_literal_evidence_required(self):
        row = valid_row()
        row["evidence_a"] = "Invented evidence"
        checked = pair_validation(row)
        self.assertEqual(checked["evidence_verified_a"], "unknown")
        self.assertNotEqual(checked["validation_status"], "VALIDATED")

    def test_evidence_offsets_must_reconstruct_literal(self):
        row = valid_row()
        row["evidence_start_a"] = 1
        self.assertEqual(pair_validation(row)["evidence_verified_a"], "unknown")

    def test_evidence_offsets_must_be_inside_named_speech(self):
        row = valid_row()
        row["_transcript_a"] = "First literal statement. Another First literal statement."
        row["evidence_start_a"] = 33
        row["evidence_end_a"] = 57
        self.assertEqual(pair_validation(row)["evidence_verified_a"], "unknown")

    def test_summary_mismatch_does_not_erase_located_speech(self):
        row = valid_row()
        row["summary_support_reviewed_a"] = "false"
        checked = pair_validation(row)
        self.assertEqual(checked["speech_verified_a"], "true")
        self.assertEqual(checked["evidence_verified_a"], "false")
        self.assertEqual(checked["validation_status"], "INVALID")

    def test_unknown_actor_blocks_validation(self):
        row = valid_row()
        row["same_actor_verified"] = "unknown"
        self.assertEqual(pair_validation(row)["validation_status"], "PARTIALLY_VALIDATED")

    def test_unattributed_speech_blocks_evidence(self):
        row = valid_row()
        row["turn_attribution_verified_a"] = "unknown"
        self.assertEqual(pair_validation(row)["evidence_verified_a"], "unknown")

    def test_reverse_input_swaps_all_side_fields(self):
        row = valid_row()
        row["event_start_a"], row["event_start_b"] = row["event_start_b"], row["event_start_a"]
        row["hearing_date_a"], row["hearing_date_b"] = row["hearing_date_b"], row["hearing_date_a"]
        checked = pair_validation(row)
        self.assertEqual(checked["input_sides_swapped"], "true")
        self.assertEqual((checked["event_id_a"], checked["event_id_b"]), ("12", "11"))
        self.assertEqual(checked["temporal_order_verified"], "true")

    def test_unknown_preserved(self):
        row = valid_row()
        row["event_verified_a"] = "unknown"
        checked = pair_validation(row)
        self.assertEqual(checked["distinct_events_verified"], "unknown")
        self.assertEqual(checked["validation_status"], "PARTIALLY_VALIDATED")

    def test_chair_name_and_literal_offsets(self):
        transcript = "O SR. PRESIDENTE(Dr. Zacharias Calil. UNIÃO - GO) - Texto um.\n\nA SRA. OUTRA PESSOA- Texto dois."
        turns = parse_turns(transcript)
        self.assertEqual(turns[0].speaker_name, "Dr. Zacharias Calil")
        self.assertEqual(transcript[turns[0].text_start:turns[0].text_end].strip(), "Texto um.")
        self.assertFalse(speaker_matches_actor(turns[1].speaker_name, "Dr. Zacharias Calil"))

    def test_nli_exact_and_whitespace_normalized_matches(self):
        transcript = "Primeira\n\nfala aqui."
        compact, char_map = compact_with_map(transcript)
        self.assertEqual(locate_chunk(transcript, compact, char_map, "Primeira\n\nfala")[0], "EXACT_MATCH")
        method, spans = locate_chunk(transcript, compact, char_map, "Primeira fala")
        self.assertEqual(method, "NORMALIZED_EXACT_MATCH")
        self.assertEqual(transcript[slice(*spans[0])], "Primeira\n\nfala")
        self.assertEqual(locate_chunk(transcript, compact, char_map, "não está aqui")[0], "NO_MATCH")

    def test_role_identity_does_not_use_name_alone(self):
        self.assertEqual(identity_status("Paulo Xavier", "Presidente da FEMBRAPP", "Paulo Xavier", "Presidente da FANMA")[0], "unknown")


if __name__ == "__main__":
    unittest.main()
