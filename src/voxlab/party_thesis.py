"""Tests of the paper's thesis: "bipolar in speech, multiparty in votes".

Builds on voxlab.party_alignment (same inputs, same labels); no network, no LLM.
Everything is computed separately per model on the literal-speech condition
(and on the masked-speech condition when it exists), never pooled.

Camps are an a priori coding of the 2023-2024 Chamber, declared here and in
docs/party_alignment.md: LEFT = PT, PSOL, PCdoB; RIGHT = PL, Novo; CENTRAO =
PSD, PP, Republicanos, União, MDB. Other parties are OTHER_PARTY; non-deputies
keep their actor type.

Analyses (numbering follows the plan):
 2. speech-vote validity beyond party: within-camp Spearman and OLS with party
    fixed effects;
 4. within-actor panel for actors present in both governments;
 5. RQ1 restricted to contested propositions (>=1 FAVOR and >=1 AGAINST);
 7. "support without voice": each camp's hearing stance relative to what its
    roll-call governism predicts (residuals), with bootstrap CIs;
 8. bipolar structure: polar share and internal division by camp;
 9. the previous government as foil: trend of mentions/criticism over the
    Lula term;
10. civil society: composition (new people) vs. within-person change.

    PYTHONPATH=src python -m voxlab.party_thesis
"""

from __future__ import annotations

import collections
import json
import random
from datetime import date
from pathlib import Path

import numpy as np
import statsmodels.api as sm
from scipy import stats

from .hearing_stance import MODELS
from .party_alignment import (
    GOVERNMENT_SCORE,
    SEED,
    actor_key,
    deputy_government_scores,
    directional_stances,
    government_stances,
    label_actors,
    load_camara,
    permutation_test,
    read_rows,
    spearman,
    within_hearing_pairs,
)

CAMPS = {"LEFT": {"PT", "PSOL", "PCDOB"}, "RIGHT": {"PL", "NOVO"},
         "CENTRAO": {"PSD", "PP", "REPUBLICANOS", "UNIAO", "MDB"}}
POLES = ("LEFT", "RIGHT")
BOOTSTRAPS = 2000
TRANSITION = date(2023, 1, 1)


def camp_of(label: dict) -> str:
    if label.get("actor_type") != "DEPUTY":
        return label.get("actor_type", "")
    party = label.get("party", "")
    for camp, parties in CAMPS.items():
        if party in parties:
            return camp
    return "OTHER_PARTY" if party else ""


def percentile_ci(draws: list[float]) -> list[float] | None:
    draws = sorted(d for d in draws if d is not None and not np.isnan(d))
    if len(draws) < 20:
        return None
    return [round(draws[int(0.025 * len(draws))], 4), round(draws[int(0.975 * len(draws)) - 1], 4)]


def rounded(value: float | None, digits: int = 4) -> float | None:
    return None if value is None or np.isnan(value) else round(float(value), digits)


# --------------------------------------------------------------------------
# 8. Bipolar structure
# --------------------------------------------------------------------------

def structure(values: list[str]) -> dict:
    """Shares plus polar share (S+C over addressed) and division (0 unanimous, 1 even split)."""
    counts = collections.Counter(values)
    n = len(values)
    support, criticize = counts["SUPPORT"], counts["CRITICIZE"]
    addressed = support + criticize + counts["MIXED"] + counts["NEUTRAL"]
    return {
        "n": n,
        "support": rounded(support / n) if n else None,
        "criticize": rounded(criticize / n) if n else None,
        "neutral_or_mixed": rounded((counts["NEUTRAL"] + counts["MIXED"]) / n) if n else None,
        "not_addressed": rounded(counts["NOT_ADDRESSED"] / n) if n else None,
        "polar_share": rounded((support + criticize) / addressed) if addressed else None,
        "division": rounded(2 * min(support, criticize) / (support + criticize)) if support + criticize else None,
        "net_support": rounded((support - criticize) / addressed) if addressed else None,
    }


