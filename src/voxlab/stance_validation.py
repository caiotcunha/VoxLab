"""Human validation of the LLM stance labels (plan item 1). No network.

build:   draws a stratified sample of actor x hearing items, writes two blind
         packets (independent random orders), a reference file linking item ids
         to hearing/actor, and one self-contained HTML annotation page per
         annotator (opens via file://, saves progress in the browser, exports CSV).
analyze: reads the two filled CSVs, computes human-human agreement and
         human-model agreement (per model, on items where the humans agree),
         overall and by camp.

Annotators see exactly what the model saw in the literal-speech condition:
publication date, president in office, topic, propositions and the speech —
never name, party, UF or role. Items are drawn per stratum (camp x period),
over-sampling model disagreement; inclusion weights are stored so estimates
can be reweighted to the corpus.

    PYTHONPATH=src python -m voxlab.stance_validation build [--n 100] [--max-chars 12000]
    PYTHONPATH=src python -m voxlab.stance_validation analyze
"""

from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import json
import random
from pathlib import Path

from .actors import build_actor_hearings
from .agreement import categorical_agreement
from .audit import read_jsonl, write_csv
from .hearing_stance import MODELS, PRESIDENTS, SPEECH_LABELS
from .party_alignment import government_stances, proposition_labels, read_rows
from .party_thesis import camp_of

OUT = Path("data/annotations/stance_validation")
TEMPLATE = Path(__file__).with_name("stance_validation_template.html")
SEED = 20260928
# Share of the sample per camp; the centrão gets the most because the thesis rests on it.
ALLOCATION = {"LEFT": 0.18, "RIGHT": 0.18, "CENTRAO": 0.22, "OTHER_PARTY": 0.08,
              "FEDERAL_EXECUTIVE": 0.12, "CIVIL_SOCIETY_OR_OTHER": 0.22}
MIN_BOLSONARO_SHARE = 0.25
GOV_CODES = ("SUPPORT", "CRITICIZE", "MIXED", "NEUTRAL", "NOT_ADDRESSED")
DET_CODES = ("YES", "NO", "UNCERTAIN")
STANCE_CODES = ("FAVOR", "AGAINST", "UNCERTAIN")
RESPONSE_FIELDS = (["government_stance", "previous_government_stance"]
                   + [f"P{i}_{f}" for i in (1, 2, 3) for f in ("determinable", "stance")]
                   + ["confidence", "notes"])
PACKET_FIELDS = ["item_id", "publication_date", "president", "topic", "P1", "P2", "P3", "speech"] + RESPONSE_FIELDS
REFERENCE_FIELDS = ["item_id", "hearing_id", "actor_index", "camp", "period", "stratum_size", "stratum_sample",
                    "inclusion_weight", "models_disagree_on_government", "speech_chars"]


def item_id(hearing_id: str, actor_index: str) -> str:
    return hashlib.sha256(f"stance-validation|{hearing_id}|{actor_index}".encode()).hexdigest()[:10]


