import unittest

from voxlab.actors import actor_type, government_period, match_turns, parse_party, publication_date
from voxlab.provenance import parse_turns


TRANSCRIPT = (
    "O SR. PRESIDENTE (Lucas Redecker. PSDB - RS) - Declaro aberta a reunião.\n"
    "O SR. GLENN EDWARD GREENWALD - Obrigado pelo convite.\n"
    "O SR. DEPUTADO ARLINDO CHINAGLIA - Discordo da premissa.\n"
    "O SR. GLENN EDWARD GREENWALD - Mais uma resposta.\n"
    "A SRA. ANA MARIA SOUZA - Primeira fala.\n"
    "A SRA. ANA PAULA SOUZA - Segunda fala.\n"
)


class ActorsTest(unittest.TestCase):
    def test_parse_party_canonicalizes_and_ignores_organizations(self):
        self.assertEqual(parse_party("Deputada Federal (União-SP)"), ("UNIAO", "SP"))
        self.assertEqual(parse_party("Deputado (PODE-PR)"), ("PODEMOS", "PR"))
        self.assertEqual(parse_party("Presidente do Sindicato (SINDIREPA-SP)"), ("", ""))
        self.assertEqual(parse_party("Pesquisador"), ("", ""))

    def test_actor_type(self):
        self.assertEqual(actor_type("Deputado (PT-DF)", "PT"), "DEPUTY")
        self.assertEqual(actor_type("Deputado estadual de São Paulo (Psol)", ""), "SUBNATIONAL_POLITICIAN")
        self.assertEqual(actor_type("Ministra da Saúde", ""), "FEDERAL_EXECUTIVE")
        self.assertEqual(actor_type("Representante do Ministério da Educação", ""), "FEDERAL_EXECUTIVE")
        self.assertEqual(actor_type("Secretário de Meio Ambiente do Pará", ""), "SUBNATIONAL_OR_OTHER_STATE")
        self.assertEqual(actor_type("Ministra do Tribunal Superior do Trabalho", ""), "SUBNATIONAL_OR_OTHER_STATE")
        self.assertEqual(actor_type("Representante do Ministério Público do Trabalho", ""),
                         "SUBNATIONAL_OR_OTHER_STATE")
        self.assertEqual(actor_type("Presidente da Associação Brasileira X", ""), "CIVIL_SOCIETY_OR_OTHER")

    def test_government_period_and_date(self):
        self.assertEqual(government_period("2022-12-06"), "BOLSONARO")
        self.assertEqual(government_period("2023-01-01"), "LULA")
        self.assertEqual(publication_date("Título\n12/04/2023 - 18:05\nTexto"), "2023-04-12")

    def test_match_turns_exact_first_last_and_ambiguous(self):
        turns = parse_turns(TRANSCRIPT)
        method, speaker, matched = match_turns(turns, "Arlindo Chinaglia")
        self.assertEqual((method, len(matched)), ("EXACT", 1))
        method, speaker, matched = match_turns(turns, "Glenn Greenwald")
        self.assertEqual((method, speaker, len(matched)), ("FIRST_LAST", "GLENN EDWARD GREENWALD", 2))
        method, _, matched = match_turns(turns, "Ana Souza")
        self.assertEqual((method, matched), ("AMBIGUOUS", []))
        self.assertEqual(match_turns(turns, "Pessoa Ausente")[0], "NONE")
        self.assertEqual(match_turns(turns, "Glenn")[0], "NONE")


if __name__ == "__main__":
    unittest.main()
