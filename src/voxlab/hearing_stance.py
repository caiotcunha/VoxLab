"""LLM stance extraction for the party-alignment track (external API calls).

Two frozen stages, each cached per call in
``data/processed/llm_raw_outputs/party_alignment/``:

1. ``propositions``: one call per hearing, a single fixed model
   (PROPOSITION_MODEL), extracts 1-3 contested propositions from the LDS
   topic and the news article. One model only, so every stance model is
   scored against the same targets.
2. ``stance``: one call per actor x hearing x model x input condition. The
   model is blind to name, party, UF and role, and returns stance on each
   hearing proposition plus stance toward the federal government in office
   (and toward previous governments).

Input conditions (RQ4): ``speech`` uses the actor's literal transcript turns
(voxlab.actors); ``lds_summary`` uses the LDS news-derived opinion summaries.

Every output is ``label_source=MODEL_PREDICTION``; there is no gold for these
targets. Malformed outputs are flagged, never folded into UNCERTAIN.

Default is a dry run that sends nothing and prints the request plan and cost
estimate. Sending requires ``--execute`` (and DEEPINFRA_API_KEY):
    PYTHONPATH=src python3 -m voxlab.hearing_stance --stage propositions
    PYTHONPATH=src python3 -m voxlab.hearing_stance --stage propositions --execute
"""

from __future__ import annotations

import argparse
import collections
import concurrent.futures
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .actors import build_actor_hearings
from .audit import read_jsonl, write_csv
from .automatic_baselines import _extract_json, _git_commit
from .llm_client import chat_completion, completion_text

MODELS = ("Qwen/Qwen2.5-72B-Instruct", "meta-llama/Llama-3.3-70B-Instruct-Turbo")
PROPOSITION_MODEL = MODELS[0]
# USD per million tokens (input, output), confirmed on DeepInfra in the
# previous round (docs/automatic_experiments.md §3). Used only for estimates.
PRICES = {MODELS[0]: (0.36, 0.40), MODELS[1]: (0.10, 0.32)}
CONDITIONS = ("speech", "lds_summary")
# Robustness condition (plan item 3): literal speech with speaker-identifying cues masked.
MASKED = "speech_masked"
ALL_CONDITIONS = (MASKED, *CONDITIONS)  # longest prefix first when parsing file names
PRESIDENTS = {"BOLSONARO": "Jair Bolsonaro", "LULA": "Luiz Inácio Lula da Silva"}
SPEECH_LABELS = {
    "speech": "Manifestação literal do participante (seus turnos de fala na transcrição, em ordem)",
    "lds_summary": "Resumo jornalístico das opiniões do participante (não é fala literal; foi redigido a partir da notícia)",
    MASKED: ("Manifestação literal do participante (seus turnos de fala na transcrição, em ordem), com nomes de "
             "pessoas e de partidos substituídos por marcadores"),
}
PARTY_MENTION_RE = re.compile(
    # Case-sensitive on purpose. Party names that are also common words (Podemos, Cidadania,
    # Solidariedade, Progressistas) only count in capitals or after "Partido"; "PL" followed by a
    # number or by "da/das/do/de" is a bill ("projeto de lei"), not the party.
    r"\b(?:Partido (?:dos Trabalhadores|Liberal|Novo|Socialismo e Liberdade|Comunista do Brasil|Social Democrático|"
    r"Socialista Brasileiro|Democrático Trabalhista|Podemos|Cidadania|Solidariedade|Progressistas)|"
    r"Movimento Democrático Brasileiro|União Brasil|Republicanos|Rede Sustentabilidade|"
    r"PODEMOS|CIDADANIA|SOLIDARIEDADE|PROGRESSISTAS|REPUBLICANOS|"
    r"PT|PSOL|PCdoB|PC do B|PSDB|MDB|PSD|PSB|PDT|PP|NOVO)\b"
    # "PL" alone usually means the bill under debate, so the party is masked only in unambiguous
    # contexts: "PL-SP", "PL/SP", "bancada/líder/partido do PL". Residual ambiguous uses stay.
    r"|\bPL(?=\s*[-/]\s*[A-Z]{2}\b)|(?<=\bbancada do )PL\b|(?<=\bBancada do )PL\b|(?<=\bLíder do )PL\b"
    r"|(?<=\blíder do )PL\b|(?<=\bpartido )PL\b|(?<=\bPartido )PL\b"
)
GROUP_LABEL_RE = re.compile(r"\b(?:petistas?|bolsonaristas?|lulistas?|petismo|bolsonarismo|lulismo)\b", re.I)