def draw_sample(candidates: list[dict], n: int, seed: int = SEED) -> list[dict]:
    """Stratified by camp x period; within a stratum, model-disagreement items first (half),
    then random. Each chosen row gets stratum sizes for inclusion weights."""
    rng = random.Random(seed)
    strata = collections.defaultdict(list)
    for row in candidates:
        strata[(row["camp"], row["period"])].append(row)
    chosen = []
    for camp, share in ALLOCATION.items():
        quota = round(n * share)
        bolsonaro = strata.get((camp, "BOLSONARO"), [])
        lula = strata.get((camp, "LULA"), [])
        take_b = min(len(bolsonaro), max(round(quota * MIN_BOLSONARO_SHARE), quota - len(lula)))
        for pool, k in ((bolsonaro, take_b), (lula, min(len(lula), quota - take_b))):
            disagree = [r for r in pool if r["disagree"]]
            agree = [r for r in pool if not r["disagree"]]
            rng.shuffle(disagree)
            rng.shuffle(agree)
            first = disagree[: k // 2]
            rest = [r for r in agree + disagree[k // 2:] if r not in first]
            rng.shuffle(rest)
            picked = first + rest[: k - len(first)]
            for row in picked:
                chosen.append({**row, "stratum_size": len(pool), "stratum_sample": len(picked),
                               "inclusion_weight": round(len(pool) / len(picked), 4)})
    return chosen


def build(root: Path, n: int, max_chars: int) -> dict:
    processed = root / "data" / "processed"
    raw = read_jsonl(root / "PublicHearingBR_LDS.jsonl")
    topics = {str(r["id"]): r["metadados"].get("assunto", "") for r in raw}
    actor_rows, speeches = build_actor_hearings(raw)
    labels = {(r["hearing_id"], r["actor_index"]): r for r in read_rows(processed / "party_actor_labels.csv")}
    propositions = collections.defaultdict(dict)
    for row in read_rows(processed / "party_propositions.csv"):
        if row["proposition_id"]:
            propositions[row["hearing_id"]][row["proposition_id"]] = row["text"]
    stance_rows = read_rows(processed / "party_stances.csv")
    first, second = (government_stances(stance_rows, m, "speech") for m in MODELS)

    candidates, eligible = [], 0
    for row in actor_rows:
        key = (row["hearing_id"], str(row["actor_index"]))
        speech = speeches[key]
        camp = camp_of(labels.get(key, {}))
        if not speech.strip() or camp not in ALLOCATION or key not in first:
            continue
        eligible += 1
        if len(speech) > max_chars:
            continue
        candidates.append({"hearing_id": key[0], "actor_index": key[1], "camp": camp,
                           "period": row["government_period"], "date": row["publication_date"],
                           "speech": speech, "disagree": first.get(key) != second.get(key)})
    sample = draw_sample(candidates, n)

    out = root / OUT
    out.mkdir(parents=True, exist_ok=True)
    reference, packet = [], []
    for row in sample:
        iid = item_id(row["hearing_id"], row["actor_index"])
        props = propositions[row["hearing_id"]]
        packet.append({"item_id": iid, "publication_date": row["date"], "president": PRESIDENTS[row["period"]],
                       "topic": topics[row["hearing_id"]], **{p: props.get(p, "") for p in ("P1", "P2", "P3")},
                       "speech": row["speech"], **{f: "" for f in RESPONSE_FIELDS}})
        reference.append({"item_id": iid, "hearing_id": row["hearing_id"], "actor_index": row["actor_index"],
                          "camp": row["camp"], "period": row["period"], "stratum_size": row["stratum_size"],
                          "stratum_sample": row["stratum_sample"], "inclusion_weight": row["inclusion_weight"],
                          "models_disagree_on_government": row["disagree"], "speech_chars": len(row["speech"])})
    for annotator, seed in ((1, SEED + 1), (2, SEED + 2)):
        order = packet[:]
        random.Random(seed).shuffle(order)
        write_csv(out / f"annotator_{annotator}.csv", order, PACKET_FIELDS)
        page = TEMPLATE.read_text(encoding="utf-8")
        page = page.replace("__ITEMS__", json.dumps(order, ensure_ascii=False)).replace("__ANNOTATOR__", str(annotator))
        page = page.replace("__SPEECH_LABEL__", SPEECH_LABELS["speech"])
        (out / f"annotator_{annotator}.html").write_text(page, encoding="utf-8")
    write_csv(out / "reference.csv", sorted(reference, key=lambda r: r["item_id"]), REFERENCE_FIELDS)
    summary = {
        "n_items": len(sample), "max_chars": max_chars,
        "candidates": len(candidates),
        "excluded_long_speech_share": round(1 - len(candidates) / eligible, 4),
        "by_camp_period": dict(collections.Counter(f"{r['camp']}|{r['period']}" for r in sample)),
        "model_disagreement_items": sum(r["disagree"] for r in sample),
        "total_speech_chars": sum(len(r["speech"]) for r in sample),
        "estimated_hours_per_annotator": round(sum(len(r["speech"]) for r in sample) / 1500 / 60
                                               + len(sample) * 1.5 / 60, 1),
    }
    (out / "sample_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


# --------------------------------------------------------------------------
# Analysis
# --------------------------------------------------------------------------

def read_filled(path: Path) -> dict[str, dict]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = {r["item_id"]: r for r in csv.DictReader(handle)}
    missing = [i for i, r in rows.items() if not r["government_stance"]]
    if missing:
        raise SystemExit(f"{path.name}: {len(missing)} items without government_stance")
    return rows


def proposition_label(row: dict, pid: str) -> str:
    determinable = row.get(f"{pid}_determinable", "")
    return row.get(f"{pid}_stance", "") if determinable == "YES" else f"DET_{determinable}" if determinable else ""


def analyze(root: Path) -> dict:
    out = root / OUT
    first, second = read_filled(out / "annotator_1_filled.csv"), read_filled(out / "annotator_2_filled.csv")
    reference = {r["item_id"]: r for r in read_rows(out / "reference.csv")}
    stance_rows = read_rows(root / "data" / "processed" / "party_stances.csv")
    ids = sorted(reference)
    result = {"n_items": len(ids), "human_human": {}, "human_model": {}}
    for field in ("government_stance", "previous_government_stance"):
        result["human_human"][field] = categorical_agreement([first[i][field] for i in ids],
                                                             [second[i][field] for i in ids])
    pairs = [(i, p) for i in ids for p in ("P1", "P2", "P3")
             if first[i][p] and proposition_label(first[i], p) and proposition_label(second[i], p)]
    result["human_human"]["proposition_stance"] = categorical_agreement(
        [proposition_label(first[i], p) for i, p in pairs], [proposition_label(second[i], p) for i, p in pairs])

    for model in MODELS:
        predicted = government_stances(stance_rows, model, "speech")
        per_model = {}
        agreed = [i for i in ids if first[i]["government_stance"] == second[i]["government_stance"]]
        keys = {i: (reference[i]["hearing_id"], reference[i]["actor_index"]) for i in ids}
        per_model["government_stance_vs_human_consensus"] = categorical_agreement(
            [first[i]["government_stance"] for i in agreed], [predicted.get(keys[i], "") for i in agreed])
        model_props = proposition_labels(stance_rows, model, "speech")
        agreed_props = [(i, p) for i, p in pairs if proposition_label(first[i], p) == proposition_label(second[i], p)]
        per_model["proposition_stance_vs_human_consensus"] = categorical_agreement(
            [proposition_label(first[i], p) for i, p in agreed_props],
            [model_props.get((*keys[i], p), "") for i, p in agreed_props])
        by_camp = collections.defaultdict(lambda: [0, 0])
        for i in agreed:
            cell = by_camp[reference[i]["camp"]]
            cell[0] += 1
            cell[1] += predicted.get(keys[i]) == first[i]["government_stance"]
        per_model["accuracy_by_camp"] = {c: {"n": n, "accuracy": round(hit / n, 4)} for c, (n, hit) in by_camp.items()}
        for annotator, rows in ((1, first), (2, second)):
            per_model[f"government_stance_vs_annotator_{annotator}"] = categorical_agreement(
                [rows[i]["government_stance"] for i in ids], [predicted.get(keys[i], "") for i in ids])
        result["human_model"][model] = per_model
    (out / "validation_results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                                                 encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build")
    b.add_argument("--n", type=int, default=100)
    b.add_argument("--max-chars", type=int, default=12000)
    sub.add_parser("analyze")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    result = build(root, args.n, args.max_chars) if args.command == "build" else analyze(root)
    print(json.dumps(result, ensure_ascii=False, indent=2)[:3000])


if __name__ == "__main__":
    main()
