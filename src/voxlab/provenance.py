"""Documentary provenance validation for the fixed 25-pair VoxLab pilot.

The official event crosswalk and human evidence review are explicit inputs.
No article publication date is used as a hearing date. NLI labels are never
used to decide whether a span or pair is valid.
"""

from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import json
import re
from dataclasses import dataclass
from pathlib import Path

from .audit import normalize_actor, read_jsonl, tokens, write_csv

MARKER_RE = re.compile(
    r"(?m)^[ \t]*(?P<marker>(?:O SR\.|A SRA\.)[ \t]+"
    r"(?P<label>[^()\n]{2,120}?)(?:[ \t]*\((?P<meta>[^()\n]{1,150})\))?)"
    r"[ \t]*-[ \t]*"
)
OFFICIAL_YEARS = (2022, 2023, 2024)
TRI = {"true", "false", "unknown"}


@dataclass(frozen=True)
class Turn:
    speaker_name: str
    marker_start: int
    text_start: int
    text_end: int
    marker: str
    has_unparsed_marker: bool


def speaker_from_marker(label: str, meta: str | None) -> str:
    """Use an explicit name, including the chair's parenthesized name."""
    label = label.strip().strip("-: ")
    if normalize_actor(label) in {"presidente", "vice presidente", "relator", "relatora"}:
        if not meta or "." not in meta:
            return ""
        name = meta.rsplit(".", 1)[0].strip()
        return name if normalize_actor(name) not in {"bloco", "presidente"} else ""
    return re.sub(r"^(?:DEPUTAD[OA]|SENADOR[A]?)\s+", "", label, flags=re.I).strip()


def parse_turns(transcript: str) -> list[Turn]:
    """Parse line-start speech markers while preserving original offsets."""
    matches = list(MARKER_RE.finditer(transcript))
    result = []
    for i, match in enumerate(matches):
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(transcript)
        body = transcript[start:end]
        unparsed = bool(re.search(r"(?m)^[ \t]*(?:O SR\.|A SRA\.)[ \t]+", body))
        result.append(Turn(speaker_from_marker(match.group("label"), match.group("meta")), match.start(), start, end,
                           match.group("marker"), unparsed))
    return result


def compact_with_map(text: str) -> tuple[str, list[int]]:
    """Collapse whitespace and retain original character positions."""
    output, positions = [], []
    in_space = False
    for index, char in enumerate(text):
        if char.isspace():
            if not in_space:
                output.append(" ")
                positions.append(index)
            in_space = True
        else:
            output.append(char)
            positions.append(index)
            in_space = False
    return "".join(output), positions


def all_occurrences(haystack: str, needle: str) -> list[int]:
    if not needle:
        return []
    positions = []
    start = 0
    while (index := haystack.find(needle, start)) >= 0:
        positions.append(index)
        start = index + 1
    return positions


def locate_chunk(transcript: str, compact: str, char_map: list[int], chunk: str) -> tuple[str, list[tuple[int, int]]]:
    """Return literal spans, first exact and then whitespace-normalized exact."""
    if not chunk.strip():
        return "NO_MATCH", []
    exact = all_occurrences(transcript, chunk)
    if exact:
        return "EXACT_MATCH", [(start, start + len(chunk)) for start in exact]
    normalized = " ".join(chunk.split())
    found = all_occurrences(compact, normalized)
    if found:
        return "NORMALIZED_EXACT_MATCH", [(char_map[start], char_map[start + len(normalized) - 1] + 1) for start in found]
    return "NO_MATCH", []


def containing_turn(turns: list[Turn], start: int, end: int) -> Turn | None:
    return next((turn for turn in turns if turn.text_start <= start and end <= turn.text_end), None)


def read_official_events(root: Path) -> dict[str, dict]:
    """Read the saved official Cámara annual CSV snapshots."""
    events = {}
    for year in OFFICIAL_YEARS:
        file = root / "data" / "raw" / "official_events" / f"eventos-{year}.csv"
        with file.open(encoding="utf-8-sig", newline="") as handle:
            events.update({row["id"]: row for row in csv.DictReader(handle, delimiter=";")})
    return events