TEMPERATURE = 0.0
SEED = 20260926
MAX_SPEECH_CHARS = 60000
MAX_ARTICLE_CHARS = 9000
CHARS_PER_TOKEN = 3.2
EXPECTED_OUTPUT_TOKENS = {"propositions": 90, "stance": 130}
EXPERIMENT_VERSION = "party_alignment_v1"
WORKERS = 8

PROPOSITIONS_PROMPT = Path("prompts/hearing_propositions_v1.txt")
STANCE_PROMPT = Path("prompts/actor_stance_v1.txt")
RAW_DIR = Path("data/processed/llm_raw_outputs/party_alignment")

DETERMINABILITY = {"YES", "NO", "UNCERTAIN"}
STANCE = {"FAVOR", "AGAINST", "UNCERTAIN"}
GOVERNMENT_STANCE = {"SUPPORT", "CRITICIZE", "MIXED", "NEUTRAL", "NOT_ADDRESSED"}
PROPOSITION_FIELDS = ["hearing_id", "model", "proposition_id", "text", "malformed_output"]
STANCE_FIELDS = [
    "hearing_id", "actor_index", "condition", "model", "proposition_id", "stance_determinable", "stance",
    "government_stance", "previous_government_stance", "malformed_output", "malformed_fields",
    "input_truncated", "label_source",
]


@dataclass(frozen=True)
class Request:
    task: str
    condition: str
    model: str
    key: str
    prompt: str
    truncated: bool = False


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def raw_path(root: Path, request: Request) -> Path:
    name = f"{request.task}_{request.condition}_{request.model.replace('/', '_')}_{request.key}.json"
    return root / RAW_DIR / name


def mask_identity(text: str, names: list[str]) -> str:
    """Mask cues to the speaker's identity and party, keeping stance content.

    Replaced: participants' names (full name and the last two name tokens), party
    names/acronyms ("PL" followed by a bill number is kept: it is "projeto de lei"),
    and group labels (petista, bolsonarista...). Kept on purpose: presidents' names,
    "nosso governo", "governo passado" — they are the stance target itself, and the
    model needs them to tell the current government from the previous one.
    """
    variants = set()
    for name in names:
        tokens = name.split()
        variants.add(name)
        if len(tokens) >= 3:
            variants.add(" ".join(tokens[-2:]))
    for variant in sorted((v for v in variants if len(v) >= 6), key=len, reverse=True):
        text = re.sub(r"\b" + re.escape(variant) + r"\b", "[PESSOA]", text, flags=re.I)
    text = PARTY_MENTION_RE.sub("[PARTIDO]", text)
    return GROUP_LABEL_RE.sub("[GRUPO POLÍTICO]", text)


