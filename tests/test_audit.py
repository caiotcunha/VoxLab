import unittest

from voxlab.audit import build_longitudinal, hearing_pairs, normalize_actor, select_pairs


def hearing(hid, date, actors, topic="regulacao de plataformas"):
    return {"id": hid, "materia": f"Notícia\n{date} - 12:00", "transcricao": "",
            "metadados": {"assunto": topic, "envolvidos": [
                {"nome": name, "cargo": "", "opinioes": [text]} for name, text in actors]}}


class AuditTests(unittest.TestCase):
    def test_actor_normalization(self):
        self.assertEqual(normalize_actor("  ÉRIKA   Kokay! "), "erika kokay")

    def test_same_actor_distinct_hearings_order_no_duplicates(self):
        raw = [hearing(1, "02/01/2024", [("Érika Kokay", "apoia a proposta")]),
               hearing(2, "01/01/2024", [("Erika Kokay", "rejeita a proposta"), ("Outra Pessoa", "fala")])]
        rows, _ = build_longitudinal(raw, {})
        pairs = select_pairs(hearing_pairs(rows), rows, 0, 5)
        self.assertEqual(len(pairs), 1)
        self.assertEqual((pairs[0]["hearing_id_a"], pairs[0]["hearing_id_b"]), ("2", "1"))
        self.assertEqual(pairs[0]["actor_id"], "erika kokay")
        self.assertEqual(pairs[0]["temporal_order_verified"], "false")

    def test_missing_or_tied_publication_date_cannot_order(self):
        raw = [hearing(1, "02/01/2024", [("Pessoa", "um")]),
               hearing(2, "02/01/2024", [("Pessoa", "dois")]),
               hearing(3, "not a date", [("Pessoa", "tres")])]
        rows, _ = build_longitudinal(raw, {})
        self.assertEqual(hearing_pairs(rows), [])

    def test_single_appearance_and_source_trace(self):
        raw = [hearing(9, "02/01/2024", [("Pessoa", "opinião")])]
        rows, _ = build_longitudinal(raw, {})
        self.assertEqual(hearing_pairs(rows), [])
        row = rows[0]
        source = raw[0]["metadados"]["envolvidos"][row["source_actor_index"]]["opinioes"][row["source_opinion_index"]]
        self.assertEqual(row["speech_text"], source)
        self.assertEqual(row["evidence"], "")


if __name__ == "__main__":
    unittest.main()