def read_crosswalk(root: Path) -> dict[str, dict]:
    file = root / "data" / "annotations" / "pilot_event_crosswalk.csv"
    with file.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != len({r["source_record_id"] for r in rows}):
        raise ValueError("Duplicate source IDs in event crosswalk")
    return {r["source_record_id"]: r for r in rows}


def schema_report(datasets: dict[str, list[dict]]) -> list[dict]:
    """Count field presence across every record, including optional paths."""
    output = []
    roles = {"id": "local dataset record ID; not official event ID", "materia": "article text and publication timestamp",
             "transcricao": "transcript text", "metadados.assunto": "LDS topic summary",
             "metadados.envolvidos[].nome": "LDS actor display name", "metadados.envolvidos[].cargo": "role/identity clue",
             "metadados.envolvidos[].opinioes[]": "LDS opinion summary, not speech",
             "metadados_extraidos.assunto": "NLI topic summary", "metadados_extraidos.envolvidos[].nome": "NLI actor display name",
             "metadados_extraidos.envolvidos[].cargo": "role/identity clue",
             "metadados_extraidos.envolvidos[].opinioes[].opiniao": "NLI opinion summary",
             "metadados_extraidos.envolvidos[].opinioes[].chunks_proximos[]": "candidate transcript evidence, unverified"}
    for dataset, records in datasets.items():
        presence = collections.Counter()
        types = collections.defaultdict(set)
        def walk(value: object, path: str, seen: set[str]) -> None:
            if path:
                seen.add(path)
                types[path].add(type(value).__name__)
            if isinstance(value, dict):
                for key, child in value.items():
                    walk(child, f"{path}.{key}" if path else key, seen)
            elif isinstance(value, list):
                for child in value:
                    walk(child, path + "[]", seen)
        for record in records:
            found: set[str] = set()
            walk(record, "", found)
            presence.update(found)
        for path in sorted(presence):
            role = roles.get(path, "LLM hallucination check; not documentary proof" if "verificacao_alucinacao" in path else "container/auxiliary metadata")
            output.append({"dataset": dataset, "field": path, "presence_count": presence[path],
                           "example_type": "|".join(sorted(types[path])), "possible_semantic_role": role})
    return output


def nli_span_rows(record_id: str, transcript: str, nli_record: dict) -> list[dict]:
    """Locate each NLI chunk and check whether it lies in a named speaker turn."""
    compact, char_map = compact_with_map(transcript)
    turns = parse_turns(transcript)
    output = []
    for actor_index, actor in enumerate(nli_record.get("metadados_extraidos", {}).get("envolvidos", [])):
        for opinion_index, opinion in enumerate(actor.get("opinioes", [])):
            for chunk_index, chunk in enumerate(opinion.get("chunks_proximos", [])):
                if not isinstance(chunk, str) or not chunk.strip():
                    continue
                method, locations = locate_chunk(transcript, compact, char_map, chunk)
                attributed = []
                for start, end in locations:
                    turn = containing_turn(turns, start, end)
                    if turn and not turn.has_unparsed_marker and normalize_actor(turn.speaker_name) == normalize_actor(actor.get("nome", "")):
                        attributed.append((start, end, turn))
                # A repeated quote is usable only if uniquely located in this actor's turns.
                chosen = attributed[0] if len(attributed) == 1 else None
                output.append({"record_id": record_id, "nli_actor_index": actor_index,
                               "nli_opinion_index": opinion_index, "nli_chunk_index": chunk_index,
                               "nli_actor_name": actor.get("nome", ""), "nli_opinion": opinion.get("opiniao", ""),
                               "match_method": method, "occurrences": len(locations), "actor_turn_occurrences": len(attributed),
                               "transcript_start": chosen[0] if chosen else "", "transcript_end": chosen[1] if chosen else "",
                               "matched_text": transcript[chosen[0]:chosen[1]] if chosen else "",
                               "speaker_name": chosen[2].speaker_name if chosen else "",
                               "turn_start": chosen[2].text_start if chosen else "", "turn_end": chosen[2].text_end if chosen else "",
                               "turn_attribution_verified": "true" if chosen else "unknown"})
    return output