def truncate(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[:limit] + "\n[... trecho final omitido por limite de tamanho ...]", True


# --------------------------------------------------------------------------
# Prompt rendering
# --------------------------------------------------------------------------

def hearing_inputs(raw: list[dict]) -> dict[str, dict]:
    return {str(r["id"]): {"topic": r["metadados"].get("assunto", ""), "article": r.get("materia", "")} for r in raw}


def render_propositions(root: Path, hearing: dict, publication_date: str) -> tuple[str, bool]:
    article, cut = truncate(hearing["article"], MAX_ARTICLE_CHARS)
    template = (root / PROPOSITIONS_PROMPT).read_text(encoding="utf-8")
    return template.format(publication_date=publication_date, topic=hearing["topic"], article=article), cut


def format_propositions(propositions: list[dict]) -> str:
    return "\n".join(f"{p['id']}: {p['text']}" for p in propositions)


def render_stance(root: Path, row: dict, topic: str, propositions: list[dict], text: str,
                  condition: str) -> tuple[str, bool]:
    body, cut = truncate(text, MAX_SPEECH_CHARS)
    template = (root / STANCE_PROMPT).read_text(encoding="utf-8")
    prompt = template.format(
        publication_date=row["publication_date"], president=PRESIDENTS[row["government_period"]],
        topic=topic, propositions=format_propositions(propositions),
        speech_label=SPEECH_LABELS[condition], speech=body,
    )
    return prompt, cut


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------

def parse_propositions(raw_text: str) -> dict:
    parsed = _extract_json(raw_text)
    items = parsed.get("propositions") if isinstance(parsed, dict) else None
    if not isinstance(items, list) or not 1 <= len(items) <= 3:
        return {"propositions": [], "malformed_output": True}
    result = []
    for position, item in enumerate(items, 1):
        if not isinstance(item, dict) or item.get("id") != f"P{position}" or not str(item.get("text", "")).strip():
            return {"propositions": [], "malformed_output": True}
        result.append({"id": item["id"], "text": " ".join(str(item["text"]).split())})
    return {"propositions": result, "malformed_output": False}


def parse_stance(raw_text: str, proposition_ids: list[str]) -> dict:
    """Validate every field; invalid values become '' and are listed as malformed."""
    parsed = _extract_json(raw_text)
    malformed: list[str] = []
    if not isinstance(parsed, dict):
        return {"propositions": {pid: {"stance_determinable": "", "stance": ""} for pid in proposition_ids},
                "government_stance": "", "previous_government_stance": "",
                "malformed_output": True, "malformed_fields": ["json"]}
    by_id = parsed.get("propositions") if isinstance(parsed.get("propositions"), dict) else {}
    if set(by_id) != set(proposition_ids):
        malformed.append("proposition_ids")
    propositions = {}
    for pid in proposition_ids:
        item = by_id.get(pid) if isinstance(by_id.get(pid), dict) else {}
        determinable = item.get("stance_determinable", "")
        stance = item.get("stance", "") or ""
        if determinable not in DETERMINABILITY:
            malformed.append(f"{pid}.stance_determinable")
            determinable, stance = "", ""
        elif determinable == "YES" and stance not in STANCE:
            malformed.append(f"{pid}.stance")
            stance = ""
        elif determinable != "YES":
            stance = ""
        propositions[pid] = {"stance_determinable": determinable, "stance": stance}
    result = {"propositions": propositions}
    for field in ("government_stance", "previous_government_stance"):
        value = parsed.get(field, "")
        if value not in GOVERNMENT_STANCE:
            malformed.append(field)
            value = ""
        result[field] = value
    result["malformed_output"] = bool(malformed)
    result["malformed_fields"] = malformed
    return result


# --------------------------------------------------------------------------
# Request planning (no network)
# --------------------------------------------------------------------------

def proposition_requests(root: Path, raw: list[dict], rows: list[dict]) -> list[Request]:
    dates = {r["hearing_id"]: r["publication_date"] for r in rows}
    requests = []
    for hearing_id, hearing in sorted(hearing_inputs(raw).items(), key=lambda item: int(item[0])):
        prompt, cut = render_propositions(root, hearing, dates.get(hearing_id, ""))
        requests.append(Request("propositions", "article", PROPOSITION_MODEL, f"h{hearing_id}", prompt, cut))
    return requests


def load_propositions(root: Path, raw: list[dict], rows: list[dict]) -> dict[str, dict]:
    """Parsed stage-1 outputs available in cache, keyed by hearing_id."""
    result = {}
    for request in proposition_requests(root, raw, rows):
        path = raw_path(root, request)
        if path.exists():
            parsed = parse_propositions(completion_text(json.loads(path.read_text(encoding="utf-8"))))
            result[request.key[1:]] = parsed
    return result


def stance_requests(root: Path, raw: list[dict], rows: list[dict], speeches: dict,
                    propositions: dict[str, dict] | None, conditions: tuple[str, ...] = CONDITIONS) -> list[Request]:
    """With propositions=None, render placeholders so the plan can be costed before stage 1."""
    topics = {h: v["topic"] for h, v in hearing_inputs(raw).items()}
    names_by_hearing = collections.defaultdict(list)
    for row in rows:
        names_by_hearing[row["hearing_id"]].extend(n for n in (row["actor_name"], row["matched_speaker"]) if n)
    placeholder = [{"id": f"P{i}", "text": "x" * 110} for i in (1, 2, 3)]
    requests = []
    for row in rows:
        hearing_id = row["hearing_id"]
        if propositions is None:
            props = placeholder
        else:
            parsed = propositions.get(hearing_id)
            if not parsed or parsed["malformed_output"]:
                continue
            props = parsed["propositions"]
        speech = speeches[(hearing_id, str(row["actor_index"]))]
        texts = {"speech": speech, "lds_summary": row["lds_opinions"]}
        if MASKED in conditions:
            texts[MASKED] = mask_identity(speech, names_by_hearing[hearing_id]) if speech.strip() else ""
        for condition in conditions:
            if not texts[condition].strip():
                continue
            prompt, cut = render_stance(root, row, topics[hearing_id], props, texts[condition], condition)
            for model in MODELS:
                requests.append(Request("stance", condition, model, f"h{hearing_id}_a{row['actor_index']}",
                                        prompt, cut))
    return requests


def plan_summary(root: Path, requests: list[Request]) -> dict:
    groups = collections.defaultdict(lambda: {"calls": 0, "cached": 0, "input_tokens_est": 0,
                                              "output_tokens_est": 0, "cost_usd_est": 0.0, "truncated": 0})
    for request in requests:
        group = groups[f"{request.task}|{request.condition}|{request.model}"]
        cached = raw_path(root, request).exists()
        group["calls"] += 1
        group["cached"] += cached
        group["truncated"] += request.truncated
        if cached:
            continue
        tokens_in = round(len(request.prompt) / CHARS_PER_TOKEN)
        tokens_out = EXPECTED_OUTPUT_TOKENS[request.task]
        price_in, price_out = PRICES[request.model]
        group["input_tokens_est"] += tokens_in
        group["output_tokens_est"] += tokens_out
        group["cost_usd_est"] += tokens_in * price_in / 1e6 + tokens_out * price_out / 1e6
    total_cost = sum(g["cost_usd_est"] for g in groups.values())
    return {
        "groups": {k: {**v, "cost_usd_est": round(v["cost_usd_est"], 4)} for k, v in sorted(groups.items())},
        "calls_to_send": sum(g["calls"] - g["cached"] for g in groups.values()),
        "cost_usd_est_total": round(total_cost, 4),
        "estimate_basis": f"prompt chars / {CHARS_PER_TOKEN} tokens; fixed output tokens {EXPECTED_OUTPUT_TOKENS}",
    }


# --------------------------------------------------------------------------
# Execution (network) and tables
# --------------------------------------------------------------------------

def send(root: Path, request: Request) -> None:
    response = chat_completion(root, request.model, [{"role": "user", "content": request.prompt}],
                               temperature=TEMPERATURE, seed=SEED)
    path = raw_path(root, request)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(response, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)  # atomic: an interrupted run never leaves a truncated cache file


def execute(root: Path, requests: list[Request], workers: int = WORKERS) -> list[str]:
    """Send uncached requests concurrently; returns the errors of calls that still failed
    after llm_client's retries (those stay uncached and are retried on the next run)."""
    pending = [r for r in requests if not raw_path(root, r).exists()]
    errors = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(send, root, r): r for r in pending}
        for position, future in enumerate(concurrent.futures.as_completed(futures), 1):
            if future.exception() is not None:
                request = futures[future]
                errors.append(f"{request.task}|{request.condition}|{request.model}|{request.key}: {future.exception()}")
            if position % 100 == 0 or position == len(pending):
                print(f"{position}/{len(pending)} done, {len(errors)} failed", flush=True)
    return errors


