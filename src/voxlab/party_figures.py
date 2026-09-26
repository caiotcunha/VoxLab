"""Static figures for the party-alignment paper (PDF + PNG, light theme for print).

Reads data/processed/party_alignment_results.json, party_deputy_scores.csv and
the Câmara snapshot; writes docs/figures/party_*.{pdf,png}. The primary model
and condition (literal speech) are shown; the other runs are in the JSON.

Colors: first three slots of the dataviz reference categorical palette
(validated all-pairs for up to three series), assigned in fixed order.

    PYTHONPATH=src python -m voxlab.party_figures
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from .hearing_stance import MODELS  # noqa: E402

SERIES = ("#2a78d6", "#eb6834", "#1baf7a")  # slots 1-3: blue, orange, aqua
TEXT, TEXT_2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
BLOCS = ("GOVERNMENT", "PIVOT", "OPPOSITION")
BLOC_NAMES = {"GOVERNMENT": "Governo (sob Lula)", "PIVOT": "Pivô (sob Lula)", "OPPOSITION": "Oposição (sob Lula)"}
PERIOD_NAMES = {"BOLSONARO": "Governo Bolsonaro", "LULA": "Governo Lula"}
SHORT = {MODELS[0]: "Qwen2.5-72B", MODELS[1]: "Llama-3.3-70B"}
PRIMARY_CONDITION = "speech"


def style() -> None:
    plt.rcParams.update({
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
        "axes.edgecolor": GRID, "axes.labelcolor": TEXT_2, "xtick.color": TEXT_2, "ytick.color": TEXT_2,
        "text.color": TEXT, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
        "axes.spines.top": False, "axes.spines.right": False, "font.size": 9, "axes.titlesize": 10,
        "axes.titleweight": "bold", "legend.frameon": False,
    })


def save(fig, out: Path, name: str) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for ext in ("pdf", "png"):
        fig.savefig(out / f"{name}.{ext}", dpi=200, bbox_inches="tight")
    plt.close(fig)


def spread(items: list[list], gap: float) -> list[list]:
    """Nudge label y-positions apart (keeping order) so direct labels do not collide."""
    items = sorted(items, key=lambda item: -item[0])
    for i in range(1, len(items)):
        items[i][0] = min(items[i][0], items[i - 1][0] - gap)
    return items


def fig_rollcall_governism(results: dict, out: Path) -> None:
    """Context: party governism in roll calls, Bolsonaro -> Lula (slope chart)."""
    governism = results["party_governism"]
    parties = ["PT", "PSOL", "PCDOB", "PSB", "PDT", "MDB", "PSD", "UNIAO", "PP", "REPUBLICANOS", "PL", "NOVO"]
    fig, ax = plt.subplots(figsize=(4.2, 4.2))
    ends = []
    for party in parties:
        before, after = governism.get(f"{party}|BOLSONARO"), governism.get(f"{party}|LULA")
        if before is None or after is None:
            continue
        bloc = "GOVERNMENT" if after >= 0.70 else "OPPOSITION" if after < 0.40 else "PIVOT"
        color = SERIES[BLOCS.index(bloc)]
        ax.plot([0, 1], [before, after], color=color, linewidth=2, marker="o", markersize=5)
        ends.append([after, party, after])
    for y, party, actual in spread(ends, gap=0.03):
        ax.plot([1.02, 1.09], [actual, y], color=GRID, linewidth=0.8, clip_on=False)
        ax.text(1.1, y, party, va="center", fontsize=7.5, color=TEXT_2)
    ax.set_xticks([0, 1], [PERIOD_NAMES["BOLSONARO"], PERIOD_NAMES["LULA"]])
    ax.set_xlim(-0.15, 1.45)
    ax.set_ylim(0, 1.02)
    ax.set_ylabel("Governismo nas votações nominais")
    ax.set_title("Partidos trocam de papel na alternância de 2023")
    handles = [plt.Line2D([], [], color=SERIES[i], linewidth=2, label=BLOC_NAMES[b]) for i, b in enumerate(BLOCS)]
    ax.legend(handles=handles, loc="lower left", fontsize=7.5)
    save(fig, out, "party_fig1_rollcall_governism")


def fig_government_by_bloc(results: dict, out: Path) -> None:
    """RQ3: net support for the government in office, by Lula-period bloc and period."""
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.2), sharey=True)
    for ax, model in zip(axes, MODELS):
        run = results["runs"][f"{model}|{PRIMARY_CONDITION}"]["rq3"].get("government_stance_by_lula_bloc", {})
        for i, bloc in enumerate(BLOCS):
            for j, period in enumerate(("BOLSONARO", "LULA")):
                cell = run.get(f"{bloc}|{period}")
                if not cell or cell["net_support"] is None:
                    continue
                x = i + (j - 0.5) * 0.32
                low, high = cell["ci95"] or (cell["net_support"], cell["net_support"])
                ax.errorbar(x, cell["net_support"], yerr=[[cell["net_support"] - low], [high - cell["net_support"]]],
                            fmt="o", color=SERIES[j], markersize=6, linewidth=1.5, capsize=0)
                ax.annotate(f"n={cell['n_addressed']}", (x, low), xytext=(0, -9), textcoords="offset points",
                            ha="center", fontsize=6.5, color=TEXT_2)
        ax.axhline(0, color=TEXT_2, linewidth=0.8)
        ax.set_xticks(range(3), [BLOC_NAMES[b].replace(" (sob Lula)", "") for b in BLOCS])
        ax.set_title(SHORT[model])
        ax.set_ylim(-1.1, 1.1)
    axes[0].set_ylabel("Apoio líquido ao governo vigente\n(+1 apoia, −1 critica)")
    handles = [plt.Line2D([], [], color=SERIES[j], marker="o", linestyle="", label=PERIOD_NAMES[p])
               for j, p in enumerate(("BOLSONARO", "LULA"))]
    fig.legend(handles=handles, loc="upper center", ncol=2, bbox_to_anchor=(0.5, 1.06), fontsize=8)
    fig.text(0.5, -0.04, "Blocos definidos pelo governismo do partido nas votações sob Lula; IC 95% por bootstrap "
             "de audiências.", ha="center", fontsize=7, color=TEXT_2)
    save(fig, out, "party_fig2_government_stance_by_bloc")


def fig_speech_vs_vote(scores: list[dict], results: dict, out: Path) -> None:
    """RQ2: deputy hearing stance toward the government vs roll-call governism (Lula period)."""
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.3), sharey=True)
    for ax, model in zip(axes, MODELS):
        rows = [r for r in scores if r["model"] == model and r["condition"] == PRIMARY_CONDITION
                and r["period"] == "LULA" and r["rollcall_governism"] != ""]
        for row in rows:
            governism = float(row["rollcall_governism"])
            bloc = "GOVERNMENT" if governism >= 0.70 else "OPPOSITION" if governism < 0.40 else "PIVOT"
            ax.scatter(governism, float(row["hearing_score"]), s=14 + 6 * min(int(row["n_hearings"]), 6),
                       color=SERIES[BLOCS.index(bloc)], alpha=0.75, edgecolors=SURFACE, linewidths=0.8)
        stat = results["runs"][f"{model}|{PRIMARY_CONDITION}"].get("rq2", {}).get("speech_vs_vote_governism", {})
        lula = stat.get("LULA", {})
        rho = f"\nSpearman ρ = {lula['rho']:.2f} (n = {lula['n']})" if lula.get("rho") is not None else ""
        ax.set_title(SHORT[model] + rho)
        ax.set_xlabel("Governismo nas votações (2023–2024)")
        ax.set_xlim(0, 1.02)
        ax.set_ylim(-1.1, 1.1)
    axes[0].set_ylabel("Postura sobre o governo nas audiências")
    handles = [plt.Line2D([], [], color=SERIES[i], marker="o", linestyle="", label=BLOC_NAMES[b].split(" (")[0])
               for i, b in enumerate(BLOCS)]
    fig.legend(handles=handles, loc="upper center", ncol=3, bbox_to_anchor=(0.5, 1.13), fontsize=8)
    save(fig, out, "party_fig3_speech_vs_vote")


def fig_within_hearing_agreement(results: dict, out: Path) -> None:
    """RQ1: agreement rate for same- vs different-group deputy pairs, per run."""
    runs = [(m, c) for m in MODELS for c in ("speech", "lds_summary")]
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.0), sharey=True)
    for ax, group in zip(axes, ("party", "bloc")):
        for k, (model, condition) in enumerate(runs):
            cell = results["runs"][f"{model}|{condition}"]["rq1"].get(group)
            if not cell or cell["gap"] is None:
                continue
            for j, (key, n_key) in enumerate((("agreement_same_group", "n_pairs_same_group"),
                                               ("agreement_diff_group", "n_pairs_diff_group"))):
                ax.bar(k + (j - 0.5) * 0.36, cell[key], width=0.34, color=SERIES[j])
            ax.annotate(f"p={cell['permutation_p']:.3f}", (k, max(cell["agreement_same_group"],
                        cell["agreement_diff_group"])), xytext=(0, 3), textcoords="offset points",
                        ha="center", fontsize=6.5, color=TEXT_2)
        ax.set_xticks(range(len(runs)), [f"{SHORT[m].split('-')[0].split('2')[0]}\n{'fala' if c == 'speech' else 'resumo'}" for m, c in runs],
                      fontsize=7)
        ax.set_title("Mesmo partido × partidos diferentes" if group == "party" else "Mesmo bloco × blocos diferentes")
        ax.set_ylim(0, 1.08)
        ax.grid(axis="x", visible=False)
    axes[0].set_ylabel("Taxa de concordância entre pares\nde deputados na mesma proposição")
    handles = [plt.Rectangle((0, 0), 1, 1, color=SERIES[j], label=label)
               for j, label in enumerate(("Mesmo grupo", "Grupos diferentes"))]
    fig.legend(handles=handles, loc="upper center", ncol=2, bbox_to_anchor=(0.5, 1.07), fontsize=8)
    save(fig, out, "party_fig4_within_hearing_agreement")


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    processed = root / "data" / "processed"
    results = json.loads((processed / "party_alignment_results.json").read_text(encoding="utf-8"))
    with (processed / "party_deputy_scores.csv").open(newline="", encoding="utf-8") as handle:
        scores = list(csv.DictReader(handle))
    out = root / "docs" / "figures"
    style()
    fig_rollcall_governism(results, out)
    fig_government_by_bloc(results, out)
    fig_speech_vs_vote(scores, results, out)
    fig_within_hearing_agreement(results, out)
    print(f"figures written to {out}")


if __name__ == "__main__":
    main()
