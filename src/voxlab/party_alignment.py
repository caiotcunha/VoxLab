"""Party alignment, government stance and model robustness (RQ1-RQ4).

Inputs: data/processed/party_actor_hearings.csv (voxlab.actors),
data/processed/party_stances.csv (voxlab.hearing_stance) and, when present,
the Câmara roll-call snapshot (voxlab.camara_api). No network, no LLM.

All stance values are MODEL_PREDICTION. Results are reported separately per
model and input condition; nothing is pooled across models.

- RQ1: within one hearing and proposition, do deputies of the same party /
  bloc agree more often than deputies of different ones? Permutation test
  shuffles group labels among the deputies of each hearing.
- RQ2: convergent validity. A deputy's stance toward the government in
  hearings vs. their roll-call governism in the same period; party-pair
  agreement in hearings vs. party-pair co-voting agreement.
- RQ3: stance toward the government in office by group and period
  (Bolsonaro vs. Lula), with hearing-level bootstrap intervals.
- RQ4: inter-model and inter-condition agreement; known-group check
  (federal executive officials should mostly support the government).

Run from the repository root:
    PYTHONPATH=src python3 -m voxlab.party_alignment
"""

from __future__ import annotations

import collections
import csv
import itertools
import json
import random
from pathlib import Path

from scipy import stats

from . import camara_api
from .agreement import categorical_agreement
from .audit import write_csv
from .hearing_stance import CONDITIONS, MODELS

STANCE_VALUE = {"FAVOR": 1, "AGAINST": -1}
GOVERNMENT_SCORE = {"SUPPORT": 1.0, "CRITICIZE": -1.0, "MIXED": 0.0, "NEUTRAL": 0.0}
# Bloc from a party's mean roll-call governism in the period. Thresholds are a
# declared choice, reported with a sensitivity check, not a literature constant.
BLOC_THRESHOLDS = (0.40, 0.70)
PERIODS = ("BOLSONARO", "LULA")
PERMUTATIONS = 5000
BOOTSTRAPS = 2000
SEED = 20260926
MIN_PARTY_PAIRS = 3