def opinion_overlap(a: str, b: str) -> float:
    x, y = set(tokens(a)), set(tokens(b))
    return round(2 * len(x & y) / (len(x) + len(y)), 4) if x and y else 0.0


def speaker_matches_actor(speaker: str, actor: str) -> bool:
    """Require an exact name or one of the documented transcript aliases."""
    expected = normalize_actor(actor)
    actual = normalize_actor(speaker)
    if actual == expected and bool(expected):
        return True
    documented_aliases = {
        "gianna sagazio": {"gianna cardoso sagazio"},
        "nisia trindade": {
            "ministra nisia trindade",
            "ministra nisia trindade lima",
        },
        "ricardo galvao": {"ricardo magnus osorio galvao"},
        "rodrigo agostinho": {"rodrigo antonio de agostinho mendonca"},
        "roselene alves": {"roselene candida alves"},
    }
    return actual in documented_aliases.get(expected, set())


def speech_candidates(pair: dict, side: str, transcript: str) -> list[dict]:
    """Rank literal sentences in explicitly named turns for human review."""
    actor = pair[f"actor_name_{side}"]
    summary = pair[f"summary_{side}"]
    candidates = []
    for turn in parse_turns(transcript):
        if turn.has_unparsed_marker or not speaker_matches_actor(turn.speaker_name, actor):
            continue
        body = transcript[turn.text_start:turn.text_end]
        for match in re.finditer(r"[^.!?\n]+(?:[.!?]|$)", body):
            text = match.group().strip()
            if len(text) < 35:
                continue
            start = turn.text_start + match.start() + len(match.group()) - len(match.group().lstrip())
            end = turn.text_start + match.end() - len(match.group()) + len(match.group().rstrip())
            if end <= start:
                continue
            score = opinion_overlap(summary, text)
            candidates.append({"pair_id": pair["pair_id"], "side": side,
                               "source_record_id": pair[f"source_record_id_{side}"],
                               "actor_name": actor, "source_summary": summary,
                               "speaker_marker": turn.marker,
                               "turn_start": turn.text_start, "turn_end": turn.text_end,
                               "evidence_start": start, "evidence_end": end,
                               "evidence_text": transcript[start:end], "lexical_score": score})
    ranked = sorted(candidates, key=lambda c: (-c["lexical_score"], c["evidence_start"]))[:5]
    for rank, item in enumerate(ranked, 1):
        item["candidate_rank"] = rank
    return ranked


def identity_status(name_a: str, role_a: str, name_b: str, role_b: str) -> tuple[str, str]:
    """Conservative role-based identity check; no stance is considered."""
    if not normalize_actor(name_a) or normalize_actor(name_a) != normalize_actor(name_b):
        return "false", "different_full_names"
    uf_re = re.compile(r"Deputad[ao][^()]*\([^)]*[-–]\s*([A-Z]{2})\)", re.I)
    ufa, ufb = uf_re.search(role_a or ""), uf_re.search(role_b or "")
    if ufa and ufb:
        if ufa.group(1).upper() != ufb.group(1).upper():
            return "unknown", "same_name_conflicting_state_metadata"
        return "true", "same_full_name_and_deputy_state"
    normalized_role_a, normalized_role_b = normalize_actor(role_a), normalize_actor(role_b)
    if normalized_role_a and normalized_role_a == normalized_role_b:
        return "true", "same_full_name_and_identical_role_description"
    organizations = {
        "alexandre da silva": "secretario nacional dos direitos da pessoa idosa",
        "mercedes bustamante": "coordenacao de aperfeicoamento de pessoal",
        "gianna sagazio": "confederacao nacional da industria",
        "vanessa pirolo": "vozes do advocacy",
    }
    name = normalize_actor(name_a)
    if name in organizations and all(organizations[name] in normalize_actor(role) for role in (role_a, role_b)):
        return "true", "same_full_name_and_institutional_role"
    return "unknown", "name_match_only_or_roles_not_equivalent"


