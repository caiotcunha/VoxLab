"""Actor × hearing table for the party-alignment track.

One row per LDS participant (``metadados.envolvidos``) in each hearing, with:
party/UF parsed from the LDS ``cargo`` string, a coarse actor type, the
government period implied by the article publication date, and the actor's
literal turns located in the transcript.

Nothing here is a stance decision. Party comes from the news-derived ``cargo``
and is later cross-checked against dated party labels in Câmara roll-call
files (``voxlab.camara_api``); it is a claim of the source, not a verified
affiliation. Publication date is not hearing date (see README); the
government-period split is safe only because no hearing falls near
2023-01-01 (the closest is published 2022-12-06, before the recess).

Run from the repository root (no network):
    PYTHONPATH=src python3 -m voxlab.actors
"""

from __future__ import annotations

import collections
import json
import re
from pathlib import Path

from .audit import DATE_RE, normalize_actor, read_jsonl, write_csv
from .provenance import Turn, parse_turns, speaker_matches_actor

# Registered party acronyms seen in the corpus, mapped to one canonical form.
# Acronyms outside this map (SINDIREPA, PROCON, ADEPOL...) are organizations.
PARTY_ALIASES = {
    "PT": "PT", "PL": "PL", "PSOL": "PSOL", "REPUBLICANOS": "REPUBLICANOS",
    "UNIÃO": "UNIAO", "UNIAO": "UNIAO", "PSD": "PSD", "PP": "PP", "PDT": "PDT",
    "PSB": "PSB", "NOVO": "NOVO", "CIDADANIA": "CIDADANIA", "PSDB": "PSDB",
    "PCDOB": "PCDOB", "MDB": "MDB", "SOLIDARIEDADE": "SOLIDARIEDADE", "PV": "PV",
    "PATRIOTA": "PATRIOTA", "PODE": "PODEMOS", "PODEMOS": "PODEMOS", "DEM": "DEM",
    "PRD": "PRD", "REDE": "REDE", "AVANTE": "AVANTE", "PSC": "PSC", "PTB": "PTB",
    "PROS": "PROS", "PSL": "PSL", "PMN": "PMN", "AGIR": "AGIR",
}
PARTY_RE = re.compile(r"\(\s*([A-Za-zÀ-ú]+(?:\s?[A-Za-z]+)?)\s*[-/–]\s*([A-Z]{2})\s*\)")
EXECUTIVE_RE = re.compile(
    r"^(?:ministr[oa]|secret[áa]ri[oa]|vice-presidente da rep|presidente da rep|"
    r"representante d[oa] (?:minist[ée]rio|secretaria|casa civil|governo)|"
    r"(?:assessor|coordenador|diretor)[a]?(?:-geral)? d[oa] (?:minist[ée]rio|secretaria))",
    re.I,
)
NON_FEDERAL_RE = re.compile(
    r"tribunal|\b(?:TSE|TST|STF|STJ|TCU)\b|minist[ée]rio p[úu]blico|observat[óo]rio|estadual|municipal|prefeitura|"
    r"\bd[eo]s? (?:Acre|Alagoas|Amap[áa]|Amazonas|Bahia|Cear[áa]|Distrito Federal|Esp[íi]rito Santo|Goi[áa]s|"
    r"Maranh[ãa]o|Mato Grosso(?: do Sul)?|Minas Gerais|Par[áa]|Para[íi]ba|Paran[áa]|Pernambuco|Piau[íi]|"
    r"Rio de Janeiro|Rio Grande do Norte|Rio Grande do Sul|Rond[ôo]nia|Roraima|Santa Catarina|S[ãa]o Paulo|"
    r"Sergipe|Tocantins)\b",
    re.I,
)
TRANSITION_DATE = "2023-01-01"
PERIODS = (("BOLSONARO", "0000-00-00", TRANSITION_DATE), ("LULA", TRANSITION_DATE, "9999-99-99"))
FIELDS = [
    "hearing_id", "actor_index", "actor_id", "actor_name", "cargo", "party_cargo", "uf_cargo",
    "actor_type", "publication_date", "government_period", "speech_match_method",
    "matched_speaker", "n_turns", "speech_chars", "lds_opinions",
]


def parse_party(cargo: str) -> tuple[str, str]:
    """Return (canonical party, UF) from '(PARTIDO-UF)' in cargo, or ('', '')."""
    for match in PARTY_RE.finditer(cargo or ""):
        party = PARTY_ALIASES.get(match.group(1).strip().upper().replace(" ", ""))
        if party:
            return party, match.group(2)
    return "", ""


def actor_type(cargo: str, party: str) -> str:
    """Coarse role from cargo; party presence alone does not make a deputy.

    FEDERAL_EXECUTIVE is the known-group used later as a sanity check (its
    members should mostly support the government of the day)."""
    text = (cargo or "").strip()
    lowered = normalize_actor(text)
    if lowered.startswith(("deputado distrital", "deputada distrital", "deputado estadual", "deputada estadual")):
        return "SUBNATIONAL_POLITICIAN"
    if lowered.startswith(("deputado", "deputada")) or (party and "deputad" in lowered):
        return "DEPUTY"
    if lowered.startswith(("senador", "senadora")):
        return "SENATOR"
    if EXECUTIVE_RE.search(text):
        return "SUBNATIONAL_OR_OTHER_STATE" if NON_FEDERAL_RE.search(text) else "FEDERAL_EXECUTIVE"
    if party:
        return "OTHER_POLITICIAN"
    return "CIVIL_SOCIETY_OR_OTHER"