def read_rows(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def actor_key(row: dict) -> tuple[str, str]:
    return row["hearing_id"], str(row["actor_index"])


# --------------------------------------------------------------------------
# Labels: dated party, governism and bloc
# --------------------------------------------------------------------------

def bloc_of(value: float | None, thresholds: tuple[float, float] = BLOC_THRESHOLDS) -> str:
    if value is None:
        return ""
    low, high = thresholds
    return "OPPOSITION" if value < low else "GOVERNMENT" if value >= high else "PIVOT"


def party_governism(deputy_governism: dict[tuple[str, str], dict],
                    deputy_party: dict[tuple[str, str], str]) -> dict[tuple[str, str], float]:
    """{(party, period): mean governism of its deputies}, weighting deputies equally."""
    values = collections.defaultdict(list)
    for (deputy_id, period), cell in deputy_governism.items():
        party = deputy_party.get((deputy_id, period))
        if party:
            values[(party, period)].append(cell["governism"])
    return {key: round(sum(v) / len(v), 4) for key, v in values.items()}


def label_actors(actor_rows: list[dict], camara: dict | None,
                 thresholds: tuple[float, float] = BLOC_THRESHOLDS) -> dict[tuple[str, str], dict]:
    """Per actor-hearing labels. Without Câmara data, party comes from cargo and
    governism/bloc stay empty."""
    labels = {}
    for row in actor_rows:
        label = {"actor_id": row["actor_id"], "actor_type": row["actor_type"],
                 "period": row["government_period"], "party": row["party_cargo"],
                 "party_source": "CARGO" if row["party_cargo"] else "", "deputado_id": "",
                 "governism": None, "bloc": ""}
        if camara and row["actor_type"] == "DEPUTY" and row["actor_id"] in camara["matches"]:
            deputy_id, _ = camara["matches"][row["actor_id"]]
            timeline = camara["directory"][deputy_id]["party_timeline"]
            label["deputado_id"] = deputy_id
            label["party"] = camara_api.party_on(timeline, row["publication_date"]) or label["party"]
            label["party_source"] = "ROLLCALL_DATED"
            cell = camara["governism"].get((deputy_id, row["government_period"]))
            label["governism"] = cell["governism"] if cell else None
        if camara and label["party"]:
            label["bloc"] = bloc_of(camara["party_governism"].get((label["party"], label["period"])), thresholds)
        labels[actor_key(row)] = label
    return labels


# --------------------------------------------------------------------------
# RQ1: within-hearing agreement by group
# --------------------------------------------------------------------------

def directional_stances(stance_rows: list[dict], model: str, condition: str) -> dict[tuple, dict]:
    """{(hearing_id, proposition_id): {actor_key: +1|-1}} for determinable, directional stances."""
    result = collections.defaultdict(dict)
    for row in stance_rows:
        if row["model"] != model or row["condition"] != condition or row["stance_determinable"] != "YES":
            continue
        value = STANCE_VALUE.get(row["stance"])
        if value is not None:
            result[(row["hearing_id"], row["proposition_id"])][actor_key(row)] = value
    return result


def within_hearing_pairs(stances: dict[tuple, dict], labels: dict, group: str) -> list[dict]:
    """Deputy pairs that both took a direction on the same proposition, with group labels."""
    pairs = []
    for (hearing_id, proposition_id), by_actor in stances.items():
        deputies = sorted(k for k in by_actor if labels.get(k, {}).get("actor_type") == "DEPUTY"
                          and labels[k].get(group))
        for a, b in itertools.combinations(deputies, 2):
            if labels[a]["actor_id"] == labels[b]["actor_id"]:
                continue
            pairs.append({"hearing_id": hearing_id, "proposition_id": proposition_id, "actor_a": a, "actor_b": b,
                          "agree": by_actor[a] == by_actor[b]})
    return pairs


def agreement_gap(pairs: list[dict], group_of: dict) -> dict:
    same = [p["agree"] for p in pairs if group_of[p["actor_a"]] == group_of[p["actor_b"]]]
    diff = [p["agree"] for p in pairs if group_of[p["actor_a"]] != group_of[p["actor_b"]]]
    rate_same = sum(same) / len(same) if same else None
    rate_diff = sum(diff) / len(diff) if diff else None
    gap = rate_same - rate_diff if same and diff else None
    return {"n_pairs_same_group": len(same), "n_pairs_diff_group": len(diff),
            "agreement_same_group": None if rate_same is None else round(rate_same, 4),
            "agreement_diff_group": None if rate_diff is None else round(rate_diff, 4),
            "gap": None if gap is None else round(gap, 4)}


def permutation_test(pairs: list[dict], labels: dict, group: str, n: int = PERMUTATIONS, seed: int = SEED) -> dict:
    """Shuffle group labels among the deputies of each hearing; one-sided p for gap >= observed."""
    observed_group = {k: labels[k][group] for p in pairs for k in (p["actor_a"], p["actor_b"])}
    observed = agreement_gap(pairs, observed_group)
    if observed["gap"] is None:
        return {**observed, "permutation_p": None, "n_permutations": 0}
    by_hearing = collections.defaultdict(list)
    for key in observed_group:
        by_hearing[key[0]].append(key)
    rng = random.Random(seed)
    at_least = 0
    for _ in range(n):
        shuffled = {}
        for keys in by_hearing.values():
            values = [observed_group[k] for k in keys]
            rng.shuffle(values)
            shuffled.update(zip(keys, values))
        gap = agreement_gap(pairs, shuffled)["gap"]
        at_least += gap is not None and gap >= observed["gap"] - 1e-12
    return {**observed, "permutation_p": round((at_least + 1) / (n + 1), 4), "n_permutations": n}


# --------------------------------------------------------------------------
# RQ2 / RQ3: government stance
# --------------------------------------------------------------------------

def government_stances(stance_rows: list[dict], model: str, condition: str,
                       field: str = "government_stance") -> dict[tuple[str, str], str]:
    """{actor_key: label}; stance rows repeat per proposition, so take the first valid one."""
    result = {}
    for row in stance_rows:
        if row["model"] == model and row["condition"] == condition and row[field]:
            result.setdefault(actor_key(row), row[field])
    return result


def deputy_government_scores(government: dict, labels: dict) -> dict[tuple[str, str], dict]:
    """{(deputado_id, period): {"n", "score"}} averaging addressed hearings (NOT_ADDRESSED excluded)."""
    values = collections.defaultdict(list)
    for key, label in government.items():
        info = labels.get(key, {})
        if info.get("deputado_id") and label in GOVERNMENT_SCORE:
            values[(info["deputado_id"], info["period"])].append(GOVERNMENT_SCORE[label])
    return {k: {"n": len(v), "score": round(sum(v) / len(v), 4)} for k, v in values.items()}


def spearman(xs: list[float], ys: list[float]) -> dict:
    if len(xs) < 5 or len(set(xs)) < 2 or len(set(ys)) < 2:
        return {"n": len(xs), "rho": None, "p": None}
    rho, p = stats.spearmanr(xs, ys)
    return {"n": len(xs), "rho": round(float(rho), 4), "p": round(float(p), 4)}


def speech_vote_validity(scores: dict, deputy_governism: dict) -> dict:
    result = {}
    for period in PERIODS:
        keys = [k for k in scores if k[1] == period and k in deputy_governism]
        result[period] = spearman([scores[k]["score"] for k in keys], [deputy_governism[k]["governism"] for k in keys])
    return result


def party_pair_hearing_agreement(pairs: list[dict], labels: dict) -> dict[tuple[str, str, str], dict]:
    counts = collections.defaultdict(lambda: [0, 0])
    for p in pairs:
        a, b = sorted((labels[p["actor_a"]]["party"], labels[p["actor_b"]]["party"]))
        if a == b:
            continue
        cell = counts[(labels[p["actor_a"]]["period"], a, b)]
        cell[0] += 1
        cell[1] += p["agree"]
    return {k: {"n": n, "agreement": round(hit / n, 4)} for k, (n, hit) in counts.items()}


def party_pair_validity(hearing: dict, covoting: dict) -> dict:
    keys = [k for k, v in hearing.items() if v["n"] >= MIN_PARTY_PAIRS and k in covoting]
    return {"min_pairs_per_party_pair": MIN_PARTY_PAIRS,
            **spearman([hearing[k]["agreement"] for k in keys], [covoting[k]["agreement"] for k in keys]),
            "note": "party pairs share parties, so observations are not independent; descriptive only"}


def group_of(label: dict) -> str:
    if label["actor_type"] == "DEPUTY":
        return f"PARTY:{label['party']}" if label["party"] else ""
    return label["actor_type"]


def net_support(values: list[str]) -> dict:
    addressed = [GOVERNMENT_SCORE[v] for v in values if v in GOVERNMENT_SCORE]
    counts = collections.Counter(values)
    return {"n": len(values), "n_addressed": len(addressed),
            "net_support": round(sum(addressed) / len(addressed), 4) if addressed else None,
            "counts": dict(sorted(counts.items()))}


def government_by_group(government: dict, labels: dict, grouping=group_of,
                        n_boot: int = BOOTSTRAPS, seed: int = SEED) -> dict:
    """Net support (SUPPORT=+1, CRITICIZE=-1, MIXED/NEUTRAL=0) per group x period, with a
    percentile bootstrap resampling hearings within each period."""
    cells = collections.defaultdict(lambda: collections.defaultdict(list))
    for key, value in government.items():
        label = labels.get(key)
        if not label or not grouping(label):
            continue
        cells[(grouping(label), label["period"])][key[0]].append(value)
    rng = random.Random(seed)
    result = {}
    for (group, period), by_hearing in sorted(cells.items()):
        flat = [v for values in by_hearing.values() for v in values]
        summary = net_support(flat)
        hearings = list(by_hearing)
        draws = []
        for _ in range(n_boot):
            sample = [v for h in rng.choices(hearings, k=len(hearings)) for v in by_hearing[h]]
            value = net_support(sample)["net_support"]
            if value is not None:
                draws.append(value)
        draws.sort()
        ci = [round(draws[int(0.025 * len(draws))], 4), round(draws[int(0.975 * len(draws)) - 1], 4)] if draws else None
        result[f"{group}|{period}"] = {**summary, "n_hearings": len(hearings), "ci95": ci}
    return result


def period_shift(by_group: dict) -> dict:
    groups = {k.rsplit("|", 1)[0] for k in by_group}
    shifts = {}
    for group in sorted(groups):
        before, after = by_group.get(f"{group}|BOLSONARO"), by_group.get(f"{group}|LULA")
        if before and after and before["net_support"] is not None and after["net_support"] is not None:
            shifts[group] = {"bolsonaro": before["net_support"], "lula": after["net_support"],
                             "shift": round(after["net_support"] - before["net_support"], 4),
                             "n_bolsonaro": before["n_addressed"], "n_lula": after["n_addressed"]}
    return shifts


def recurrent_actor_panel(government: dict, labels: dict) -> list[dict]:
    by_actor = collections.defaultdict(lambda: collections.defaultdict(list))
    for key, value in government.items():
        label = labels.get(key)
        if label:
            by_actor[label["actor_id"]][label["period"]].append(value)
    rows = []
    for actor_id, periods in sorted(by_actor.items()):
        if set(PERIODS) <= set(periods):
            rows.append({"actor_id": actor_id,
                         **{f"{p.lower()}_{k}": v for p in PERIODS for k, v in net_support(periods[p]).items()
                            if k in ("n", "net_support")}})
    return rows


# --------------------------------------------------------------------------
# RQ4: robustness
# --------------------------------------------------------------------------

def paired_agreement(first: dict, second: dict) -> dict:
    shared = sorted(set(first) & set(second))
    return categorical_agreement([first[k] for k in shared], [second[k] for k in shared])


def proposition_labels(stance_rows: list[dict], model: str, condition: str) -> dict[tuple, str]:
    """Collapsed per-proposition label: FAVOR/AGAINST/UNCERTAIN when determinable, else NO/UNCERTAIN_DET."""
    result = {}
    for row in stance_rows:
        if row["model"] != model or row["condition"] != condition or not row["stance_determinable"]:
            continue
        label = row["stance"] if row["stance_determinable"] == "YES" else f"DET_{row['stance_determinable']}"
        result[(row["hearing_id"], str(row["actor_index"]), row["proposition_id"])] = label
    return result


def robustness(stance_rows: list[dict], labels: dict) -> dict:
    result = {"label": "INTER_MODEL_AND_INTER_CONDITION_AGREEMENT (not gold)"}
    for condition in CONDITIONS:
        result[f"models|{condition}"] = {
            "government_stance": paired_agreement(*(government_stances(stance_rows, m, condition) for m in MODELS)),
            "proposition_stance": paired_agreement(*(proposition_labels(stance_rows, m, condition) for m in MODELS)),
        }
    for model in MODELS:
        result[f"conditions|{model}"] = {
            "government_stance": paired_agreement(*(government_stances(stance_rows, model, c) for c in CONDITIONS)),
            "proposition_stance": paired_agreement(*(proposition_labels(stance_rows, model, c) for c in CONDITIONS)),
        }
        for condition in CONDITIONS:
            government = government_stances(stance_rows, model, condition)
            executive = collections.defaultdict(list)
            for key, value in government.items():
                if labels.get(key, {}).get("actor_type") == "FEDERAL_EXECUTIVE":
                    executive[labels[key]["period"]].append(value)
            result[f"known_group_federal_executive|{model}|{condition}"] = {
                p: net_support(executive[p]) for p in PERIODS if executive[p]}
    malformed = collections.Counter((r["model"], r["condition"]) for r in stance_rows if r["malformed_output"] == "True")
    result["malformed_rows"] = {f"{m}|{c}": n for (m, c), n in sorted(malformed.items())}
    return result


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------

def load_camara(root: Path, actor_rows: list[dict]) -> dict | None:
    if not all((root / camara_api.RAW_DIR / name).exists() for name in camara_api.file_urls()
               if name != "deputados.csv"):
        return None
    votes, orientations, dates = camara_api.load(root)
    orientation = camara_api.government_orientation(orientations)
    directory = camara_api.deputy_directory(votes, dates)
    deputy_governism = camara_api.governism(votes, orientation, dates)
    deputy_party = {}
    for deputy_id, entry in directory.items():
        for period in PERIODS:
            dated = [p for d, p in entry["party_timeline"] if camara_api.government_period(d) == period]
            if dated:
                deputy_party[(deputy_id, period)] = collections.Counter(dated).most_common(1)[0][0]
    return {"directory": directory, "governism": deputy_governism,
            "matches": camara_api.match_deputies(actor_rows, directory),
            "party_governism": party_governism(deputy_governism, deputy_party),
            "covoting": camara_api.party_covoting(votes, dates),
            "n_government_oriented_rollcalls": len(orientation)}


def analyze(stance_rows: list[dict], actor_rows: list[dict], camara: dict | None) -> dict:
    labels = label_actors(actor_rows, camara)
    deputies = [r for r in actor_rows if r["actor_type"] == "DEPUTY"]
    results = {
        "label_source": "MODEL_PREDICTION",
        "camara_data": camara is not None,
        "deputy_rows": len(deputies),
        "deputy_rows_matched_to_camara": sum(1 for r in deputies if labels[actor_key(r)]["deputado_id"]),
        "bloc_thresholds": BLOC_THRESHOLDS,
        "party_governism": ({f"{p}|{period}": v for (p, period), v in sorted(camara["party_governism"].items())}
                            if camara else None),
        "runs": {},
    }
    for model, condition in itertools.product(MODELS, CONDITIONS):
        stances = directional_stances(stance_rows, model, condition)
        government = government_stances(stance_rows, model, condition)
        previous = government_stances(stance_rows, model, condition, "previous_government_stance")
        run = {"rq1": {}}
        for group in ("party", "bloc"):
            if group == "bloc" and not camara:
                continue
            pairs = within_hearing_pairs(stances, labels, group)
            run["rq1"][group] = permutation_test(pairs, labels, group)
        if camara:
            for low, high in ((0.35, 0.65), (0.45, 0.75)):
                sensitivity = label_actors(actor_rows, camara, (low, high))
                pairs = within_hearing_pairs(stances, sensitivity, "bloc")
                run["rq1"][f"bloc_sensitivity_{low}_{high}"] = permutation_test(pairs, sensitivity, "bloc", n=1000)
            party_pairs = within_hearing_pairs(stances, labels, "party")
            run["rq2"] = {
                "speech_vs_vote_governism": speech_vote_validity(deputy_government_scores(government, labels),
                                                                 camara["governism"]),
                "party_pair_agreement_vs_covoting": party_pair_validity(
                    party_pair_hearing_agreement(party_pairs, labels), camara["covoting"]),
            }
        by_group = government_by_group(government, labels)
        run["rq3"] = {"government_stance_by_group": by_group, "shift_bolsonaro_to_lula": period_shift(by_group)}
        if camara:
            # Pre-2023 deputy rows are few (47; PL has 2), so the role-switch contrast
            # groups parties by the bloc they occupy under Lula, in both periods.
            def lula_bloc(label: dict) -> str:
                if label["actor_type"] != "DEPUTY" or not label["party"]:
                    return ""
                return bloc_of(camara["party_governism"].get((label["party"], "LULA")))
            by_bloc = government_by_group(government, labels, lula_bloc)
            run["rq3"]["government_stance_by_lula_bloc"] = by_bloc
            run["rq3"]["shift_by_lula_bloc"] = period_shift(by_bloc)
        run["rq3"].update({
            "previous_government_stance_by_group": government_by_group(previous, labels, n_boot=0),
            "recurrent_actors_both_periods": recurrent_actor_panel(government, labels)})
        results["runs"][f"{model}|{condition}"] = run
    results["rq4"] = robustness(stance_rows, labels)
    return results


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    processed = root / "data" / "processed"
    stance_path = processed / "party_stances.csv"
    if not stance_path.exists():
        raise SystemExit("party_stances.csv not found: run voxlab.hearing_stance --stage stance --execute first.")
    actor_rows = read_rows(processed / "party_actor_hearings.csv")
    camara = load_camara(root, actor_rows)
    if camara is None:
        print("Câmara snapshot missing: RQ2 and bloc analyses skipped (run voxlab.camara_api --download).")
    results = analyze(read_rows(stance_path), actor_rows, camara)
    (processed / "party_alignment_results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    labels = label_actors(actor_rows, camara)
    write_csv(processed / "party_actor_labels.csv",
              [{"hearing_id": k[0], "actor_index": k[1], **{f: v for f, v in lab.items()}}
               for k, lab in sorted(labels.items(), key=lambda item: (int(item[0][0]), int(item[0][1])))],
              ["hearing_id", "actor_index", "actor_id", "actor_type", "period", "party", "party_source",
               "deputado_id", "governism", "bloc"])
    if camara:
        score_rows = []
        for model, condition in itertools.product(MODELS, CONDITIONS):
            scores = deputy_government_scores(government_stances(read_rows(stance_path), model, condition), labels)
            for (deputy_id, period), cell in sorted(scores.items()):
                party = camara_api.party_on(camara["directory"][deputy_id]["party_timeline"],
                                            "2022-06-30" if period == "BOLSONARO" else "2023-06-30")
                roll = camara["governism"].get((deputy_id, period), {})
                score_rows.append({"model": model, "condition": condition, "deputado_id": deputy_id,
                                   "name": camara["directory"][deputy_id]["name"], "party": party,
                                   "period": period, "n_hearings": cell["n"], "hearing_score": cell["score"],
                                   "rollcall_governism": roll.get("governism", ""),
                                   "rollcall_n": roll.get("n", "")})
        write_csv(processed / "party_deputy_scores.csv", score_rows,
                  ["model", "condition", "deputado_id", "name", "party", "period", "n_hearings", "hearing_score",
                   "rollcall_governism", "rollcall_n"])
    print(json.dumps({k: v for k, v in results.items() if k != "runs"}, ensure_ascii=False, indent=2)[:4000])


if __name__ == "__main__":
    main()