def bipolar_structure(government: dict, labels: dict, period: str = "LULA",
                      n_boot: int = BOOTSTRAPS, seed: int = SEED) -> dict:
    """Per camp, with CIs by resampling hearings; plus CENTRAO minus pooled poles."""
    by_hearing = collections.defaultdict(lambda: collections.defaultdict(list))
    for key, value in government.items():
        label = labels.get(key)
        if label and label["period"] == period and value and camp_of(label):
            by_hearing[key[0]][camp_of(label)].append(value)
    hearings = sorted(by_hearing)

    def compute(sample: list[str]) -> dict:
        pooled = collections.defaultdict(list)
        for hearing_id in sample:
            for camp, values in by_hearing[hearing_id].items():
                pooled[camp].extend(values)
        result = {camp: structure(values) for camp, values in pooled.items()}
        # Shares compare against the pooled poles; division compares against the mean of each
        # pole's own division (pooling LEFT and RIGHT would make the poles look split).
        poles = structure(pooled["LEFT"] + pooled["RIGHT"])
        center = result.get("CENTRAO")
        if center and poles["n"]:
            diff = {metric: rounded(center[metric] - poles[metric])
                    if center[metric] is not None and poles[metric] is not None else None
                    for metric in ("polar_share", "neutral_or_mixed")}
            pole_divisions = [result[c]["division"] for c in POLES if c in result and result[c]["division"] is not None]
            diff["division"] = (rounded(center["division"] - float(np.mean(pole_divisions)))
                                if center["division"] is not None and pole_divisions else None)
            result["CENTRAO_minus_POLES"] = diff
        return result

    observed = compute(hearings)
    rng = random.Random(seed)
    draws = [compute(rng.choices(hearings, k=len(hearings))) for _ in range(n_boot)]
    for camp, cell in observed.items():
        for metric in ("polar_share", "division", "net_support", "neutral_or_mixed"):
            if metric in cell:
                cell[f"{metric}_ci95"] = percentile_ci([d.get(camp, {}).get(metric) for d in draws])
    return {"period": period, "unit": "actor x hearing", "bootstrap": "hearings", **observed}


# --------------------------------------------------------------------------
# 2 + 7. Speech vs vote beyond party; support without voice
# --------------------------------------------------------------------------

def deputy_table(scores: dict, camara: dict, labels: dict, period: str) -> list[dict]:
    """One row per deputy in the period with hearing score, governism and camp."""
    party_by_deputy = {}
    for label in labels.values():
        if label["deputado_id"] and label["period"] == period:
            party_by_deputy.setdefault(label["deputado_id"], label)
    rows = []
    for (deputy_id, p), cell in scores.items():
        roll = camara["governism"].get((deputy_id, p))
        label = party_by_deputy.get(deputy_id)
        if p != period or not roll or not label:
            continue
        rows.append({"deputado_id": deputy_id, "party": label["party"], "camp": camp_of(label),
                     "score": cell["score"], "n": cell["n"], "governism": roll["governism"]})
    return rows


def beyond_party(rows: list[dict]) -> dict:
    """Within-camp Spearman and OLS score ~ governism + party fixed effects."""
    result = {"within_camp_spearman": {}}
    for camp in ("LEFT", "RIGHT", "CENTRAO", "OTHER_PARTY"):
        sub = [r for r in rows if r["camp"] == camp]
        result["within_camp_spearman"][camp] = spearman([r["governism"] for r in sub], [r["score"] for r in sub])
    parties = sorted({r["party"] for r in rows})
    if len(rows) > len(parties) + 5:
        X = np.array([[r["governism"]] + [float(r["party"] == p) for p in parties[1:]] for r in rows])
        fit = sm.OLS(np.array([r["score"] for r in rows]), sm.add_constant(X)).fit(cov_type="HC1")
        low, high = fit.conf_int()[1]
        result["ols_party_fixed_effects"] = {"n": len(rows), "n_parties": len(parties),
                                             "governism_coef": rounded(fit.params[1]),
                                             "ci95": [rounded(low), rounded(high)], "p": rounded(fit.pvalues[1])}
    return result


def support_without_voice(rows: list[dict], n_boot: int = BOOTSTRAPS, seed: int = SEED) -> dict:
    """Mean residual of hearing stance given roll-call governism (pooled OLS fit), by camp."""
    if len(rows) < 10:
        return {"n": len(rows), "note": "too few deputies"}

    def residual_means(sample: list[dict]) -> dict:
        x = np.array([r["governism"] for r in sample])
        y = np.array([r["score"] for r in sample])
        slope, intercept = np.polyfit(x, y, 1)
        by_camp = collections.defaultdict(list)
        for r, res in zip(sample, y - (intercept + slope * x)):
            by_camp[r["camp"]].append(res)
        means = {camp: float(np.mean(v)) for camp, v in by_camp.items()}
        poles = by_camp["LEFT"] + by_camp["RIGHT"]
        if "CENTRAO" in means and poles:
            means["CENTRAO_minus_POLES"] = means["CENTRAO"] - float(np.mean(poles))
        if "CENTRAO" in means and "LEFT" in means:
            means["CENTRAO_minus_LEFT"] = means["CENTRAO"] - means["LEFT"]
        means["_slope"] = float(slope)
        return means

    observed = residual_means(rows)
    rng = random.Random(seed)
    draws = [residual_means(rng.choices(rows, k=len(rows))) for _ in range(n_boot)]
    counts = collections.Counter(r["camp"] for r in rows)
    mean_governism = {camp: rounded(np.mean([r["governism"] for r in rows if r["camp"] == camp]))
                      for camp in counts}
    return {"n_deputies": len(rows), "slope": rounded(observed.pop("_slope")),
            "residual_by_camp": {k: {"mean": rounded(v), "ci95": percentile_ci([d.get(k) for d in draws]),
                                     "n": counts.get(k)} for k, v in observed.items()},
            "mean_governism_by_camp": mean_governism, "bootstrap": "deputies"}


