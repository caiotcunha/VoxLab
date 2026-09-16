"""Audit PublicHearingBR and retrieve exploratory longitudinal pairs.

No stance or comparability decision is made here. Dates printed in the source
article are publication dates, not verified hearing dates.
"""

from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import hashlib
import itertools
import json
import math
import re
import unicodedata
from pathlib import Path


DATE_RE = re.compile(r"\b(\d{2}/\d{2}/\d{4})\s*-\s*\d{2}:\d{2}\b")
WORD_RE = re.compile(r"[a-z0-9]+")
STOP = set("a ao aos as o os de da do das dos e em para por com sobre que um uma no na nos nas pelo pela seus suas sua seu ser".split())
FIELDS = ["source_dataset", "source_hearing_id", "source_actor_index", "source_opinion_index", "actor_id", "actor_name", "actor_role", "hearing_id", "hearing_date", "publication_date", "date_basis", "hearing_topic", "speech_text", "text_kind", "evidence", "evidence_status", "target_proposition", "stance_silver"]


def normalize_actor(name: str) -> str:
    """Make a conservative name key; this is not a verified person identifier."""
    name = unicodedata.normalize("NFKD", name or "")
    name = "".join(ch for ch in name if not unicodedata.combining(ch))
    return " ".join(WORD_RE.findall(name.casefold()))