def usage_summary(root: Path) -> dict:
    """Actual tokens and provider-reported cost from the cached raw responses."""
    groups = collections.defaultdict(lambda: {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0,
                                              "estimated_cost_usd": 0.0})
    for path in sorted((root / RAW_DIR).glob("*.json")):
        task, rest = path.name.split("_", 1)
        condition = next((c for c in (*ALL_CONDITIONS, "article") if rest.startswith(c + "_")), "")
        raw = json.loads(path.read_text(encoding="utf-8"))
        usage = raw.get("usage", {})
        group = groups[f"{task}|{condition}|{raw.get('model', '')}"]
        group["calls"] += 1
        group["prompt_tokens"] += usage.get("prompt_tokens", 0)
        group["completion_tokens"] += usage.get("completion_tokens", 0)
        group["estimated_cost_usd"] += usage.get("estimated_cost", 0) or 0
    for group in groups.values():
        group["estimated_cost_usd"] = round(group["estimated_cost_usd"], 4)
    return {"groups": dict(sorted(groups.items())),
            "total_cost_usd": round(sum(g["estimated_cost_usd"] for g in groups.values()), 4),
            "source": "usage.estimated_cost reported by DeepInfra in each raw response"}


def build_manifest(root: Path, stage: str, requests: list[Request],
                   conditions: tuple[str, ...] = CONDITIONS) -> dict:
    return {
        "experiment_version": EXPERIMENT_VERSION,
        "stage": stage,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "provider": "deepinfra",
        "models": list(MODELS),
        "proposition_model": PROPOSITION_MODEL,
        "temperature": TEMPERATURE,
        "seed": SEED,
        "prompt_propositions_sha256": sha256_text((root / PROPOSITIONS_PROMPT).read_text(encoding="utf-8")),
        "prompt_stance_sha256": sha256_text((root / STANCE_PROMPT).read_text(encoding="utf-8")),
        "max_speech_chars": MAX_SPEECH_CHARS,
        "max_article_chars": MAX_ARTICLE_CHARS,
        "conditions": list(conditions),
        "n_requests": len(requests),
        "request_prompts_sha256": sha256_text("\n".join(sha256_text(r.prompt) for r in requests)),
        "git_commit": _git_commit(root),
    }


