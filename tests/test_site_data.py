import json
import unittest
from pathlib import Path

from voxlab.site_data import MAX_BYTES, build, proposition_code


ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"


class PropositionCodeTest(unittest.TestCase):
    def test_codes(self):
        self.assertEqual([proposition_code("YES", s) for s in ("FAVOR", "AGAINST", "UNCERTAIN", "")],
                         ["F", "A", "U", "x"])
        self.assertEqual([proposition_code(d, "") for d in ("NO", "UNCERTAIN", "")], ["-", "?", "x"])


@unittest.skipUnless((PROCESSED / "party_stances.csv").exists(), "party-alignment outputs not generated")
class SiteDataTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = build(ROOT)

    def test_schema_and_integrity(self):
        data = self.data
        self.assertEqual(data["meta"]["label_source"], "MODEL_PREDICTION")
        self.assertEqual(len(data["hearings"]), 206)
        actor_keys = {f"{h['id']}_{a['i']}" for h in data["hearings"] for a in h["actors"]}
        self.assertEqual(len(actor_keys), 1065)
        self.assertLessEqual(set(data["stances"]), actor_keys)
        propositions = {h["id"]: {p["id"] for p in h["propositions"]} for h in data["hearings"]}
        for key, runs in data["stances"].items():
            hearing_id = key.split("_")[0]
            for cell in runs.values():
                self.assertEqual(set(cell["p"]), propositions[hearing_id])
        for deputy in data["deputies"].values():
            self.assertTrue(set(deputy["periods"]) <= {"BOLSONARO", "LULA"})

    def test_results_match_analysis_output(self):
        results = json.loads((PROCESSED / "party_alignment_results.json").read_text(encoding="utf-8"))
        original = results["runs"]["Qwen/Qwen2.5-72B-Instruct|speech"]["rq2"]["speech_vs_vote_governism"]
        self.assertEqual(self.data["results"]["runs"]["qwen|fala"]["rq2"]["speech_vs_vote_governism"], original)
        self.assertEqual(self.data["results"]["party_governism"], results["party_governism"])

    def test_size_budget(self):
        payload = json.dumps(self.data, ensure_ascii=False, separators=(",", ":"))
        self.assertLess(len(payload.encode("utf-8")), MAX_BYTES)


if __name__ == "__main__":
    unittest.main()
