import unittest

from voxlab.hearing_stance import MODELS
from voxlab.party_alignment import (
    agreement_gap,
    bloc_of,
    directional_stances,
    government_by_group,
    government_stances,
    net_support,
    period_shift,
    permutation_test,
    recurrent_actor_panel,
    within_hearing_pairs,
)


def label(actor_id, party, period="LULA", actor_type="DEPUTY", bloc=""):
    return {"actor_id": actor_id, "actor_type": actor_type, "period": period, "party": party, "bloc": bloc,
            "deputado_id": "", "governism": None, "party_source": "CARGO"}


def stance(hearing, actor, prop, value, gov="NOT_ADDRESSED", model=MODELS[0], condition="speech"):
    determinable = "YES" if value else "NO"
    return {"hearing_id": hearing, "actor_index": actor, "proposition_id": prop, "model": model,
            "condition": condition, "stance_determinable": determinable, "stance": value or "",
            "government_stance": gov, "previous_government_stance": "NOT_ADDRESSED", "malformed_output": "False"}


class GroupAgreementTest(unittest.TestCase):
    def setUp(self):
        # Hearing 1: two PT deputies agree, one PL deputy disagrees; a civil-society actor is ignored.
        self.labels = {("1", "0"): label("a", "PT"), ("1", "1"): label("b", "PT"), ("1", "2"): label("c", "PL"),
                       ("1", "3"): label("d", "", actor_type="CIVIL_SOCIETY_OR_OTHER")}
        self.rows = [stance("1", "0", "P1", "FAVOR"), stance("1", "1", "P1", "FAVOR"),
                     stance("1", "2", "P1", "AGAINST"), stance("1", "3", "P1", "FAVOR"),
                     stance("1", "0", "P2", "UNCERTAIN"), stance("1", "1", "P2", None)]

    def test_pairs_only_directional_deputy_stances(self):
        stances = directional_stances(self.rows, MODELS[0], "speech")
        self.assertEqual(set(stances), {("1", "P1")})
        pairs = within_hearing_pairs(stances, self.labels, "party")
        self.assertEqual(len(pairs), 3)
        gap = agreement_gap(pairs, {k: v["party"] for k, v in self.labels.items()})
        self.assertEqual((gap["agreement_same_group"], gap["agreement_diff_group"], gap["gap"]), (1.0, 0.0, 1.0))

    def test_same_person_twice_is_not_a_pair(self):
        self.labels[("1", "1")] = label("a", "PT")
        pairs = within_hearing_pairs(directional_stances(self.rows, MODELS[0], "speech"), self.labels, "party")
        self.assertEqual(len(pairs), 2)

    def test_permutation_p_is_valid_probability(self):
        pairs = within_hearing_pairs(directional_stances(self.rows, MODELS[0], "speech"), self.labels, "party")
        result = permutation_test(pairs, self.labels, "party", n=200)
        self.assertEqual(result["gap"], 1.0)
        self.assertGreater(result["permutation_p"], 0)
        self.assertLessEqual(result["permutation_p"], 1)

    def test_bloc_of(self):
        self.assertEqual([bloc_of(v) for v in (None, 0.2, 0.5, 0.9)], ["", "OPPOSITION", "PIVOT", "GOVERNMENT"])


class GovernmentStanceTest(unittest.TestCase):
    def test_net_support_excludes_not_addressed(self):
        result = net_support(["SUPPORT", "SUPPORT", "CRITICIZE", "NOT_ADDRESSED", "NEUTRAL"])
        self.assertEqual((result["n"], result["n_addressed"], result["net_support"]), (5, 4, 0.25))
        self.assertIsNone(net_support(["NOT_ADDRESSED"])["net_support"])

    def test_government_stances_deduplicate_propositions(self):
        rows = [stance("1", "0", "P1", "FAVOR", "SUPPORT"), stance("1", "0", "P2", "FAVOR", "SUPPORT"),
                stance("1", "0", "P1", "FAVOR", "CRITICIZE", model=MODELS[1])]
        self.assertEqual(government_stances(rows, MODELS[0], "speech"), {("1", "0"): "SUPPORT"})

    def test_group_shift_and_panel(self):
        labels = {("1", "0"): label("a", "PT", "BOLSONARO"), ("2", "0"): label("a", "PT", "LULA"),
                  ("3", "0"): label("b", "PL", "BOLSONARO"), ("4", "0"): label("b", "PL", "LULA")}
        government = {("1", "0"): "CRITICIZE", ("2", "0"): "SUPPORT", ("3", "0"): "SUPPORT", ("4", "0"): "CRITICIZE"}
        by_group = government_by_group(government, labels, n_boot=50)
        self.assertEqual(by_group["PARTY:PT|LULA"]["ci95"], [1.0, 1.0])
        shift = period_shift(by_group)
        self.assertEqual((shift["PARTY:PT"]["shift"], shift["PARTY:PL"]["shift"]), (2.0, -2.0))
        panel = recurrent_actor_panel(government, labels)
        self.assertEqual([(r["actor_id"], r["bolsonaro_net_support"], r["lula_net_support"]) for r in panel],
                         [("a", -1.0, 1.0), ("b", 1.0, -1.0)])


if __name__ == "__main__":
    unittest.main()
