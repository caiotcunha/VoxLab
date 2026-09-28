"""Trade-off figure: reversal recall versus the two errors a gate should prevent.

Reads data/processed/decoupled_gate/decoupled_gate_metrics.json (no API) and
writes docs/figures/gate_tradeoff.{png,pdf}. One point per model x condition,
on the synthetic contrast items of both splits.

Requires matplotlib, which the rest of the pipeline does not:
    <python with matplotlib> src/voxlab/tradeoff_figure.py
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
METRICS = ROOT / "data/processed/decoupled_gate/decoupled_gate_metrics.json"
OUT = ROOT / "docs/figures/gate_tradeoff"

# Three families, fixed order (validated: all-pairs CVD >= 9.2 in light mode).
FAMILIES = {
    "A_end_to_end": ("End-to-end", "#2a78d6"),
    "B_forced_comparability": ("Sem gate", "#eb6834"),
    "D_forced_comparability": ("Sem gate", "#eb6834"),
    "C_structured_with_gate": ("Com gate", "#1baf7a"),
    "D_decoupled_gate": ("Com gate", "#1baf7a"),
}
MARKERS = {  # shape = how the relation is produced
    "A_end_to_end": ("s", "uma chamada"),
    "B_forced_comparability": ("o", "estruturado (v1)"),
    "C_structured_with_gate": ("o", "estruturado (v1)"),
    "D_forced_comparability": ("^", "desacoplado"),
    "D_decoupled_gate": ("^", "desacoplado"),
}
TEXT, MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
RECALL = "reversal_recall__REVERSE_ON_COMPARABLE"
PANELS = [
    ("false_reversal__REVERSE_ON_INCOMPARABLE", "Falsa reversão\n(stance invertida em par incomparável)"),
    ("false_comparability__SHIFT_PROPOSITION", "Falsa comparabilidade\n(proposição deslocada)"),
]


def short_model(model: str) -> str:
    return {"Qwen/Qwen2.5-72B-Instruct": "Qwen2.5", "meta-llama/Llama-3.3-70B-Instruct-Turbo": "Llama3.3",
            "zai-org/GLM-5.2": "GLM-5.2", "nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B": "Nemotron-U",
            "openai/gpt-oss-120b": "gpt-oss"}.get(model, model.split("/")[-1])


def main() -> None:
    headline = json.loads(METRICS.read_text(encoding="utf-8"))["synthetic_headline"]["all"]
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.6), sharey=True, facecolor=SURFACE)
    for ax, (metric, title) in zip(axes, PANELS):
        ax.set_facecolor(SURFACE)
        for model, conditions in headline.items():
            for condition, values in conditions.items():
                x, y = values.get(metric, {}), values.get(RECALL, {})
                if not x.get("n") or not y.get("n"):
                    continue
                label, color = FAMILIES[condition]
                marker, _ = MARKERS[condition]
                ax.scatter(x["rate"], y["rate"], s=64, marker=marker, color=color, alpha=0.85,
                           edgecolors=SURFACE, linewidths=2, zorder=3)
        ax.annotate("ideal", xy=(0, 1), xytext=(0.06, 0.93), color=MUTED, fontsize=9,
                    arrowprops={"arrowstyle": "->", "color": MUTED, "lw": 1})
        ax.set_xlim(-0.05, 1.05)
        ax.set_ylim(-0.05, 1.05)
        ax.set_xlabel(title, color=TEXT, fontsize=10)
        ax.grid(color=GRID, linewidth=0.8, zorder=0)
        ax.tick_params(colors=MUTED, labelsize=9)
        for spine in ax.spines.values():
            spine.set_visible(False)
    axes[0].set_ylabel("Reversões verdadeiras detectadas\n(recall em reversões sintéticas)", color=TEXT, fontsize=10)

    color_handles = [plt.Line2D([], [], marker="o", ls="", color=c, markersize=8, label=l)
                     for l, c in [("End-to-end", "#2a78d6"), ("Sem gate", "#eb6834"), ("Com gate", "#1baf7a")]]
    shape_handles = [plt.Line2D([], [], marker=m, ls="", color=MUTED, markersize=8, label=l)
                     for m, l in [("s", "uma chamada"), ("o", "estruturado (v1)"), ("^", "desacoplado")]]
    fig.legend(handles=color_handles + shape_handles, loc="upper center", ncol=6, frameon=False,
               fontsize=9, labelcolor=TEXT, bbox_to_anchor=(0.5, 1.0))
    models = ", ".join(short_model(m) for m in headline)
    fig.text(0.5, -0.02, f"Um ponto por modelo × condição ({models}). Itens: contrafactuais aceitos, dev + teste.",
             ha="center", color=MUTED, fontsize=8.5)
    fig.tight_layout(rect=(0, 0.02, 1, 0.93))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    for ext in ("png", "pdf"):
        fig.savefig(OUT.with_suffix(f".{ext}"), dpi=200, bbox_inches="tight", facecolor=SURFACE)
    print(OUT.with_suffix(".png"))


if __name__ == "__main__":
    main()