# --------------------------------------------------------------------------
# 4. Within-actor panel
# --------------------------------------------------------------------------

def within_actor_panel(government: dict, labels: dict, n_boot: int = BOOTSTRAPS, seed: int = SEED) -> dict:
    """Actors with addressed government stance in both periods: change Lula - Bolsonaro by camp.
    Camp of a deputy is taken from the Lula-period label."""
    per_actor = collections.defaultdict(lambda: collections.defaultdict(list))
    camp_by_actor = {}
    for key, value in government.items():
        label = labels.get(key)
        if not label or value not in GOVERNMENT_SCORE:
            continue
        per_actor[label["actor_id"]][label["period"]].append(GOVERNMENT_SCORE[value])
        if label["period"] == "LULA" or label["actor_id"] not in camp_by_actor:
            camp_by_actor[label["actor_id"]] = camp_of(label)
    changes = collections.defaultdict(list)
    actors = []
    for actor_id, periods in sorted(per_actor.items()):
        if periods.get("BOLSONARO") and periods.get("LULA"):
            change = float(np.mean(periods["LULA"]) - np.mean(periods["BOLSONARO"]))
            changes[camp_by_actor[actor_id]].append(change)
            actors.append({"actor_id": actor_id, "camp": camp_by_actor[actor_id], "change": rounded(change),
                           "n_bolsonaro": len(periods["BOLSONARO"]), "n_lula": len(periods["LULA"])})
    rng = random.Random(seed)
    summary = {}
    for camp, values in sorted(changes.items()):
        up, down = sum(v > 0 for v in values), sum(v < 0 for v in values)
        summary[camp] = {"n_actors": len(values), "mean_change": rounded(np.mean(values)),
                         "ci95": percentile_ci([float(np.mean(rng.choices(values, k=len(values))))
                                                for _ in range(n_boot)]),
                         "increased": up, "decreased": down,
                         "sign_test_p": rounded(stats.binomtest(up, up + down).pvalue) if up + down else None}
    return {"by_camp": summary, "actors": actors}


# --------------------------------------------------------------------------
# 5. RQ1 on contested propositions
# --------------------------------------------------------------------------

def contested_only(stances: dict[tuple, dict]) -> dict[tuple, dict]:
    """Keep (hearing, proposition) cells where someone favors and someone opposes."""
    return {k: v for k, v in stances.items() if 1 in v.values() and -1 in v.values()}


# --------------------------------------------------------------------------
# 9. Previous government as foil
# --------------------------------------------------------------------------

def months_since_transition(iso: str) -> float:
    d = date.fromisoformat(iso)
    return (d - TRANSITION).days / 30.44


def previous_government_trend(previous: dict, labels: dict, dates: dict) -> dict:
    """Logistic trend over the Lula term of mentioning / criticizing the previous government,
    cluster-robust by hearing; semester shares and shares by camp."""
    rows = [(key, value) for key, value in previous.items()
            if value and labels.get(key, {}).get("period") == "LULA"]
    months = np.array([months_since_transition(dates[key]) for key, _ in rows])
    groups = np.array([int(key[0]) for key, _ in rows])
    result = {"n": len(rows)}
    for outcome, test in (("mention", lambda v: v != "NOT_ADDRESSED"), ("criticize", lambda v: v == "CRITICIZE")):
        y = np.array([float(test(v)) for _, v in rows])
        fit = sm.GLM(y, sm.add_constant(months), family=sm.families.Binomial()).fit(
            cov_type="cluster", cov_kwds={"groups": groups})
        low, high = fit.conf_int()[1]
        result[outcome] = {"odds_ratio_per_6_months": rounded(np.exp(6 * fit.params[1])),
                           "ci95": [rounded(np.exp(6 * low)), rounded(np.exp(6 * high))],
                           "p": rounded(fit.pvalues[1]), "overall_share": rounded(y.mean())}
    semesters = collections.defaultdict(lambda: [0, 0, 0])
    camps = collections.defaultdict(lambda: [0, 0, 0])
    for key, value in rows:
        iso = dates[key]
        for bucket in (semesters[iso[:4] + ("-S1" if iso[5:7] <= "06" else "-S2")], camps[camp_of(labels[key])]):
            bucket[0] += 1
            bucket[1] += value != "NOT_ADDRESSED"
            bucket[2] += value == "CRITICIZE"
    shape = lambda d: {k: {"n": n, "mention": rounded(m / n), "criticize": rounded(c / n)}  # noqa: E731
                       for k, (n, m, c) in sorted(d.items()) if k}
    result["by_semester"] = shape(semesters)
    result["by_camp"] = shape(camps)
    return result


