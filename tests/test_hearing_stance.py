import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from voxlab import hearing_stance
from voxlab.hearing_stance import (
    mask_identity,
    MAX_SPEECH_CHARS,
    Request,
    parse_propositions,
    parse_stance,
    plan_summary,
    raw_path,
    render_stance,
    stance_rows,
    truncate,
)


ROOT = Path(__file__).resolve().parents[1]
ROW = {"hearing_id": "7", "actor_index": 2, "publication_date": "2023-05-10", "government_period": "LULA"}
PROPS = [{"id": "P1", "text": "O imposto X deve aumentar."}, {"id": "P2", "text": "A agência Y deve ser extinta."}]


def response(content: str) -> dict:
    return {"choices": [{"message": {"content": content}}]}


class ParseTest(unittest.TestCase):
    def test_parse_propositions_valid_and_malformed(self):
        ok = parse_propositions('{"propositions": [{"id": "P1", "text": " A  B "}, {"id": "P2", "text": "C"}]}')
        self.assertEqual(ok, {"propositions": [{"id": "P1", "text": "A B"}, {"id": "P2", "text": "C"}],
                              "malformed_output": False})
        for bad in ("nada", '{"propositions": []}', '{"propositions": [{"id": "P2", "text": "x"}]}',
                    '{"propositions": [{"id": "P1", "text": ""}]}',
                    json.dumps({"propositions": [{"id": f"P{i}", "text": "x"} for i in range(1, 5)]})):
            self.assertTrue(parse_propositions(bad)["malformed_output"], bad)

    def test_parse_stance_valid(self):
        raw = json.dumps({"propositions": {"P1": {"stance_determinable": "YES", "stance": "AGAINST"},
                                           "P2": {"stance_determinable": "NO", "stance": "FAVOR"}},
                          "government_stance": "CRITICIZE", "previous_government_stance": "NOT_ADDRESSED"})
        parsed = parse_stance(raw, ["P1", "P2"])
        self.assertFalse(parsed["malformed_output"])
        self.assertEqual(parsed["propositions"]["P1"], {"stance_determinable": "YES", "stance": "AGAINST"})
        # A stance given despite determinability NO is dropped, not kept.
        self.assertEqual(parsed["propositions"]["P2"], {"stance_determinable": "NO", "stance": ""})

    def test_parse_stance_flags_schema_errors_without_inventing_values(self):
        raw = json.dumps({"propositions": {"P1": {"stance_determinable": "YES", "stance": "NEUTRAL"}},
                          "government_stance": "OPPOSE", "previous_government_stance": "NEUTRAL"})
        parsed = parse_stance(raw, ["P1", "P2"])
        self.assertTrue(parsed["malformed_output"])
        self.assertEqual(set(parsed["malformed_fields"]),
                         {"proposition_ids", "P1.stance", "P2.stance_determinable", "government_stance"})
        self.assertEqual(parsed["propositions"]["P1"]["stance"], "")
        self.assertEqual(parsed["government_stance"], "")
        self.assertEqual(parse_stance("not json", ["P1"])["malformed_fields"], ["json"])


class RenderTest(unittest.TestCase):
    def test_stance_prompt_is_blind_and_names_government(self):
        prompt, cut = render_stance(ROOT, ROW, "Tema", PROPS, "Fala do participante.", "speech")
        self.assertFalse(cut)
        self.assertIn("Luiz Inácio Lula da Silva", prompt)
        self.assertIn("P1: O imposto X deve aumentar.", prompt)
        self.assertIn("Manifestação literal", prompt)
        self.assertNotIn("{", prompt.split("Responda em JSON")[0])
        summary_prompt, _ = render_stance(ROOT, ROW, "Tema", PROPS, "Resumo.", "lds_summary")
        self.assertIn("não é fala literal", summary_prompt)

    def test_truncate(self):
        text, cut = truncate("x" * (MAX_SPEECH_CHARS + 5), MAX_SPEECH_CHARS)
        self.assertTrue(cut)
        self.assertTrue(text.startswith("x" * MAX_SPEECH_CHARS))
        self.assertEqual(truncate("abc", 10), ("abc", False))


class PlanAndTablesTest(unittest.TestCase):
    def test_plan_counts_cache_and_never_calls_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            requests = [Request("stance", "speech", hearing_stance.MODELS[0], "h7_a2", "p" * 320),
                        Request("stance", "speech", hearing_stance.MODELS[0], "h7_a3", "p" * 320)]
            path = raw_path(root, requests[0])
            path.parent.mkdir(parents=True)
            path.write_text("{}")
            with mock.patch.object(hearing_stance, "chat_completion") as network:
                plan = plan_summary(root, requests)
                network.assert_not_called()
            group = plan["groups"][f"stance|speech|{hearing_stance.MODELS[0]}"]
            self.assertEqual((group["calls"], group["cached"], plan["calls_to_send"]), (2, 1, 1))
            self.assertEqual(group["input_tokens_est"], 100)

    def test_stance_rows_long_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            request = Request("stance", "speech", hearing_stance.MODELS[1], "h7_a2", "prompt")
            path = raw_path(root, request)
            path.parent.mkdir(parents=True)
            content = json.dumps({"propositions": {"P1": {"stance_determinable": "YES", "stance": "FAVOR"},
                                                   "P2": {"stance_determinable": "NO", "stance": ""}},
                                  "government_stance": "SUPPORT", "previous_government_stance": "CRITICIZE"})
            path.write_text(json.dumps(response(content)))
            rows = stance_rows(root, [request], {"7": {"propositions": PROPS, "malformed_output": False}})
            self.assertEqual([(r["hearing_id"], r["actor_index"], r["proposition_id"], r["stance"]) for r in rows],
                             [("7", "2", "P1", "FAVOR"), ("7", "2", "P2", "")])
            self.assertTrue(all(r["government_stance"] == "SUPPORT" and r["label_source"] == "MODEL_PREDICTION"
                                for r in rows))


class MaskTest(unittest.TestCase):
    def test_masks_people_parties_and_group_labels(self):
        text = ("Como disse a Deputada Erika Kokay, o PT e o Partido Novo discordam; "
                "os bolsonaristas e o PSOL também. Falo pelo PL-SP e pela bancada do PL.")
        masked = mask_identity(text, ["Erika Kokay", "ERIKA JUCÁ KOKAY"])
        self.assertNotIn("Kokay", masked)
        for cue in ("PT", "Partido Novo", "bolsonaristas", "PSOL", "PL-SP", "bancada do PL"):
            self.assertNotIn(cue, masked)
        self.assertIn("[PESSOA]", masked)
        self.assertIn("[GRUPO POLÍTICO]", masked)

    def test_keeps_bills_common_words_and_government_references(self):
        text = ("O PL 2630 e o PL das Fake News; o PL garante direitos. Podemos avançar no Ministério da "
                "Cidadania. O governo Lula e o governo Bolsonaro; nosso governo fez isso.")
        self.assertEqual(mask_identity(text, []), text)


if __name__ == "__main__":
    unittest.main()