def tri_and(*values: str) -> str:
    if any(value == "false" for value in values):
        return "false"
    if all(value == "true" for value in values):
        return "true"
    return "unknown"


def validation_status(row: dict) -> str:
    required = [row[key] for key in ("same_actor_verified", "distinct_events_verified", "temporal_order_verified",
                                       "speech_verified_a", "speech_verified_b", "evidence_verified_a", "evidence_verified_b")]
    if any(value == "false" for value in required):
        return "INVALID"
    if all(value == "true" for value in required):
        return "VALIDATED"
    if any(value == "true" for value in required):
        return "PARTIALLY_VALIDATED"
    return "UNRESOLVED"


def ordered_pair(row: dict) -> dict:
    """Swap A/B consistently if verified official starts contradict proxy order."""
    row = dict(row)
    if row.get("hearing_date_verified_a") == "true" and row.get("hearing_date_verified_b") == "true":
        a, b = row.get("event_start_a", ""), row.get("event_start_b", "")
        if a and b and a > b:
            bases = [key[:-2] for key in row if key.endswith("_a") and key[:-2] + "_b" in row]
            for base in bases:
                row[base + "_a"], row[base + "_b"] = row[base + "_b"], row[base + "_a"]
            row["input_sides_swapped"] = "true"
        else:
            row["input_sides_swapped"] = "false"
    else:
        row["input_sides_swapped"] = "false"
    return row


def pair_validation(row: dict) -> dict:
    """Derive pair status without collapsing unknown into false or true."""
    row = ordered_pair(row)
    ida, idb = row.get("event_id_a", ""), row.get("event_id_b", "")
    if row.get("event_verified_a") == row.get("event_verified_b") == "true" and ida and idb:
        row["distinct_events_verified"] = "true" if ida != idb else "false"
    else:
        row["distinct_events_verified"] = "unknown"
    dates = tri_and(row.get("hearing_date_verified_a", "unknown"), row.get("hearing_date_verified_b", "unknown"))
    if dates == "true" and row["distinct_events_verified"] == "true":
        a, b = row.get("event_start_a", ""), row.get("event_start_b", "")
        row["temporal_order_verified"] = "true" if a and b and a < b else "unknown"
    else:
        row["temporal_order_verified"] = "unknown"
    for side in "ab":
        evidence = row.get(f"evidence_{side}", "")
        speech = row.get(f"speech_text_{side}", "")
        transcript = row.get(f"_transcript_{side}", "")
        named = row.get(f"turn_attribution_verified_{side}", "unknown")
        reviewed = row.get(f"summary_support_reviewed_{side}", "unknown")
        speech_start, speech_end = row.get(f"speech_start_{side}"), row.get(f"speech_end_{side}")
        evidence_start, evidence_end = row.get(f"evidence_start_{side}"), row.get(f"evidence_end_{side}")
        speech_span_valid = bool(speech and transcript and speech_start not in (None, "") and speech_end not in (None, "")
                                 and transcript[int(speech_start):int(speech_end)] == speech)
        evidence_span_valid = bool(evidence and transcript and evidence_start not in (None, "") and evidence_end not in (None, "")
                                   and transcript[int(evidence_start):int(evidence_end)] == evidence)
        nested_span = bool(speech_span_valid and evidence_span_valid
                           and int(speech_start) <= int(evidence_start) < int(evidence_end) <= int(speech_end))
        row[f"speech_verified_{side}"] = "true" if speech_span_valid and named == "true" else "unknown"
        if reviewed == "false":
            row[f"evidence_verified_{side}"] = "false"
        else:
            row[f"evidence_verified_{side}"] = ("true" if row[f"speech_verified_{side}"] == "true" and nested_span
                                                 and reviewed == "true" else "unknown")
    row["validation_status"] = validation_status(row)
    return row


