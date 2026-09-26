import tempfile
import unittest
from pathlib import Path

from voxlab.camara_api import (
    deputy_directory,
    government_orientation,
    governism,
    match_deputies,
    party_covoting,
    party_on,
    read_semicolon_csv,
)


def vote(vote_id, deputy, party, value, name=None, uf="SP"):
    return {"idVotacao": vote_id, "deputado_id": deputy, "deputado_nome": name or f"Dep {deputy}",
            "deputado_siglaPartido": party, "deputado_siglaUf": uf, "voto": value}


DATES = {"v1": "2022-06-01", "v2": "2023-03-01", "v3": "2023-04-01"}
VOTES = [
    vote("v1", "1", "PT", "Não"), vote("v1", "2", "PL", "Sim"),
    vote("v2", "1", "PT", "Sim"), vote("v2", "2", "PL", "Não"), vote("v2", "3", "PSD", "Sim"),
    vote("v3", "1", "PT", "Sim"), vote("v3", "2", "PL", "Obstrução"), vote("v3", "3", "PSD", "Não"),
]
ORIENTATIONS = [
    {"idVotacao": "v1", "siglaBancada": "Governo", "orientacao": "Sim"},
    {"idVotacao": "v2", "siglaBancada": "Governo", "orientacao": "Sim"},
    {"idVotacao": "v3", "siglaBancada": "Governo", "orientacao": "Liberado"},
    {"idVotacao": "v3", "siglaBancada": "PT", "orientacao": "Sim"},
]


class CamaraTest(unittest.TestCase):
    def test_government_orientation_keeps_only_directional_government_lines(self):
        self.assertEqual(government_orientation(ORIENTATIONS), {"v1": "SIM", "v2": "SIM"})

    def test_governism_by_period(self):
        result = governism(VOTES, government_orientation(ORIENTATIONS), DATES)
        self.assertEqual(result[("1", "BOLSONARO")], {"n": 1, "governism": 0.0})
        self.assertEqual(result[("1", "LULA")], {"n": 1, "governism": 1.0})
        self.assertEqual(result[("2", "BOLSONARO")], {"n": 1, "governism": 1.0})
        self.assertEqual(result[("2", "LULA")], {"n": 1, "governism": 0.0})
        self.assertNotIn(("3", "BOLSONARO"), result)

    def test_dated_party(self):
        directory = deputy_directory([vote("v1", "9", "PSL", "Sim"), vote("v2", "9", "União", "Sim")], DATES)
        timeline = directory["9"]["party_timeline"]
        self.assertEqual(party_on(timeline, "2022-12-01"), "PSL")
        self.assertEqual(party_on(timeline, "2023-03-02"), "UNIAO")
        self.assertEqual(party_on(timeline, "2021-01-01"), "PSL")

    def test_match_deputies_uses_uf_and_refuses_ambiguity(self):
        directory = {"1": {"name": "Erika Kokay", "uf": "DF", "party_timeline": []},
                     "2": {"name": "João Silva", "uf": "SP", "party_timeline": []},
                     "3": {"name": "João Silva", "uf": "RJ", "party_timeline": []},
                     "4": {"name": "Maria Lima", "uf": "BA", "party_timeline": []},
                     "5": {"name": "Maria Lima", "uf": "PE", "party_timeline": []}}
        rows = [{"actor_type": "DEPUTY", "actor_id": "erika kokay", "uf_cargo": "DF"},
                {"actor_type": "DEPUTY", "actor_id": "joao silva", "uf_cargo": "RJ"},
                {"actor_type": "DEPUTY", "actor_id": "maria lima", "uf_cargo": ""},
                {"actor_type": "CIVIL_SOCIETY_OR_OTHER", "actor_id": "erika kokay", "uf_cargo": ""}]
        self.assertEqual(match_deputies(rows, directory),
                         {"erika kokay": ("1", "NAME_UF_CONSISTENT"), "joao silva": ("3", "NAME_UF_CONSISTENT")})

    def test_party_covoting(self):
        result = party_covoting(VOTES, DATES)
        self.assertEqual(result[("BOLSONARO", "PL", "PT")], {"n": 1, "agreement": 0.0})
        self.assertEqual(result[("LULA", "PSD", "PT")], {"n": 2, "agreement": 0.5})
        self.assertEqual(result[("LULA", "PL", "PT")], {"n": 1, "agreement": 0.0})

    def test_read_semicolon_csv_checks_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.csv"
            path.write_text('﻿"idVotacao";"voto"\n"v1";"Sim"\n', encoding="utf-8")
            self.assertEqual(read_semicolon_csv(path, {"idVotacao"}), [{"idVotacao": "v1", "voto": "Sim"}])
            with self.assertRaisesRegex(ValueError, "missing columns"):
                read_semicolon_csv(path, {"idVotacao", "deputado_id"})


if __name__ == "__main__":
    unittest.main()
