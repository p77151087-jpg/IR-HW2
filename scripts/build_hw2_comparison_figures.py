"""Render additional report comparisons from the saved, unchanged analysis.

Run with the project Python. Outputs live outside the 21 formal experiment
artifacts. No corpus download, tokenization, regression or model training.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ir_hw2.comparisons import COLORS, SEGMENT_COLORS, representative_terms, selected_term_rows

REPORTS = ROOT / "reports/hw2"
OUTPUT = REPORTS / "figures"
SOURCE = REPORTS / "experiment/summary.json"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def finish(fig, name, description, evidence):
    path = OUTPUT / name
    fig.savefig(path, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    evidence.append({"path": path.relative_to(ROOT).as_posix(), "sha256": digest(path), "description": description})


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    summary = json.loads(SOURCE.read_text(encoding="utf-8"))
    evidence = []
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                         "axes.spines.top": False, "axes.spines.right": False,
                         "axes.titleweight": "bold", "axes.axisbelow": True})

    fig, axes = plt.subplots(2, 2, figsize=(11, 7.2), layout="constrained")
    labels = ["Basic", "+ punctuation", "+ stopword removal", "+ Porter"]
    max_cf = max(d["top50"][0]["cf"] for d in summary["conditions"].values())
    for ax, (condition, data), label in zip(axes.flat, summary["conditions"].items(), labels):
        rows = data["top50"][:10]
        bars = ax.barh([row["term"] for row in rows], [row["cf"] for row in rows], color=COLORS[condition])
        ax.bar_label(bars, labels=[f"{row['cf']:,}" for row in rows], padding=4, fontsize=8)
        ax.invert_yaxis()
        ax.set(xlim=(0, max_cf * 1.17), xlabel="Collection frequency (CF)", title=f"{condition}: {label}")
        ax.grid(axis="x", alpha=.18)
    fig.suptitle("High-frequency words: Top 10 in each condition", fontsize=15, fontweight="bold")
    finish(fig, "high_frequency_terms.png", "Four Top 10 lists; shared CF scale; independent ranks.", evidence)

    fig, axes = plt.subplots(1, 2, figsize=(11, 4), layout="constrained")
    for ax, metric, title in zip(axes, ["r_squared", "rmse"], ["R² (higher is better)", "RMSE in log(CF) (lower is better)"]):
        for i, segment in enumerate(["head", "middle", "tail"]):
            values = [data["segments"][segment][metric] for data in summary["conditions"].values()]
            ax.bar(np.arange(4) + (i - 1) * .24, values, width=.23, color=SEGMENT_COLORS[i], label=segment.title())
        ax.set(xticks=range(4), xticklabels=list(COLORS), xlabel="Condition", title=title)
        ax.set_ylim(0, 1.06 if metric == "r_squared" else .12)
        ax.grid(axis="y", alpha=.18)
    axes[0].legend(ncols=3, loc="upper left", bbox_to_anchor=(0, -.18), frameon=False)
    fig.suptitle("Separate fits: head 1% / middle to 10% / remaining tail", fontsize=13, fontweight="bold")
    finish(fig, "segment_fit.png", "All 12 saved segment fits, showing both R² and RMSE.", evidence)

    rows = selected_term_rows(summary)
    by_term = {row["term"]: row for row in rows}
    fig, ax = plt.subplots(figsize=(9, 5.6), layout="constrained")
    ax.plot([1, 1000], [1, 1000], "--", color="#8997A5", linewidth=1.2, label="CF = DF (once per matching document)")
    ax.scatter([r["df"] for r in rows], [r["cf"] for r in rows], color=COLORS["B"], s=40, alpha=.8)
    offsets = {"and": (-40, 2), "semaglutide": (-90, 18), "receptor": (-65, 7),
               "glp-1": (-18, 20), "insulin": (-45, -23), "il6": (10, 8),
               "pathway-specific": (10, -17), "endotyping": (12, -7), "play": (10, -12)}
    for term, offset in offsets.items():
        if term in by_term:
            row = by_term[term]
            ax.annotate(term, (row["df"], row["cf"]), xytext=offset, textcoords="offset points", fontsize=8,
                        arrowprops={"arrowstyle": "-", "color": "#AAB7BD", "lw": .65})
    ax.set(xscale="log", yscale="log", xlabel="Document frequency (DF; log scale)",
           ylabel="Collection frequency (CF; log scale)", title=f"CF versus DF: {len(rows)} selected terms, condition B")
    ax.grid(alpha=.18)
    ax.legend(loc="upper left", frameon=False, fontsize=9)
    finish(fig, "cf_df.png", "B selected terms, CF = DF reference, all coordinates from saved results.", evidence)

    n = summary["conditions"]["B"]["documents"]
    fig, ax = plt.subplots(figsize=(9, 4.7), layout="constrained")
    dfs = np.geomspace(1, n, 200)
    ax.plot(dfs, np.log10(n / dfs), color="#ADB8BF", label="IDF = log(N / DF), base 10")
    ax.scatter([r["df"] for r in rows], [r["idf"] for r in rows], color=COLORS["B"], s=40, alpha=.8, label="Selected terms")
    for term, offset in {"il6": (12, -5), "pathway-specific": (10, 10), "semaglutide": (-90, -20), "and": (-36, 13)}.items():
        if term in by_term:
            row = by_term[term]
            ax.annotate(term, (row["df"], row["idf"]), xytext=offset, textcoords="offset points", fontsize=9,
                        arrowprops={"arrowstyle": "-", "color": "#8997A5", "lw": .7})
    ax.set(xscale="log", xlabel="DF: documents containing the term (log scale)", ylabel="IDF",
           title=f"More document coverage, lower IDF (N = {n:,})", ylim=(-.1, np.log10(n) + .15))
    ax.grid(alpha=.18)
    ax.legend(loc="upper right", frameon=False)
    finish(fig, "idf_relation.png", "Specified base-10 IDF formula and observed term coordinates; IDF axis is linear.", evidence)

    chosen = representative_terms(summary)
    fig, ax = plt.subplots(figsize=(9, 5.3), layout="constrained")
    bars = ax.barh([r["term"] for r in chosen], [r["idf"] for r in chosen], color=COLORS["B"])
    ax.bar_label(bars, labels=[f"{r['idf']:.3f}  (DF={r['df']})" for r in chosen], padding=5, fontsize=9)
    ax.invert_yaxis()
    ax.set(xlim=(0, max(r["idf"] for r in chosen) * 1.38), xlabel="IDF = log(N / DF)",
           title="Representative terms: common, domain and rare words")
    ax.grid(axis="x", alpha=.18)
    finish(fig, "idf_terms.png", "Twelve real terms; IDF with corresponding DF labels.", evidence)

    manifest = {"source": SOURCE.relative_to(ROOT).as_posix(), "source_sha256": digest(SOURCE),
                "code": [{"path": p, "sha256": digest(ROOT / p)} for p in [
                    "scripts/build_hw2_comparison_figures.py", "ir_hw2/comparisons.py"]],
                "figures": evidence}
    (REPORTS / "comparison_figures.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"figures": len(evidence), "output": str(OUTPUT)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