# --------------------------------------------------------------------------
# 10. Civil society: composition vs within-person change
# --------------------------------------------------------------------------

def civil_society_decomposition(government: dict, labels: dict) -> dict:
    per_actor = collections.defaultdict(lambda: collections.defaultdict(list))
    for key, value in government.items():
        label = labels.get(key)
        if label and label["actor_type"] == "CIVIL_SOCIETY_OR_OTHER" and value in GOVERNMENT_SCORE:
            per_actor[label["actor_id"]][label["period"]].append(GOVERNMENT_SCORE[value])
    both = [a for a, p in per_actor.items() if p.get("BOLSONARO") and p.get("LULA")]
    net = {p: [v for a in per_actor.values() for v in a.get(p, [])] for p in ("BOLSONARO", "LULA")}
    lula_rows = sum(len(a.get("LULA", [])) for a in per_actor.values())
    lula_rows_recurrent = sum(len(per_actor[a]["LULA"]) for a in both)
    within = [float(np.mean(per_actor[a]["LULA"]) - np.mean(per_actor[a]["BOLSONARO"])) for a in both]
    return {
        "net_support": {p: rounded(np.mean(v)) if v else None for p, v in net.items()},
        "n_addressed": {p: len(v) for p, v in net.items()},
        "distinct_actors": {p: sum(1 for a in per_actor.values() if a.get(p)) for p in ("BOLSONARO", "LULA")},
        "actors_in_both_periods": len(both),
        "lula_rows_from_recurrent_actors_share": rounded(lula_rows_recurrent / lula_rows) if lula_rows else None,
        "within_person_mean_change": rounded(np.mean(within)) if within else None,
        "reading": ("If almost all Lula-period civil-society rows come from people absent before 2023, "
                    "the aggregate shift is compositional (who is invited/covered), not within-person change."),
    }


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------

def analyze(stance_rows: list[dict], actor_rows: list[dict], camara: dict, condition: str = "speech") -> dict:
    labels = label_actors(actor_rows, camara)
    dates = {actor_key(r): r["publication_date"] for r in actor_rows}
    result = {"label_source": "MODEL_PREDICTION", "condition": condition,
              "camps": {k: sorted(v) for k, v in CAMPS.items()}, "models": {}}
    for model in MODELS:
        government = government_stances(stance_rows, model, condition)
        previous = government_stances(stance_rows, model, condition, "previous_government_stance")
        scores = deputy_government_scores(government, labels)
        stances = directional_stances(stance_rows, model, condition)
        contested = contested_only(stances)
        run = {
            "8_bipolar_structure": bipolar_structure(government, labels),
            "8_bipolar_structure_bolsonaro": bipolar_structure(government, labels, "BOLSONARO", n_boot=0),
            "4_within_actor_panel": within_actor_panel(government, labels),
            "5_rq1_contested": {
                "n_cells_all": len(stances), "n_cells_contested": len(contested),
                **{group: permutation_test(within_hearing_pairs(contested, labels, group), labels, group)
                   for group in ("party", "bloc")}},
            "9_previous_government": previous_government_trend(previous, labels, dates),
            "10_civil_society": civil_society_decomposition(government, labels),
        }
        for period in ("LULA", "BOLSONARO"):
            rows = deputy_table(scores, camara, labels, period)
            run[f"2_beyond_party_{period.lower()}"] = beyond_party(rows)
            run[f"7_support_without_voice_{period.lower()}"] = support_without_voice(rows)
        result["models"][model] = run
    return result


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    processed = root / "data" / "processed"
    actor_rows = read_rows(processed / "party_actor_hearings.csv")
    camara = load_camara(root, actor_rows)
    if camara is None:
        raise SystemExit("Câmara snapshot missing: run voxlab.camara_api --download first.")
    stance_rows = read_rows(processed / "party_stances.csv")
    conditions = sorted({r["condition"] for r in stance_rows} & {"speech", "speech_masked"})
    results = {condition: analyze(stance_rows, actor_rows, camara, condition) for condition in conditions}
    (processed / "party_thesis_results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n",
                                                        encoding="utf-8")
    print(f"wrote party_thesis_results.json for conditions {conditions}")


if __name__ == "__main__":
    main()
