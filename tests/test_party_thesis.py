import unittest

from voxlab.party_thesis import (
    beyond_party,
    camp_of,
    civil_society_decomposition,
    contested_only,
    structure,
    support_without_voice,
    within_actor_panel,
)
from voxlab.stance_validation import ALLOCATION, draw_sample, item_id


def label(actor_id, party="", period="LULA", actor_type="DEPUTY"):
    return {"actor_id": actor_id, "party": party, "period": period, "actor_type": actor_type,
            "deputado_id": actor_id, "bloc": "", "governism": None, "party_source": "CARGO"}


class CampAndStructureTest(unittest.TestCase):
    def test_camp_of(self):
        self.assertEqual(camp_of(label("a", "PT")), "LEFT")
        self.assertEqual(camp_of(label("a", "NOVO")), "RIGHT")
        self.assertEqual(camp_of(label("a", "UNIAO")), "CENTRAO")
        self.assertEqual(camp_of(label("a", "PSB")), "OTHER_PARTY")
        self.assertEqual(camp_of(label("a", "", actor_type="FEDERAL_EXECUTIVE")), "FEDERAL_EXECUTIVE")

    def test_structure_metrics(self):
        s = structure(["SUPPORT", "SUPPORT", "CRITICIZE", "NEUTRAL", "NOT_ADDRESSED"])
        self.assertEqual((s["polar_share"], s["division"], s["net_support"]), (0.75, 0.6667, 0.25))
        unanimous = structure(["CRITICIZE", "CRITICIZE"])
        self.assertEqual((unanimous["division"], unanimous["polar_share"]), (0.0, 1.0))
        self.assertIsNone(structure(["NOT_ADDRESSED"])["polar_share"])

    def test_contested_only(self):
        cells = {("1", "P1"): {"a": 1, "b": -1}, ("1", "P2"): {"a": 1, "b": 1}}
        self.assertEqual(set(contested_only(cells)), {("1", "P1")})


class DeputyLevelTest(unittest.TestCase):
    def rows(self):
        rows = []
        for i in range(12):
            rows.append({"party": "PT", "camp": "LEFT", "governism": 0.9 + 0.005 * i, "score": 0.8 + 0.01 * i})
            rows.append({"party": "PL", "camp": "RIGHT", "governism": 0.3 + 0.005 * i, "score": -0.8 - 0.01 * i})
            rows.append({"party": "PSD", "camp": "CENTRAO", "governism": 0.75 + 0.005 * i, "score": 0.0 + 0.01 * i})
        return rows

    def test_support_without_voice_centrao_below_prediction(self):
        result = support_without_voice(self.rows(), n_boot=200)
        self.assertLess(result["residual_by_camp"]["CENTRAO"]["mean"], 0)
        self.assertLess(result["residual_by_camp"]["CENTRAO_minus_POLES"]["ci95"][1], 0)

    def test_beyond_party_reports_within_camp(self):
        result = beyond_party(self.rows())
        self.assertEqual(set(result["within_camp_spearman"]), {"LEFT", "RIGHT", "CENTRAO", "OTHER_PARTY"})
        self.assertIn("ols_party_fixed_effects", result)


class PanelAndCivilSocietyTest(unittest.TestCase):
    def test_within_actor_panel(self):
        labels = {("1", "0"): label("a", "PT", "BOLSONARO"), ("2", "0"): label("a", "PT", "LULA"),
                  ("3", "0"): label("b", "PL", "BOLSONARO"), ("4", "0"): label("b", "PL", "LULA"),
                  ("5", "0"): label("c", "PT", "LULA")}
        government = {("1", "0"): "CRITICIZE", ("2", "0"): "SUPPORT", ("3", "0"): "SUPPORT",
                      ("4", "0"): "CRITICIZE", ("5", "0"): "SUPPORT"}
        result = within_actor_panel(government, labels, n_boot=50)
        self.assertEqual(result["by_camp"]["LEFT"]["mean_change"], 2.0)
        self.assertEqual(result["by_camp"]["RIGHT"]["mean_change"], -2.0)
        self.assertEqual(len(result["actors"]), 2)

    def test_civil_society_composition(self):
        cs = "CIVIL_SOCIETY_OR_OTHER"
        labels = {("1", "0"): label("x", period="BOLSONARO", actor_type=cs), ("2", "0"): label("y", actor_type=cs),
                  ("3", "0"): label("z", actor_type=cs), ("4", "0"): label("x", actor_type=cs)}
        government = {("1", "0"): "CRITICIZE", ("2", "0"): "SUPPORT", ("3", "0"): "SUPPORT", ("4", "0"): "CRITICIZE"}
        result = civil_society_decomposition(government, labels)
        self.assertEqual(result["actors_in_both_periods"], 1)
        self.assertEqual(result["lula_rows_from_recurrent_actors_share"], 0.3333)
        self.assertEqual(result["within_person_mean_change"], 0.0)


class ValidationSampleTest(unittest.TestCase):
    def test_stratified_sample_respects_quotas_and_prefers_disagreement(self):
        candidates = []
        for camp in ALLOCATION:
            for period in ("BOLSONARO", "LULA"):
                for k in range(30):
                    candidates.append({"hearing_id": f"{camp}{period}{k}", "actor_index": "0", "camp": camp,
                                       "period": period, "disagree": k < 10})
        sample = draw_sample(candidates, 100)
        self.assertEqual(len(sample), sum(round(100 * s) for s in ALLOCATION.values()))
        self.assertEqual(len({(r["hearing_id"], r["actor_index"]) for r in sample}), len(sample))
        left_lula = [r for r in sample if r["camp"] == "LEFT" and r["period"] == "LULA"]
        self.assertGreaterEqual(sum(r["disagree"] for r in left_lula), len(left_lula) // 2)
        self.assertTrue(all(r["inclusion_weight"] >= 1 for r in sample))
        self.assertEqual(item_id("1", "2"), item_id("1", "2"))
        self.assertNotEqual(item_id("1", "2"), item_id("2", "1"))


if __name__ == "__main__":
    unittest.main()