def proposition_rows(propositions: dict[str, dict]) -> list[dict]:
    rows = []
    for hearing_id, parsed in sorted(propositions.items(), key=lambda item: int(item[0])):
        if parsed["malformed_output"]:
            rows.append({"hearing_id": hearing_id, "model": PROPOSITION_MODEL, "proposition_id": "",
                         "text": "", "malformed_output": True})
        for item in parsed["propositions"]:
            rows.append({"hearing_id": hearing_id, "model": PROPOSITION_MODEL, "proposition_id": item["id"],
                         "text": item["text"], "malformed_output": False})
    return rows


def stance_rows(root: Path, requests: list[Request], propositions: dict[str, dict]) -> list[dict]:
    """Long table: one row per actor x hearing x condition x model x proposition."""
    rows = []
    for request in requests:
        path = raw_path(root, request)
        if not path.exists():
            continue
        hearing_id, actor_index = request.key[1:].split("_a")
        ids = [p["id"] for p in propositions[hearing_id]["propositions"]]
        parsed = parse_stance(completion_text(json.loads(path.read_text(encoding="utf-8"))), ids)
        for pid in ids:
            rows.append({
                "hearing_id": hearing_id, "actor_index": actor_index, "condition": request.condition,
                "model": request.model, "proposition_id": pid, **parsed["propositions"][pid],
                "government_stance": parsed["government_stance"],
                "previous_government_stance": parsed["previous_government_stance"],
                "malformed_output": parsed["malformed_output"],
                "malformed_fields": "|".join(parsed["malformed_fields"]),
                "input_truncated": request.truncated, "label_source": "MODEL_PREDICTION",
            })
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stage", choices=("propositions", "stance"), required=True)
    parser.add_argument("--execute", action="store_true", help="send uncached requests (costs money)")
    parser.add_argument("--conditions", nargs="+", choices=ALL_CONDITIONS, default=list(CONDITIONS),
                        help="stance inputs to request (default: speech lds_summary)")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    raw = read_jsonl(root / "PublicHearingBR_LDS.jsonl")
    rows, speeches = build_actor_hearings(raw)
    out = root / "data" / "processed"

    if args.stage == "propositions":
        requests = proposition_requests(root, raw, rows)
    else:
        propositions = load_propositions(root, raw, rows)
        if not propositions:
            print("Stage 'propositions' not in cache: costing stance calls with placeholder propositions.")
        requests = stance_requests(root, raw, rows, speeches, propositions or None, tuple(args.conditions))

    print(json.dumps(plan_summary(root, requests), ensure_ascii=False, indent=2))
    if not args.execute:
        print("Dry run: nothing was sent. Re-run with --execute after approval.")
        return
    if args.stage == "stance" and not load_propositions(root, raw, rows):
        raise SystemExit("Run and parse stage 'propositions' first.")

    suffix = "" if args.stage == "propositions" or tuple(args.conditions) == CONDITIONS else "_" + "_".join(args.conditions)
    (out / f"party_manifest_{args.stage}{suffix}.json").write_text(
        json.dumps(build_manifest(root, args.stage, requests, tuple(args.conditions)), ensure_ascii=False,
                   indent=2) + "\n", encoding="utf-8")
    errors = execute(root, requests)
    if errors:
        print(f"{len(errors)} calls failed and stay uncached; re-run to retry:\n" + "\n".join(errors[:20]))
    propositions = load_propositions(root, raw, rows)
    write_csv(out / "party_propositions.csv", proposition_rows(propositions), PROPOSITION_FIELDS)
    if args.stage == "stance":
        # Rebuild the table from every cached condition, not only the ones just requested.
        cached = stance_requests(root, raw, rows, speeches, propositions, ALL_CONDITIONS)
        write_csv(out / "party_stances.csv", stance_rows(root, cached, propositions), STANCE_FIELDS)


if __name__ == "__main__":
    main()
