import unittest
from pathlib import Path

from voxlab.consensus import (GOLD_FIELDS, analyze_consensus, build_gold_rows,
                              repair_cp1252_controls)


ROOT = Path(__file__).resolve().parents[1]


class ConsensusTests(unittest.TestCase):
    def test_cp1252_control_repair(self):
        self.assertEqual(repair_cp1252_controls("gás \x97 IBP"), "gás — IBP")

    def test_current_consensus_is_complete_and_source_valid(self):
        report, rows = analyze_consensus(ROOT)
        self.assertEqual(report["physical_consensus_rows"], 18)
        self.assertEqual(report["unique_known_pair_ids"], 18)
        self.assertEqual(report["missing_pair_ids"], [])
        self.assertEqual(report["duplicate_pair_ids"], {})
        self.assertEqual(report["source_content_mismatches"], [])
        self.assertTrue(report["valid_for_gold_generation"])
        self.assertTrue(report["all_responses_complete_and_schema_valid"])
        self.assertTrue(report["all_display_text_matches_claimed_pair"])
        self.assertEqual(report["source_valid_consensus_rows"], 18)
        self.assertEqual(report["relation_distribution"], {
            "INCOMPARABLE": 11, "RELATION_UNCERTAIN": 2, "STANCE_MAINTAINED": 5,
        })
        self.assertEqual(len(rows), 18)

    def test_gold_is_chronological_source_clean_and_human_labeled(self):
        report, _ = analyze_consensus(ROOT)
        rows = build_gold_rows(ROOT, report)
        self.assertEqual(len(rows), 18)
        self.assertEqual(len({row["pair_id"] for row in rows}), 18)
        self.assertTrue(all(list(row) == GOLD_FIELDS for row in rows))
        self.assertTrue(all(row["date_a"] < row["date_b"] for row in rows))
        self.assertTrue(all(row["label_source"] == "HUMAN_CONSENSUS" for row in rows))
        self.assertTrue(all(row["consensus_input_sha256"] == report["input_sha256"] for row in rows))
        self.assertFalse(any(0x80 <= ord(character) <= 0x9f
                             for row in rows for value in row.values() for character in value))


if __name__ == "__main__":
    unittest.main()