def government_period(date: str) -> str:
    for name, start, end in PERIODS:
        if start <= date < end:
            return name
    return ""


def publication_date(materia: str) -> str:
    match = DATE_RE.search(materia or "")
    if not match:
        return ""
    day, month, year = match.group(1).split("/")
    return f"{year}-{month}-{day}"


def match_turns(turns: list[Turn], actor_name: str) -> tuple[str, str, list[Turn]]:
    """Locate the actor's turns: exact/documented alias first, then conservative
    name variants that must resolve to exactly one distinct speaker."""
    usable = [t for t in turns if t.speaker_name and not t.has_unparsed_marker]
    exact = [t for t in usable if speaker_matches_actor(t.speaker_name, actor_name)]
    if exact:
        return "EXACT", exact[0].speaker_name, exact
    target = normalize_actor(actor_name).split()
    if len(target) < 2:
        return "NONE", "", []
    by_speaker = collections.defaultdict(list)
    for turn in usable:
        by_speaker[normalize_actor(turn.speaker_name)].append(turn)

    def first_last(tokens: list[str]) -> tuple[str, str]:
        return tokens[0], tokens[-1]

    rules = (
        ("FIRST_LAST", lambda s: len(s) >= 2 and first_last(s) == first_last(target)),
        ("TOKEN_SUBSET", lambda s: len(s) >= 2 and (set(target) <= set(s) or set(s) <= set(target))),
    )
    for method, rule in rules:
        hits = [name for name in by_speaker if rule(name.split())]
        if len(hits) == 1:
            chosen = by_speaker[hits[0]]
            return method, chosen[0].speaker_name, chosen
        if len(hits) > 1:
            return "AMBIGUOUS", "|".join(sorted(hits)), []
    return "NONE", "", []


def actor_speech(transcript: str, turns: list[Turn]) -> str:
    return "\n\n".join(transcript[t.text_start:t.text_end].strip() for t in turns)


def build_actor_hearings(raw: list[dict]) -> tuple[list[dict], dict[tuple[str, str], str]]:
    """Rows for every participant and a {(hearing_id, actor_index): speech} map."""
    rows, speeches = [], {}
    for record in raw:
        hearing_id = str(record["id"])
        transcript = record.get("transcricao") or ""
        turns = parse_turns(transcript)
        date = publication_date(record.get("materia", ""))
        for index, person in enumerate(record["metadados"].get("envolvidos", [])):
            cargo = person.get("cargo") or ""
            party, uf = parse_party(cargo)
            method, speaker, matched = match_turns(turns, person.get("nome", ""))
            speech = actor_speech(transcript, matched)
            speeches[(hearing_id, str(index))] = speech
            rows.append({
                "hearing_id": hearing_id, "actor_index": index,
                "actor_id": normalize_actor(person.get("nome", "")), "actor_name": person.get("nome", ""),
                "cargo": cargo, "party_cargo": party, "uf_cargo": uf,
                "actor_type": actor_type(cargo, party), "publication_date": date,
                "government_period": government_period(date), "speech_match_method": method,
                "matched_speaker": speaker, "n_turns": len(matched), "speech_chars": len(speech),
                "lds_opinions": " | ".join(person.get("opinioes") or []),
            })
    return rows, speeches


def summary(rows: list[dict]) -> dict:
    count = collections.Counter
    deputies = [r for r in rows if r["actor_type"] == "DEPUTY"]
    multi_party = collections.defaultdict(set)
    for r in deputies:
        if r["party_cargo"]:
            multi_party[r["hearing_id"]].add(r["party_cargo"])
    appearances = count(r["actor_id"] for r in rows)
    periods_by_actor = collections.defaultdict(set)
    for r in rows:
        periods_by_actor[r["actor_id"]].add(r["government_period"])
    return {
        "labels": {"party": "SOURCE_CLAIM_FROM_LDS_CARGO", "speech": "LITERAL_TRANSCRIPT_TURNS",
                   "date": "ARTICLE_PUBLICATION_DATE", "stance": "NONE"},
        "actor_hearing_rows": len(rows),
        "hearings": len({r["hearing_id"] for r in rows}),
        "hearings_by_period": dict(count(period for _, period in
                                         {(r["hearing_id"], r["government_period"]) for r in rows})),
        "actor_type": dict(count(r["actor_type"] for r in rows)),
        "speech_match_method": dict(count(r["speech_match_method"] for r in rows)),
        "rows_with_speech": sum(1 for r in rows if r["n_turns"]),
        "deputy_rows_with_party": sum(1 for r in deputies if r["party_cargo"]),
        "deputy_rows_with_party_and_speech": sum(1 for r in deputies if r["party_cargo"] and r["n_turns"]),
        "party_distribution_deputy_rows": dict(count(r["party_cargo"] for r in deputies).most_common()),
        "hearings_with_2plus_deputy_parties": sum(1 for v in multi_party.values() if len(v) >= 2),
        "actors_2plus_hearings": sum(1 for v in appearances.values() if v >= 2),
        "actors_in_both_periods": sum(1 for v in periods_by_actor.values() if {"BOLSONARO", "LULA"} <= v),
    }


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    rows, _ = build_actor_hearings(read_jsonl(root / "PublicHearingBR_LDS.jsonl"))
    out = root / "data" / "processed"
    write_csv(out / "party_actor_hearings.csv", rows, FIELDS)
    stats = summary(rows)
    (out / "party_actor_summary.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2) + "\n",
                                                  encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
