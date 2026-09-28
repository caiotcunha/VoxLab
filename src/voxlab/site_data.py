"""Build site/data.js for the static party-alignment dashboard (no network).

Packs the already computed outputs (actor table, labels, LLM stances,
propositions, deputy scores, RQ1-RQ4 results) into one compact object,
``window.VOXLAB``, so site/index.html opens from file:// or GitHub Pages
without a server. Every stance label stays a MODEL_PREDICTION.

    PYTHONPATH=src python -m voxlab.site_data
"""

from __future__ import annotations

import collections
import json
from pathlib import Path

from .actors import build_actor_hearings
from .audit import read_jsonl
from .hearing_stance import CONDITIONS, MODELS, usage_summary
from .party_alignment import read_rows

SPEECH_EXCERPT_CHARS = 1200
MAX_BYTES = 10 * 1024 * 1024
MODEL_KEYS = {MODELS[0]: "qwen", MODELS[1]: "llama"}
CONDITION_KEYS = {"speech": "fala", "lds_summary": "resumo"}


def proposition_code(determinable: str, stance: str) -> str:
    """F/A/U for a determinable stance, '-' not determinable, '?' uncertain, 'x' malformed."""
    if determinable == "YES":
        return {"FAVOR": "F", "AGAINST": "A", "UNCERTAIN": "U"}.get(stance, "x")
    return {"NO": "-", "UNCERTAIN": "?"}.get(determinable, "x")


def number(value: str) -> float | None:
    return float(value) if value not in ("", None) else None


def compact_stances(rows: list[dict]) -> dict[str, dict]:
    """{"h_a": {"qwen|fala": {"g", "pg", "p": {P1: code}, "m"}}}."""
    result: dict[str, dict] = collections.defaultdict(dict)
    for row in rows:
        if row["condition"] not in CONDITION_KEYS:
            continue  # robustness-only conditions (e.g. speech_masked) are not shown on the site
        run = f"{MODEL_KEYS[row['model']]}|{CONDITION_KEYS[row['condition']]}"
        cell = result[f"{row['hearing_id']}_{row['actor_index']}"].setdefault(
            run, {"g": row["government_stance"], "pg": row["previous_government_stance"], "p": {},
                  "m": row["malformed_output"] == "True"})
        cell["p"][row["proposition_id"]] = proposition_code(row["stance_determinable"], row["stance"])
    return dict(result)


def build(root: Path) -> dict:
    processed = root / "data" / "processed"
    raw = read_jsonl(root / "PublicHearingBR_LDS.jsonl")
    topics = {str(r["id"]): r["metadados"].get("assunto", "") for r in raw}
    actor_rows, speeches = build_actor_hearings(raw)
    labels = {(r["hearing_id"], r["actor_index"]): r for r in read_rows(processed / "party_actor_labels.csv")}
    propositions = collections.defaultdict(list)
    for row in read_rows(processed / "party_propositions.csv"):
        if row["proposition_id"]:
            propositions[row["hearing_id"]].append({"id": row["proposition_id"], "text": row["text"]})

    hearings: dict[str, dict] = {}
    for row in actor_rows:
        hearing_id, index = row["hearing_id"], str(row["actor_index"])
        hearing = hearings.setdefault(hearing_id, {
            "id": hearing_id, "date": row["publication_date"], "period": row["government_period"],
            "topic": topics[hearing_id], "propositions": propositions.get(hearing_id, []), "actors": []})
        label = labels.get((hearing_id, index), {})
        speech = speeches[(hearing_id, index)]
        hearing["actors"].append({
            "i": index, "name": row["actor_name"], "id": row["actor_id"], "cargo": row["cargo"],
            "type": row["actor_type"], "party": label.get("party", ""), "bloc": label.get("bloc", ""),
            "dep": label.get("deputado_id", ""), "match": row["speech_match_method"],
            "speech": speech[:SPEECH_EXCERPT_CHARS], "speech_chars": len(speech), "summary": row["lds_opinions"],
        })

    deputies: dict[str, dict] = {}
    for row in read_rows(processed / "party_deputy_scores.csv"):
        deputy = deputies.setdefault(row["deputado_id"], {"id": row["deputado_id"], "name": row["name"],
                                                          "periods": {}, "scores": {}})
        deputy["periods"].setdefault(row["period"], {"party": row["party"],
                                                     "governism": number(row["rollcall_governism"]),
                                                     "rollcall_n": number(row["rollcall_n"])})
        run = f"{MODEL_KEYS[row['model']]}|{CONDITION_KEYS[row['condition']]}"
        deputy["scores"].setdefault(run, {})[row["period"]] = {"score": float(row["hearing_score"]),
                                                               "n": int(row["n_hearings"])}

    results = json.loads((processed / "party_alignment_results.json").read_text(encoding="utf-8"))
    runs = {f"{MODEL_KEYS[m]}|{CONDITION_KEYS[c]}": results["runs"][f"{m}|{c}"] for m in MODELS for c in CONDITIONS}
    manifests = {stage: json.loads((processed / f"party_manifest_{stage}.json").read_text(encoding="utf-8"))
                 for stage in ("propositions", "stance")}
    usage = usage_summary(root)
    return {
        "meta": {
            "label_source": "MODEL_PREDICTION",
            "models": {MODEL_KEYS[m]: m for m in MODELS},
            "conditions": {CONDITION_KEYS[c]: c for c in CONDITIONS},
            "calls": sum(g["calls"] for g in usage["groups"].values()),
            "cost_usd": usage["total_cost_usd"],
            "prompt_sha256": {"propositions": manifests["stance"]["prompt_propositions_sha256"],
                              "stance": manifests["stance"]["prompt_stance_sha256"]},
            "speech_excerpt_chars": SPEECH_EXCERPT_CHARS,
        },
        "hearings": sorted(hearings.values(), key=lambda h: (h["date"], int(h["id"]))),
        "stances": compact_stances(read_rows(processed / "party_stances.csv")),
        "deputies": deputies,
        "results": {"party_governism": results["party_governism"], "bloc_thresholds": results["bloc_thresholds"],
                    "runs": runs, "rq4": results["rq4"]},
    }


def write(root: Path, data: dict) -> int:
    payload = "window.VOXLAB = " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n"
    size = len(payload.encode("utf-8"))
    if size > MAX_BYTES:
        raise SystemExit(f"site/data.js would be {size} bytes (> {MAX_BYTES}); reduce SPEECH_EXCERPT_CHARS")
    path = root / "site" / "data.js"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")
    return size


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    size = write(root, build(root))
    print(f"site/data.js: {size / 1e6:.2f} MB")


if __name__ == "__main__":
    main()