def read_review(root: Path) -> dict[tuple[str, str], dict]:
    file = root / "data" / "annotations" / "pilot_evidence_review.csv"
    if not file.exists():
        return {}
    with file.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != len({(r["pair_id"], r["side"]) for r in rows}):
        raise ValueError("Duplicate pair sides in evidence review")
    return {(r["pair_id"], r["side"]): r for r in rows}


def build_validated(root: Path) -> tuple[list[dict], list[dict], dict]:
    raw = {str(r["id"]): r for r in read_jsonl(root / "PublicHearingBR_LDS.jsonl")}
    nli = {str(r["id"]): r for r in read_jsonl(root / "PublicHearingBR_NLI.jsonl")}
    with (root / "data" / "annotations" / "pilot_pairs.csv").open(newline="", encoding="utf-8") as handle:
        pilot = list(csv.DictReader(handle))
    ids = {p[f"hearing_id_{side}"] for p in pilot for side in "ab"}
    events, crosswalk, reviews = read_official_events(root), read_crosswalk(root), read_review(root)
    all_spans = {rid: nli_span_rows(rid, raw[rid]["transcricao"], nli[rid]) for rid in sorted(ids, key=int)}
    span_lookup = {(r["record_id"], str(r["nli_actor_index"]), str(r["nli_opinion_index"]), str(r["nli_chunk_index"])): r
                   for group in all_spans.values() for r in group}
    output = []
    review_candidates = []
    for pair in pilot:
        record = {"pair_id": pair["pair_id"], "actor_name": pair["actor_name"], "actor_id": pair["actor_id"],
                  "publication_date_a": pair["publication_date_a"], "publication_date_b": pair["publication_date_b"],
                  "same_actor_verified": "unknown", "actor_identity_basis": "", "validation_notes": ""}
        roles = []
        names = []
        for side in "ab":
            rid = pair[f"hearing_id_{side}"]
            source = raw[rid]
            actor_index = int(pair[f"source_actor_index_{side}"])
            opinion_index = int(pair[f"source_opinion_index_{side}"])
            actor = source["metadados"]["envolvidos"][actor_index]
            summary = actor["opinioes"][opinion_index]
            if summary != pair[f"text_{side}"]:
                raise ValueError(f"Pilot source index mismatch for {pair['pair_id']} {side}")
            names.append(actor["nome"])
            roles.append(actor.get("cargo", ""))
            named_turns = [turn for turn in parse_turns(source["transcricao"])
                           if not turn.has_unparsed_marker and speaker_matches_actor(turn.speaker_name, actor["nome"])]
            record.update({f"source_record_id_{side}": rid, f"source_actor_index_{side}": actor_index,
                           f"source_opinion_index_{side}": opinion_index, f"actor_name_{side}": actor["nome"],
                           f"actor_role_{side}": actor.get("cargo", ""), f"summary_{side}": summary,
                           f"actor_marker_verified_{side}": "true" if named_turns else "unknown",
                           f"actor_marker_name_{side}": named_turns[0].speaker_name if named_turns else ""})
            link = crosswalk.get(rid)
            official = events.get(link["official_event_id"]) if link else None
            if official and official.get("situacao", "").startswith("Encerrada") and official.get("dataHoraInicio"):
                record.update({f"event_id_{side}": official["id"], f"event_source_{side}": official["uri"],
                               f"event_type_{side}": official["descricaoTipo"],
                               f"event_title_{side}": "",  # Annual event CSV has a description, not a title field.
                               f"event_description_{side}": official["descricao"],
                               f"event_start_{side}": official["dataHoraInicio"],
                               f"event_date_{side}": official["dataHoraInicio"][:10],
                               f"hearing_date_{side}": official["dataHoraInicio"][:10],
                               f"hearing_date_source_{side}": "official_event_metadata",
                               f"event_verified_{side}": "true", f"hearing_date_verified_{side}": "true",
                               f"event_match_basis_{side}": link["match_basis"],
                               f"event_review_note_{side}": link["review_note"]})
            else:
                record.update({f"event_id_{side}": "", f"event_source_{side}": "", f"event_type_{side}": "",
                               f"event_title_{side}": "", f"event_description_{side}": "",
                               f"event_start_{side}": "", f"event_date_{side}": "", f"hearing_date_{side}": "",
                               f"hearing_date_source_{side}": "",
                               f"event_verified_{side}": "unknown", f"hearing_date_verified_{side}": "unknown",
                               f"event_match_basis_{side}": "", f"event_review_note_{side}": ""})
            review = reviews.get((pair["pair_id"], side), {})
            selected = None
            if review.get("nli_actor_index", ""):
                selected = span_lookup.get((rid, review["nli_actor_index"], review["nli_opinion_index"], review["nli_chunk_index"]))
            if selected and selected["turn_attribution_verified"] == "true":
                start, end = int(selected["turn_start"]), int(selected["turn_end"])
                transcript = source["transcricao"]
                record.update({f"speech_text_{side}": transcript[start:end], f"speech_start_{side}": start,
                               f"speech_end_{side}": end, f"evidence_{side}": selected["matched_text"],
                               f"evidence_start_{side}": selected["transcript_start"],
                               f"evidence_end_{side}": selected["transcript_end"],
                               f"nli_actor_index_{side}": selected["nli_actor_index"],
                               f"nli_opinion_index_{side}": selected["nli_opinion_index"],
                               f"nli_chunk_index_{side}": selected["nli_chunk_index"],
                               f"nli_match_method_{side}": selected["match_method"],
                               f"turn_attribution_verified_{side}": "true"})
            elif review.get("evidence_start", "") and review.get("evidence_end", ""):
                transcript = source["transcricao"]
                start, end = int(review["evidence_start"]), int(review["evidence_end"])
                turn = containing_turn(parse_turns(transcript), start, end)
                if not 0 <= start < end <= len(transcript) or not turn or turn.has_unparsed_marker or not speaker_matches_actor(turn.speaker_name, actor["nome"]):
                    raise ValueError(f"Invalid reviewed speech span for {pair['pair_id']} {side}")
                if review.get("reviewed_evidence_text", "") != transcript[start:end]:
                    raise ValueError(f"Reviewed evidence text does not match offsets for {pair['pair_id']} {side}")
                record.update({f"speech_text_{side}": transcript[turn.text_start:turn.text_end],
                               f"speech_start_{side}": turn.text_start, f"speech_end_{side}": turn.text_end,
                               f"evidence_{side}": transcript[start:end], f"evidence_start_{side}": start,
                               f"evidence_end_{side}": end, f"nli_actor_index_{side}": "",
                               f"nli_opinion_index_{side}": "", f"nli_chunk_index_{side}": "",
                               f"nli_match_method_{side}": "DIRECT_TRANSCRIPT_REVIEW",
                               f"turn_attribution_verified_{side}": "true"})
            else:
                record.update({f"speech_text_{side}": "", f"speech_start_{side}": "", f"speech_end_{side}": "",
                               f"evidence_{side}": "", f"evidence_start_{side}": "", f"evidence_end_{side}": "",
                               f"nli_actor_index_{side}": "", f"nli_opinion_index_{side}": "", f"nli_chunk_index_{side}": "",
                               f"nli_match_method_{side}": "", f"turn_attribution_verified_{side}": "unknown"})
            record[f"summary_support_reviewed_{side}"] = review.get("summary_support_reviewed", "unknown")
            record[f"review_note_{side}"] = review.get("review_note", "")
            record[f"_transcript_{side}"] = source["transcricao"]
            review_candidates.extend(speech_candidates(record, side, source["transcricao"]))
        record["same_actor_verified"], record["actor_identity_basis"] = identity_status(names[0], roles[0], names[1], roles[1])
        for side in "ab":
            record[f"actor_verified_{side}"] = tri_and(record["same_actor_verified"], record[f"actor_marker_verified_{side}"])
        record = pair_validation(record)
        record.pop("_transcript_a")
        record.pop("_transcript_b")
        output.append(record)
    spans = [row for rid in sorted(all_spans, key=int) for row in all_spans[rid]]
    return output, spans, {"raw": list(raw.values()), "nli": list(nli.values()), "review_candidates": review_candidates}


