"""Câmara dos Deputados roll-call data for the party-alignment track.

Bulk yearly CSVs from dadosabertos.camara.leg.br (the REST API has no
per-deputy vote endpoint). Files are snapshotted under data/raw/camara_api/
with SHA-256 hashes, like data/raw/official_events/.

Derived here (no LLM, no stance):
- the government leader's orientation per roll call;
- each deputy's governism per government period: the share of their Sim/Não
  votes that match the government orientation, over roll calls where the
  government oriented Sim or Não;
- each deputy's party on a date, taken from their own vote records (party
  switching is common in Brazil, so party is dated, not fixed);
- party-pair co-voting agreement per period.

Default is a dry run listing the files; downloading requires --download:
    PYTHONPATH=src python3 -m voxlab.camara_api
    PYTHONPATH=src python3 -m voxlab.camara_api --download
"""

from __future__ import annotations

import argparse
import bisect
import collections
import csv
import hashlib
import http.client
import itertools
import json
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from .actors import PARTY_ALIASES, government_period
from .audit import normalize_actor

BASE = "https://dadosabertos.camara.leg.br/arquivos"
YEARS = (2022, 2023, 2024)
FILE_KINDS = ("votacoes", "votacoesVotos", "votacoesOrientacoes")
RAW_DIR = Path("data/raw/camara_api")
GOVERNMENT_BANCADAS = {"governo", "gov", "lider do governo", "lideranca do governo"}
DIRECTIONAL_VOTES = {"sim": "SIM", "nao": "NAO"}
# Column names as documented by the Câmara bulk files; checked on load so a
# schema change fails loudly instead of producing silent empty results.
VOTE_COLUMNS = {"idVotacao", "voto", "deputado_id", "deputado_nome", "deputado_siglaPartido", "deputado_siglaUf"}
ORIENTATION_COLUMNS = {"idVotacao", "siglaBancada", "orientacao"}
ROLLCALL_COLUMNS = {"id", "data"}


def file_urls() -> dict[str, str]:
    urls = {f"{kind}-{year}.csv": f"{BASE}/{kind}/csv/{kind}-{year}.csv" for kind in FILE_KINDS for year in YEARS}
    urls["deputados.csv"] = f"{BASE}/deputados/csv/deputados.csv"
    return urls


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def fetch(url: str, path: Path, attempts: int = 20) -> None:
    """Stream to a .part file, resuming with HTTP Range after dropped connections
    (the server cuts large files mid-transfer); rename only when the size matches."""
    partial = path.with_name(path.name + ".part")
    total = None
    for attempt in range(attempts):
        offset = partial.stat().st_size if partial.exists() else 0
        if total is not None and offset == total:
            break
        request = urllib.request.Request(url, headers={"Range": f"bytes={offset}-"} if offset else {})
        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                if offset and response.status != 206:
                    raise RuntimeError(f"{url}: server ignored Range request")
                content_range = response.headers.get("Content-Range")
                total = int(content_range.rsplit("/", 1)[1]) if content_range else int(response.headers["Content-Length"])
                with partial.open("ab" if offset else "wb") as handle:
                    for block in iter(lambda: response.read(1 << 20), b""):
                        handle.write(block)
        except (OSError, http.client.HTTPException):
            time.sleep(min(2 ** attempt, 30))
            continue
        if partial.stat().st_size == total:
            break
    if total is None or partial.stat().st_size != total:
        raise RuntimeError(f"download failed for {url} after {attempts} attempts")
    partial.rename(path)