def tokens(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFKD", text or "")
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return [w for w in WORD_RE.findall(normalized.casefold()) if len(w) > 2 and w not in STOP]


def read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def read_silver(path: Path) -> dict[tuple[str, str, str], list[dict]]:
    result = collections.defaultdict(list)
    if not path.exists():
        return result
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            key = (row["id_audiencia"], normalize_actor(row["nome"]), row["opiniao_limpa"].strip())
            result[key].append(row)
    return result


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def build_longitudinal(raw: list[dict], silver: dict) -> tuple[list[dict], dict]:
    """Flatten LDS opinions, retaining exact source indices and silver provenance."""
    rows = []
    invalid_dates = []
    for hearing in raw:
        hid = str(hearing["id"])
        match = DATE_RE.search(hearing.get("materia", ""))
        publication_date = ""
        if match:
            try:
                publication_date = dt.datetime.strptime(match.group(1), "%d/%m/%Y").date().isoformat()
            except ValueError:
                invalid_dates.append(hid)
        for actor_index, actor in enumerate(hearing.get("metadados", {}).get("envolvidos", [])):
            name = (actor.get("nome") or "").strip()
            actor_id = normalize_actor(name)
            if not actor_id:
                continue
            for opinion_index, opinion in enumerate(actor.get("opinioes", [])):
                text = opinion.strip() if isinstance(opinion, str) else ""
                if not text:
                    continue
                matches = silver.get((hid, actor_id, text), [])
                rows.append({
                    "source_dataset": "PublicHearingBR_LDS.jsonl",
                    "source_hearing_id": hid,
                    "source_actor_index": actor_index,
                    "source_opinion_index": opinion_index,
                    "actor_id": actor_id,
                    "actor_name": name,
                    "actor_role": actor.get("cargo", ""),
                    "hearing_id": hid,
                    "hearing_date": "",  # Absent from the supplied schema.
                    "publication_date": publication_date,
                    "date_basis": "article_publication_only" if publication_date else "missing",
                    "hearing_topic": hearing.get("metadados", {}).get("assunto", ""),
                    "speech_text": text,
                    "text_kind": "LDS_opinion_summary_not_verbatim_speech",
                    "evidence": "",
                    "evidence_status": "not_verified_in_transcript",
                    "target_proposition": " | ".join(dict.fromkeys(m["proposicao_alvo"] for m in matches if m["proposicao_alvo"])),
                    "stance_silver": " | ".join(dict.fromkeys(m["postura_final"] for m in matches if m["postura_final"])),
                })
    return rows, {"invalid_publication_date_ids": invalid_dates}


def tfidf_vectors(topics: dict[str, str]) -> dict[str, dict[str, float]]:
    """L2-normalized TF-IDF vectors of hearing subjects, with no downloads."""
    docs = {key: collections.Counter(tokens(value)) for key, value in topics.items()}
    df = collections.Counter(word for doc in docs.values() for word in doc)
    n = len(docs)
    vectors = {}
    for key, counts in docs.items():
        vec = {word: (1 + math.log(count)) * (math.log((1 + n) / (1 + df[word])) + 1) for word, count in counts.items()}
        norm = math.sqrt(sum(value * value for value in vec.values()))
        vectors[key] = {word: value / norm for word, value in vec.items()} if norm else {}
    return vectors


def cosine(a: dict[str, float], b: dict[str, float]) -> float:
    return sum(value * b.get(word, 0) for word, value in a.items())


def hearing_pairs(rows: list[dict]) -> list[dict]:
    """Enumerate unique same-name, different-hearing pairs with article dates."""
    actor_hearings = collections.defaultdict(lambda: collections.defaultdict(list))
    topics = {}
    for row in rows:
        actor_hearings[row["actor_id"]][row["hearing_id"]].append(row)
        topics[row["hearing_id"]] = row["hearing_topic"]
    vectors = tfidf_vectors(topics)
    pairs = []
    for actor, hearings in actor_hearings.items():
        ids = sorted(hearings)
        for id_a, id_b in itertools.combinations(ids, 2):
            a, b = hearings[id_a][0], hearings[id_b][0]
            if not a["publication_date"] or not b["publication_date"] or a["publication_date"] == b["publication_date"]:
                continue
            if a["publication_date"] > b["publication_date"]:
                id_a, id_b = id_b, id_a
            pairs.append({"actor_id": actor, "hearing_id_a": id_a, "hearing_id_b": id_b,
                          "topic_similarity": round(cosine(vectors[id_a], vectors[id_b]), 6),
                          "gap_publication_days": (dt.date.fromisoformat(hearings[id_b][0]["publication_date"]) - dt.date.fromisoformat(hearings[id_a][0]["publication_date"])).days})
    return pairs


def select_pairs(hearing_candidates: list[dict], rows: list[dict], threshold: float, top_k: int) -> list[dict]:
    """Retrieve up to top_k later hearings per actor and earlier hearing."""
    lookup = collections.defaultdict(list)
    for row in rows:
        lookup[(row["actor_id"], row["hearing_id"])].append(row)
    eligible = [p for p in hearing_candidates if p["topic_similarity"] >= threshold]
    grouped = collections.defaultdict(list)
    for p in eligible:
        grouped[(p["actor_id"], p["hearing_id_a"])].append(p)
    selected = []
    for group in grouped.values():
        selected.extend(sorted(group, key=lambda p: (-p["topic_similarity"], p["hearing_id_b"]))[:top_k])
    output = []
    for pair in selected:
        a_options = lookup[(pair["actor_id"], pair["hearing_id_a"])]
        b_options = lookup[(pair["actor_id"], pair["hearing_id_b"])]
        # Choose the most lexically related summaries; stance silver is never used.
        a, b = max(itertools.product(a_options, b_options), key=lambda ab: (len(set(tokens(ab[0]["speech_text"])) & set(tokens(ab[1]["speech_text"]))), -int(ab[0]["source_opinion_index"]), -int(ab[1]["source_opinion_index"])))
        pid = hashlib.sha256(f"{pair['actor_id']}|{pair['hearing_id_a']}|{pair['hearing_id_b']}".encode()).hexdigest()[:16]
        record = {"pair_id": pid, "actor_id": pair["actor_id"], "actor_name": a["actor_name"],
                  "topic_similarity": pair["topic_similarity"], "gap_publication_days": pair["gap_publication_days"],
                  "temporal_order_verified": "false", "date_basis": "article_publication_only", "candidate_method": "topic_tfidf_cosine"}
        for suffix, item in (("a", a), ("b", b)):
            for original, renamed in (("source_dataset", "source_dataset"), ("hearing_id", "hearing_id"), ("hearing_date", "hearing_date"), ("publication_date", "publication_date"), ("hearing_topic", "topic"), ("speech_text", "text"), ("text_kind", "text_kind"), ("target_proposition", "proposition_silver"), ("stance_silver", "stance_silver"), ("evidence", "evidence"), ("evidence_status", "evidence_status"), ("source_actor_index", "source_actor_index"), ("source_opinion_index", "source_opinion_index")):
                record[f"{renamed}_{suffix}"] = item[original]
        output.append(record)
    return sorted(output, key=lambda p: (p["actor_id"], p["publication_date_a"], p["publication_date_b"], p["pair_id"]))


def pilot_sample(pairs: list[dict], target: int = 25) -> list[dict]:
    """Deterministic round-robin over similarity bands, actors and gaps."""
    bands = {"low": [], "medium": [], "high": []}
    for pair in pairs:
        score = pair["topic_similarity"]
        band = "high" if score >= .3 else "medium" if score >= .15 else "low"
        bands[band].append(pair)
    for band in bands:
        bands[band].sort(key=lambda p: (p["actor_id"], -p["gap_publication_days"], p["pair_id"]))
    chosen = []
    used_actors = set()
    while len(chosen) < target and any(bands.values()):
        for band in ("low", "medium", "high"):
            if not bands[band] or len(chosen) >= target:
                continue
            index = next((i for i, p in enumerate(bands[band]) if p["actor_id"] not in used_actors), 0)
            item = bands[band].pop(index)
            chosen.append(item)
            used_actors.add(item["actor_id"])
    return chosen


def audit_metrics(raw: list[dict], rows: list[dict], possible: list[dict], selected: list[dict], threshold: float, top_k: int) -> dict:
    hearings_by_actor = collections.defaultdict(set)
    actors_by_topic = collections.defaultdict(set)
    topics = {}
    dates = {}
    for row in rows:
        hearings_by_actor[row["actor_id"]].add(row["hearing_id"])
        actors_by_topic[row["hearing_topic"]].add(row["actor_id"])
        topics[row["hearing_id"]] = row["hearing_topic"]
        dates[row["hearing_id"]] = row["publication_date"]
    distribution = collections.Counter(len(h) for h in hearings_by_actor.values())
    consecutive_gaps = []
    for hearing_ids in hearings_by_actor.values():
        ordered = sorted(dt.date.fromisoformat(dates[hid]) for hid in hearing_ids if dates[hid])
        consecutive_gaps.extend((b - a).days for a, b in zip(ordered, ordered[1:]))
    def gap_band(days: int) -> str:
        return "0-30" if days <= 30 else "31-180" if days <= 180 else "181-365" if days <= 365 else "366+"
    actor_names = {r["actor_id"]: r["actor_name"] for r in rows}
    return {
        "labels": {"corpus_counts": "OBSERVED/DERIVED", "pairs": "HEURISTIC", "stance": "LLM/SILVER", "human_gold": "NONE"},
        "source": {"dataset": "PublicHearingBR_LDS.jsonl", "date_semantics": "date in materia is article publication; hearing date unavailable", "actor_id_semantics": "accent/case/punctuation normalized name; identity unverified", "text_semantics": "LDS opinion summaries, not verbatim speech"},
        "config": {"topic_method": "local word TF-IDF cosine of LDS assunto", "threshold": threshold, "top_k_later_hearings_per_actor_earlier_hearing": top_k},
        "counts": {"total_hearings": len(raw), "unique_actors_normalized_names": len(hearings_by_actor), "opinion_summaries": len(rows),
                   "actors_2plus_hearings": sum(len(v) >= 2 for v in hearings_by_actor.values()),
                   "actors_3plus_hearings": sum(len(v) >= 3 for v in hearings_by_actor.values()),
                   "actors_5plus_hearings": sum(len(v) >= 5 for v in hearings_by_actor.values()),
                   "hearings_with_publication_date": sum(bool(d) for d in dates.values()),
                   "hearings_with_verified_hearing_date": 0,
                   "possible_actor_hearing_pairs_with_distinct_publication_dates": len(possible),
                   "candidate_pairs_proxy_order": len(selected),
                   "candidate_pairs_verified_hearing_order": 0,
                   "candidate_actors_proxy_order": len({p["actor_id"] for p in selected})},
        "hearing_count_distribution": dict(sorted(distribution.items())),
        "publication_gap_days_distribution_all_pairs": dict(sorted(collections.Counter(gap_band(p["gap_publication_days"]) for p in possible).items())),
        "publication_gap_days_distribution_consecutive_appearances": dict(sorted(collections.Counter(gap_band(gap) for gap in consecutive_gaps).items())),
        "top_actors": [{"actor_id": actor, "actor_name": actor_names[actor], "hearings": len(h), "first_publication": min(dates[i] for i in h if dates[i]), "last_publication": max(dates[i] for i in h if dates[i])} for actor, h in sorted(hearings_by_actor.items(), key=lambda x: (-len(x[1]), x[0]))[:20]],
        "top_exact_topics": [{"topic": topic, "hearings": n, "actors": len(actors_by_topic[topic])} for topic, n in collections.Counter(topics.values()).most_common(20)],
        "topic_recurrent_actors_exact_title": {topic: sum(len({p["hearing_id"] for p in rows if p["actor_id"] == actor and p["hearing_topic"] == topic}) >= 2 for actor in actors) for topic, actors in actors_by_topic.items() if sum(t == topic for t in topics.values()) >= 2},
        "threshold_sensitivity_unlimited": {str(t): sum(p["topic_similarity"] >= t for p in possible) for t in (0, .05, .1, .15, .2, .3, .4, .5, .6, .7, .8)},
    }


def evidence_metrics(raw: list[dict], nli: list[dict], rows: list[dict]) -> dict:
    """Count source-verifiable substrings; no chunk is assigned to an LDS claim."""
    transcripts = {str(record["id"]): record.get("transcricao", "") for record in raw}
    lds_exact = sum(row["speech_text"] in transcripts[row["source_hearing_id"]] for row in rows)
    nli_total = nli_exact = nli_space = 0
    for record in nli:
        transcript = transcripts.get(str(record["id"]), "")
        compact_transcript = " ".join(transcript.split())
        for actor in record.get("metadados_extraidos", {}).get("envolvidos", []):
            for opinion in actor.get("opinioes", []):
                for chunk in opinion.get("chunks_proximos", []):
                    if not isinstance(chunk, str) or not chunk.strip():
                        continue
                    nli_total += 1
                    nli_exact += chunk in transcript
                    nli_space += " ".join(chunk.split()) in compact_transcript
    return {"lds_summary_exact_transcript_matches": lds_exact,
            "lds_summaries_checked": len(rows), "nli_nonempty_chunks": nli_total,
            "nli_chunk_exact_matches": nli_exact,
            "nli_chunk_whitespace_normalized_matches": nli_space}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--threshold", type=float, default=0.1)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--pilot-size", type=int, default=25)
    args = parser.parse_args()
    if not 0 <= args.threshold <= 1 or args.top_k < 1 or args.pilot_size < 1:
        parser.error("threshold must be in [0,1], top-k and pilot-size must be positive")
    root = args.root
    raw = read_jsonl(root / "PublicHearingBR_LDS.jsonl")
    silver = read_silver(root / "base_posturas_classificadas.csv")
    rows, diagnostics = build_longitudinal(raw, silver)
    out = root / "data" / "processed"
    write_csv(out / "longitudinal.csv", rows, FIELDS)
    possible = hearing_pairs(rows)
    selected = select_pairs(possible, rows, args.threshold, args.top_k)
    pair_fields = list(selected[0]) if selected else ["pair_id", "actor_id", "actor_name", "topic_similarity", "temporal_order_verified"]
    write_csv(out / "candidate_pairs.csv", selected, pair_fields)
    metrics = audit_metrics(raw, rows, possible, selected, args.threshold, args.top_k)
    metrics["diagnostics"] = diagnostics
    nli_path = root / "PublicHearingBR_NLI.jsonl"
    metrics["evidence"] = evidence_metrics(raw, read_jsonl(nli_path), rows) if nli_path.exists() else {"nli_file_missing": True}
    pilot = pilot_sample(selected, args.pilot_size)
    metrics["pilot"] = {"size": len(pilot), "actors": len({p["actor_id"] for p in pilot}), "similarity_bands": dict(collections.Counter("high" if p["topic_similarity"] >= .3 else "medium" if p["topic_similarity"] >= .15 else "low" for p in pilot))}
    (out / "audit_summary.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    annotation = root / "data" / "annotations"
    write_csv(annotation / "pilot_pairs.csv", pilot, pair_fields)
    blind_fields = ["pair_id", "topic_similarity", "gap_publication_days", "topic_a", "text_a", "topic_b", "text_b", "date_basis", "text_kind_a", "text_kind_b"]
    blind = []
    for pair in pilot:
        record = {key: pair.get(key, "") for key in blind_fields}
        # Remove the focal actor's displayed name when repeated in a summary.
        if pair["actor_name"]:
            for key in ("topic_a", "topic_b", "text_a", "text_b"):
                record[key] = re.sub(re.escape(pair["actor_name"]), "[ATOR]", record[key], flags=re.I)
        blind.append(record)
    write_csv(annotation / "pilot_pairs_blind.csv", blind, blind_fields)
    template_fields = blind_fields + ["stance_determinable_both", "same_specific_proposition", "stance_a", "stance_b", "relation", "confidence", "notes", "transcript_verified", "hearing_dates_verified"]
    write_csv(annotation / "pilot_annotation_template.csv", blind, template_fields)
    print(json.dumps({"counts": metrics["counts"], "pilot": metrics["pilot"], "threshold_sensitivity_unlimited": metrics["threshold_sensitivity_unlimited"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