def funnel(rows: list[dict]) -> dict:
    """Sequential, non-increasing counts for documentary validation."""
    stages = [
        ("candidate_pairs", lambda r: True),
        ("distinct_events_verified", lambda r: r["distinct_events_verified"] == "true"),
        ("same_actor_verified", lambda r: r["same_actor_verified"] == "true"),
        ("both_hearing_dates_verified", lambda r: r["hearing_date_verified_a"] == r["hearing_date_verified_b"] == "true"),
        ("temporal_order_verified", lambda r: r["temporal_order_verified"] == "true"),
        ("both_speeches_verified", lambda r: r["speech_verified_a"] == r["speech_verified_b"] == "true"),
        ("both_evidence_spans_verified", lambda r: r["evidence_verified_a"] == r["evidence_verified_b"] == "true"),
        ("fully_validated", lambda r: r["validation_status"] == "VALIDATED"),
    ]
    survivors = rows
    counts = {}
    for label, condition in stages:
        survivors = [row for row in survivors if condition(row)]
        counts[label] = len(survivors)
    reasons = collections.Counter()
    for row in rows:
        if row["distinct_events_verified"] != "true": reasons["EVENT_NOT_IDENTIFIED_OR_SAME_EVENT"] += 1
        if row["same_actor_verified"] != "true": reasons["ACTOR_AMBIGUOUS_OR_DIFFERENT"] += 1
        if row["hearing_date_verified_a"] != "true" or row["hearing_date_verified_b"] != "true": reasons["MISSING_HEARING_DATE"] += 1
        if row["speech_verified_a"] != "true" or row["speech_verified_b"] != "true": reasons["SPEECH_NOT_LOCATED"] += 1
        if (row["summary_support_reviewed_a"] == "unknown" or row["summary_support_reviewed_b"] == "unknown"):
            reasons["SUMMARY_EVIDENCE_LINK_UNCERTAIN"] += 1
        if row["summary_support_reviewed_a"] == "false" or row["summary_support_reviewed_b"] == "false":
            reasons["SUMMARY_TRANSCRIPT_MISMATCH"] += 1
    return {"stages": counts, "status": dict(collections.Counter(r["validation_status"] for r in rows)),
            "reasons_nonexclusive": dict(sorted(reasons.items()))}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    root = args.root
    rows, spans, datasets = build_validated(root)
    processed = root / "data" / "processed"
    write_csv(processed / "provenance_schema.csv", schema_report({"LDS": datasets["raw"], "NLI": datasets["nli"]}),
              ["dataset", "field", "presence_count", "example_type", "possible_semantic_role"])
    write_csv(processed / "pilot_nli_spans.csv", spans, list(spans[0]))
    candidates = datasets["review_candidates"]
    write_csv(processed / "pilot_speech_candidates.csv", candidates, list(candidates[0]))
    clean_rows = [{key: value for key, value in row.items() if not key.startswith("_")} for row in rows]
    write_csv(root / "data" / "annotations" / "pilot_pairs_validated.csv", clean_rows, list(clean_rows[0]))
    report = funnel(rows)
    report["nli_pilot_chunks"] = {"total": len(spans), "match_methods": dict(collections.Counter(r["match_method"] for r in spans)),
                                  "unique_named_actor_turn": sum(r["turn_attribution_verified"] == "true" for r in spans)}
    (processed / "provenance_funnel.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