def download(root: Path) -> dict:
    out = root / RAW_DIR
    out.mkdir(parents=True, exist_ok=True)
    sources = {}
    for name, url in file_urls().items():
        path = out / name
        if not path.exists():
            fetch(url, path)
            print(f"downloaded {name}", flush=True)
        sources[name] = {"url": url, "sha256": sha256_file(path), "bytes": path.stat().st_size}
    manifest = {"retrieved_at": datetime.now(timezone.utc).isoformat(), "files": sources}
    (out / "SOURCES.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------

def read_semicolon_csv(path: Path, required: set[str]) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{path.name}: missing columns {sorted(missing)}; header={reader.fieldnames}")
        return list(reader)


def canonical_party(sigla: str) -> str:
    key = (sigla or "").strip().upper().replace(" ", "")
    return PARTY_ALIASES.get(key, key)


def normalize_vote(value: str) -> str:
    return DIRECTIONAL_VOTES.get(normalize_actor(value), "")


def load(root: Path) -> tuple[list[dict], list[dict], dict[str, str]]:
    """(vote rows, orientation rows, {idVotacao: ISO date}) for all years."""
    raw = root / RAW_DIR
    votes, orientations, dates = [], [], {}
    for year in YEARS:
        votes += read_semicolon_csv(raw / f"votacoesVotos-{year}.csv", VOTE_COLUMNS)
        orientations += read_semicolon_csv(raw / f"votacoesOrientacoes-{year}.csv", ORIENTATION_COLUMNS)
        for row in read_semicolon_csv(raw / f"votacoes-{year}.csv", ROLLCALL_COLUMNS):
            dates[row["id"]] = row["data"][:10]
    return votes, orientations, dates


# --------------------------------------------------------------------------
# Derivations (pure functions, tested offline)
# --------------------------------------------------------------------------

def government_orientation(orientations: list[dict]) -> dict[str, str]:
    """{idVotacao: SIM|NAO} for roll calls where the government oriented a direction."""
    result = {}
    for row in orientations:
        if normalize_actor(row["siglaBancada"]) in GOVERNMENT_BANCADAS:
            direction = normalize_vote(row["orientacao"])
            if direction:
                result[row["idVotacao"]] = direction
    return result


def governism(votes: list[dict], orientation: dict[str, str], dates: dict[str, str]) -> dict[tuple[str, str], dict]:
    """{(deputado_id, period): {"n": votes counted, "governism": share matching}}."""
    counts = collections.defaultdict(lambda: [0, 0])
    for row in votes:
        vote_id = row["idVotacao"]
        vote = normalize_vote(row["voto"])
        if vote_id not in orientation or not vote or vote_id not in dates:
            continue
        cell = counts[(row["deputado_id"], government_period(dates[vote_id]))]
        cell[0] += 1
        cell[1] += vote == orientation[vote_id]
    return {key: {"n": n, "governism": round(hit / n, 4)} for key, (n, hit) in counts.items()}


def deputy_directory(votes: list[dict], dates: dict[str, str]) -> dict[str, dict]:
    """{deputado_id: {"name", "uf", "party_timeline": [(date, party), ...]}} from vote records."""
    directory: dict[str, dict] = {}
    for row in votes:
        date = dates.get(row["idVotacao"])
        if not date:
            continue
        entry = directory.setdefault(row["deputado_id"], {"name": row["deputado_nome"], "uf": row["deputado_siglaUf"],
                                                          "party_timeline": set()})
        entry["party_timeline"].add((date, canonical_party(row["deputado_siglaPartido"])))
    for entry in directory.values():
        entry["party_timeline"] = sorted(entry["party_timeline"])
    return directory


def party_on(timeline: list[tuple[str, str]], date: str) -> str:
    """Party at the closest recorded vote on or before date; else the first recorded."""
    if not timeline:
        return ""
    position = bisect.bisect_right(timeline, (date, "￿"))
    return timeline[position - 1][1] if position else timeline[0][1]


def match_deputies(actor_rows: list[dict], directory: dict[str, dict]) -> dict[str, tuple[str, str]]:
    """{actor_id: (deputado_id, method)} by normalized parliamentary name; UF breaks ties.
    Ambiguous or missing names are left unmatched rather than guessed."""
    by_name = collections.defaultdict(list)
    for deputy_id, entry in directory.items():
        by_name[normalize_actor(entry["name"])].append(deputy_id)
    result = {}
    for row in actor_rows:
        if row["actor_type"] != "DEPUTY" or row["actor_id"] in result:
            continue
        candidates = by_name.get(row["actor_id"], [])
        if len(candidates) > 1 and row["uf_cargo"]:
            candidates = [c for c in candidates if directory[c]["uf"] == row["uf_cargo"]]
        if len(candidates) != 1:
            continue
        if not row["uf_cargo"]:
            method = "NAME"
        elif directory[candidates[0]]["uf"] == row["uf_cargo"]:
            method = "NAME_UF_CONSISTENT"
        else:
            method = "NAME_UF_MISMATCH"
        result[row["actor_id"]] = (candidates[0], method)
    return result


def party_covoting(votes: list[dict], dates: dict[str, str]) -> dict[tuple[str, str, str], dict]:
    """{(period, party_a, party_b): {"n", "agreement"}} — share of roll calls where the
    two parties' majority Sim/Não positions coincide."""
    tallies = collections.defaultdict(collections.Counter)
    for row in votes:
        vote = normalize_vote(row["voto"])
        if vote and row["idVotacao"] in dates:
            tallies[(row["idVotacao"], canonical_party(row["deputado_siglaPartido"]))][vote] += 1
    majority = collections.defaultdict(dict)
    for (vote_id, party), counter in tallies.items():
        ranked = counter.most_common(2)
        if len(ranked) == 1 or ranked[0][1] > ranked[1][1]:
            majority[vote_id][party] = ranked[0][0]
    counts = collections.defaultdict(lambda: [0, 0])
    for vote_id, positions in majority.items():
        period = government_period(dates[vote_id])
        for a, b in itertools.combinations(sorted(positions), 2):
            cell = counts[(period, a, b)]
            cell[0] += 1
            cell[1] += positions[a] == positions[b]
    return {key: {"n": n, "agreement": round(hit / n, 4)} for key, (n, hit) in counts.items()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--download", action="store_true", help="download the bulk files (network)")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    urls = file_urls()
    missing = [name for name in urls if not (root / RAW_DIR / name).exists()]
    print(json.dumps({"files": urls, "missing_locally": missing}, indent=2))
    if not args.download:
        print("Dry run: nothing was downloaded. Re-run with --download after approval.")
        return
    print(json.dumps(download(root), indent=2))


if __name__ == "__main__":
    main()
