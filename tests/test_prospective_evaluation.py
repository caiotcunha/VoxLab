import unittest

from voxlab.prospective_evaluation import evaluate_predictions


def gold(pair_id: str, relation: str, same: str) -> dict[str, str]:
    return {"pair_id": pair_id, "derived_relation": relation, "same_proposition": same,
            "label_source": "HUMAN_CONSENSUS"}


def prediction(pair_id: str, a: str, b: str, c: str, same: str) -> dict[str, str]:
    return {"pair_id": pair_id, "model": "model", "relation_end_to_end": a,
            "relation_structured_without_gate": b, "relation_structured_with_gate": c,
            "same_proposition": same, "label_source": "MODEL_PREDICTION"}


class ProspectiveEvaluationTests(unittest.TestCase):

    def test_primary_A_vs_C_effect_and_metrics_are_paired(self):
        truth = [gold("p1", "INCOMPARABLE", "NO"),
                 gold("p2", "STANCE_MAINTAINED", "YES")]
        predicted = [
            prediction("p2", "STANCE_MAINTAINED", "STANCE_MAINTAINED", "INCOMPARABLE", "NO"),
            prediction("p1", "STANCE_MAINTAINED", "STANCE_MAINTAINED", "INCOMPARABLE", "NO"),
        ]
        result = evaluate_predictions(predicted, truth)["models"]["model"]
        self.assertEqual(result["conditions"]["end_to_end_A"]["accuracy"], 0.5)
        self.assertEqual(result["conditions"]["structured_with_gate_C"]["accuracy"], 0.5)
        self.assertEqual(result["paired_A_vs_C"]["A_error_to_C_correct"], 1)
        self.assertEqual(result["paired_A_vs_C"]["A_correct_to_C_error"], 1)

    def test_pair_set_must_match_exactly_for_each_model(self):
        with self.assertRaisesRegex(ValueError, "exactly 1:1"):
            evaluate_predictions(
                [prediction("p1", "INCOMPARABLE", "INCOMPARABLE", "INCOMPARABLE", "NO")],
                [gold("p1", "INCOMPARABLE", "NO"), gold("p2", "INCOMPARABLE", "NO")],
            )

    def test_label_sources_are_enforced(self):
        bad = prediction("p1", "INCOMPARABLE", "INCOMPARABLE", "INCOMPARABLE", "NO")
        bad["label_source"] = "HUMAN_CONSENSUS"
        with self.assertRaisesRegex(ValueError, "MODEL_PREDICTION"):
            evaluate_predictions([bad], [gold("p1", "INCOMPARABLE", "NO")])


if __name__ == "__main__":
    unittest.main()
