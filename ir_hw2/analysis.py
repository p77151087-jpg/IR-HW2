"""Reproducible abstract-only HW2 statistics, independent of search features.

A uses whitespace tokens and HW1 normalization; B applies the HW1 tokenizer's
punctuation rules; C removes a checked-in stoplist; D uses the HW1 Porter stemmer.
All four assignment conditions are included in the cumulative comparison.
Nothing here uses relevance features, compound expansion or smoothed search IDF.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import platform
import unicodedata
from collections import Counter
from functools import lru_cache
from importlib.metadata import version
from pathlib import Path
from typing import Iterable, Sequence

import regex

from ir_hw1 import preprocessing as hw1_preprocessing
from ir_hw1.models import Document

CONDITIONS = ("A", "B", "C", "D")
PIPELINE_VERSION = "hw2-hw1-four-conditions-v5-log10"
STOPWORDS_PATH = Path(__file__).resolve().parents[1] / "resources" / "hw2_stopwords.json"


def baseline_tokenizer_spec() -> dict:
    """Describe the HW1 token contract independently of analysis settings.

    Models can persist and compare this JSON-safe description without becoming
    stale when only statistical formulas or the HW2 analysis version change.
    """
    return {
        "implementation": "ir_hw1.preprocessing.tokenize",
        "version": hw1_preprocessing.TOKENIZER_VERSION,
        "regex": hw1_preprocessing.TOKEN_RE.pattern,
        "regex_flags": int(hw1_preprocessing.TOKEN_RE.flags),
        "normalization": {
            "implementation": "ir_hw1.preprocessing.normalize",
            "unicode_form": "NFC", "casefold": True,
            "replacements": {"’": "'", "‐": "-", "‑": "-"},
        },
        "source": "ir_hw1/preprocessing.py",
        "source_sha256": hashlib.sha256(Path(hw1_preprocessing.__file__).read_bytes()).hexdigest(),
        "dependencies": {"regex": version("regex"), "unicode_database": unicodedata.unidata_version},
        "remove_stopwords": False, "stemming": False,
        "search_feature_expansion": False, "isolated_letter_filter": False,
    }


@lru_cache(maxsize=1)
def stopword_spec() -> dict:
    """Read and validate the local, versioned stopword resource."""
    raw = STOPWORDS_PATH.read_bytes()
    spec = json.loads(raw)
    words = spec["words"]
    if len(words) != len(set(words)) or any(w != w.lower() or not w.isalpha() for w in words):
        raise ValueError("Stopword list must contain unique lowercase alphabetic words")
    if any(w in words for w in ("no", "not", "without")):
        raise ValueError("The HW2 stoplist must preserve no/not/without")
    return {**spec, "sha256": hashlib.sha256(raw).hexdigest(), "count": len(words)}


def tokenize(text: str, condition: str = "A") -> list[str]:
    """Return ordered experimental tokens; never expand biomedical compounds."""
    if condition not in CONDITIONS:
        raise ValueError(f"Unknown preprocessing condition: {condition!r}")
    if condition == "A":
        return [hw1_preprocessing.normalize(term) for term in text.split()]
    terms = [token.term for token in hw1_preprocessing.tokenize(text)]
    if condition in {"C", "D"}:
        stopwords = frozenset(stopword_spec()["words"])
        terms = [term for term in terms if term not in stopwords]
    if condition == "D":
        terms = [hw1_preprocessing.stem_term(term) for term in terms]
    return terms


def abstract_text(document: Document) -> str:
    """Only abstract body blocks: no title, section labels or full-text blocks."""
    return "\n".join(block.text for block in document.blocks if block.kind == "abstract")


def _validated_texts(documents: dict[str, Document]) -> list[tuple[str, str]]:
    if not documents:
        raise ValueError("Cannot analyze an empty document collection")
    result = []
    seen: set[str] = set()
    for document in documents.values():
        pmid = document.pmid.strip()
        if not regex.fullmatch(r"[1-9][0-9]*", pmid):
            raise ValueError(f"Every analysis document requires a valid PMID: {pmid!r}")
        if pmid in seen:
            raise ValueError(f"Duplicate PMID in analysis input: {pmid}")
        seen.add(pmid)
        text = abstract_text(document)
        if not text.strip():
            raise ValueError(f"PMID {pmid} has an empty abstract; exclude it explicitly before analysis")
        result.append((pmid, text))
    return sorted(result, key=lambda pair: int(pair[0]))


def text_fingerprint(texts: Iterable[tuple[str, str]]) -> str:
    """Hash the ordered PMID/abstract pairs using an unambiguous JSON encoding."""
    payload = json.dumps(list(texts), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def inverse_document_frequency(documents: int, df: int) -> float:
    """Assignment IDF = log10(N / DF), with no smoothing or additive constant."""
    if documents < 1 or not 1 <= df <= documents:
        raise ValueError("IDF requires 1 <= DF <= number of documents")
    return math.log10(documents / df)


def linear_regression(ranks: Sequence[float], frequencies: Sequence[float]) -> dict:
    """OLS of log10(CF) on log10(rank); nulls represent undefined statistics.

    RMSE uses divisor n in log10-frequency space. Constant log-frequency has no
    defined R-squared, even if the horizontal line has zero residual error.
    """
    if len(ranks) != len(frequencies):
        raise ValueError("Ranks and frequencies must have equal length")
    if any(not math.isfinite(x) or x <= 0 for x in (*ranks, *frequencies)):
        raise ValueError("Ranks and frequencies must be positive finite numbers")
    result = {
        "points": len(ranks), "rank_start": min(ranks) if ranks else None,
        "rank_end": max(ranks) if ranks else None, "slope": None, "intercept": None,
        "zipf_exponent": None, "r_squared": None, "rmse": None,
        "log_base": 10, "rmse_space": "log10(CF)", "status": "insufficient_points",
    }
    if len(ranks) < 2:
        return result
    x = [math.log10(rank) for rank in ranks]
    y = [math.log10(cf) for cf in frequencies]
    mean_x, mean_y = math.fsum(x) / len(x), math.fsum(y) / len(y)
    sxx = math.fsum((value - mean_x) ** 2 for value in x)
    if sxx <= 0:
        result["status"] = "constant_rank"
        return result
    if max(y) == min(y):
        result.update(slope=0.0, intercept=y[0], zipf_exponent=0.0,
                      rmse=0.0, status="constant_frequency")
        return result
    slope = math.fsum((a - mean_x) * (b - mean_y) for a, b in zip(x, y)) / sxx
    intercept = mean_y - slope * mean_x
    sse = math.fsum((b - (intercept + slope * a)) ** 2 for a, b in zip(x, y))
    sst = math.fsum((value - mean_y) ** 2 for value in y)
    result.update(slope=slope, intercept=intercept, zipf_exponent=-slope,
                  r_squared=1.0 - sse / sst,
                  rmse=math.sqrt(sse / len(x)),
                  status="ok")
    return result


def _segments(frequencies: Sequence[int]) -> dict:
    """Disjoint rank segments, floor percentages with a two-point head minimum.

    For V >= 6 every segment has at least two points. Tiny vocabularies retain
    as many points as possible and expose insufficient-point statuses instead
    of inventing regression metrics. Actual boundaries are always exported.
    """
    size = len(frequencies)
    head_end = min(size, max(2, math.floor(size * 0.01)))
    middle_end = min(size, max(head_end + 2, math.floor(size * 0.10)))
    if size >= 6:
        middle_end = min(middle_end, size - 2)
    bounds = {"head": (0, head_end), "middle": (head_end, middle_end), "tail": (middle_end, size)}
    return {
        name: linear_regression(list(range(start + 1, end + 1)), frequencies[start:end])
        for name, (start, end) in bounds.items()
    }


def _term_rows(condition: dict) -> list[dict]:
    return [
        {"rank": rank, "term": term, "cf": condition["cf"][term], "df": condition["df"][term],
         "idf": inverse_document_frequency(condition["documents"], condition["df"][term])}
        for rank, term in enumerate(condition["cf"], start=1)
    ]


def _select_terms(condition: dict) -> list[dict]:
    """Deterministically select B terms spanning frequencies and domain words."""
    rows = _term_rows(condition)
    if not rows:
        return []
    positions = set(range(min(10, len(rows))))
    positions.update(min(len(rows) - 1, max(0, math.ceil(len(rows) * q) - 1))
                     for q in (0.01, 0.03, 0.05, 0.10, 0.20, 0.30, 0.40, 0.50, 0.75, 1.0))
    domain = {"glp-1", "glp-1ra", "glp-1ras", "glucagon-like", "peptide-1", "β-cells", "il6",
              "glp", "semaglutide", "glucose", "diabetes", "insulin", "obesity", "receptor",
              "patients", "treatment", "agonist", "no", "not", "without"}
    positions.update(i for i, row in enumerate(rows) if row["term"] in domain)
    for i in range(len(rows)):
        if len(positions) >= min(20, len(rows)):
            break
        positions.add(i)
    return [{"condition": "B", **rows[i]} for i in sorted(positions)]


def analyze_documents(documents: dict[str, Document]) -> dict:
    """Analyze a fixed collection. Duplicate PMID and blank abstracts are errors.

    Documents whose tokens all disappear in C or D remain in N; otherwise IDF
    would change its population between conditions. Collection keys are not
    used as identities: authoritative document.pmid is validated separately.
    """
    texts = _validated_texts(documents)
    results = {}
    for label in CONDITIONS:
        cf: Counter[str] = Counter()
        df: Counter[str] = Counter()
        per_document = []
        for pmid, text in texts:
            terms = tokenize(text, label)
            cf.update(terms)
            df.update(set(terms))
            per_document.append({"pmid": pmid, "tokens": len(terms), "unique_terms": len(set(terms))})
        ordered = sorted(cf, key=lambda term: (-cf[term], term))
        frequencies = [cf[term] for term in ordered]
        tokens = sum(frequencies)
        singletons = sum(value == 1 for value in frequencies)
        condition = {
            "documents": len(texts), "tokens": tokens, "unique_terms": len(cf),
            "average_tokens_per_document": tokens / len(texts),
            "cf": {term: cf[term] for term in ordered}, "df": {term: df[term] for term in ordered},
            "per_document": per_document,
            "regression": linear_regression(list(range(1, len(cf) + 1)), frequencies),
            "segments": _segments(frequencies), "singleton_terms": singletons,
            "singleton_ratio": singletons / len(cf) if cf else 0.0,
            "singleton_token_share": singletons / tokens if tokens else 0.0,
            "top10_token_share": sum(frequencies[:10]) / tokens if tokens else 0.0,
            "postings_entries": sum(df.values()),
        }
        condition["top50"] = _term_rows(condition)[:50]
        results[label] = condition
    baseline = baseline_tokenizer_spec()
    metadata = {
        "pipeline_version": PIPELINE_VERSION,
        "analysis_code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "baseline_tokenizer": baseline,
        "primary_comparison": ["A", "B", "C", "D"], "reference_condition": None,
        "content": "Only TextBlock.kind == abstract text; labels, titles, full text excluded",
        "identity": "Unique PMID; input duplicate PMID, invalid PMID and blank abstracts rejected",
        "source_text_sha256": text_fingerprint(texts), "pmids": [pmid for pmid, _ in texts],
        "conditions": {
            "A": "Basic whitespace tokens + ir_hw1.preprocessing.normalize; attached punctuation retained",
            "B": "Punctuation processing: ir_hw1.preprocessing.tokenize token.term in source order; no added filtering or expansion",
            "C": "B + remove the fixed project stopword list",
            "D": "C + ir_hw1.preprocessing.stem_term; NLTK Porter MARTIN_EXTENSIONS on ASCII alphabetic tokens only",
        },
        "unicode_normalization": "HW1 normalize: NFC then casefold; right apostrophe and supported Unicode hyphens normalized",
        "punctuation_pattern": baseline["regex"],
        "punctuation_caveat": "HW1 keeps decimal numbers and internal supported hyphens/apostrophes; GLP-1, IL6, 3.5 and beta-cell compounds stay intact; other punctuation delimits tokens",
        "stopwords": stopword_spec(), "stemming": {"implementation": "nltk.stem.PorterStemmer",
            "adapter": "ir_hw1.preprocessing.stem_term",
            "mode": hw1_preprocessing.PORTER_PREPROCESSING["mode"],
            "scope": "ASCII alphabetic only; compounds, decimals and non-ASCII tokens preserved", "self_implemented": False},
        "ranking": "Descending CF; ties sorted by Unicode term, ordinal ranks 1..V; no tied mean ranks",
        "log_base": 10,
        "regression": "OLS log10(CF)=intercept+slope*log10(rank); exponent=-slope; full rank 1..V",
        "segments": "head to max(2,floor(.01*V)); middle to max(head+2,floor(.1*V)); tail remainder; cap at V and reserve 2 tail points if V>=6; actual bounds in each result",
        "r_squared": "1-SSE/SST; null for constant frequency or insufficient points; not a power-law test",
        "rmse": "sqrt(SSE/n) in log10(CF) space, not original CF space",
        "idf": "log10(N/DF); no smoothing; no additive constant",
        "term_selection": "Condition B: top 10, predefined vocabulary-rank quantiles, present domain/negation terms; fill to 20 if vocabulary permits",
        "versions": {"python": platform.python_version(), "nltk": version("nltk"), "regex": version("regex"),
                     "matplotlib": version("matplotlib")},
        "limitations": ["Descriptive OLS on dependent ordered counts does not establish a power-law distribution",
                        "Assignment A/B/C/D comparison: whitespace, HW1 punctuation handling, stopwords, Porter",
                        "HW1 preserves supported compounds and decimals but is not a biomedical entity recognizer",
                        "Rare terms and singleton ties may dominate full-range log regression",
                        "An experiment can contain fewer than 20 terms only for small test corpora"],
    }
    return {"schema_version": 1, "metadata": metadata, "conditions": results,
            "selected_terms": _select_terms(results["B"])}


def _write_csv(path: Path, rows: list[dict], fields: Sequence[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _plot_results(results: dict, output_dir: Path) -> None:
    """Create static report figures; imports are lazy and require no GUI."""
    import os
    os.environ.setdefault("MPLCONFIGDIR", str(Path(__file__).resolve().parents[1] / "tmp" / "matplotlib"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import MaxNLocator

    colors = {"A": "#355C9A", "B": "#16847D", "C": "#C87924", "D": "#9152A0"}
    comparison_key = "A=basic | B=punctuation | C=stopwords | D=Porter"
    condition_labels = {"A": "A: basic", "B": "B: punctuation", "C": "C: stopwords", "D": "D: Porter"}
    with plt.rc_context({"font.family": "DejaVu Sans", "font.size": 11,
                         "axes.spines.top": False, "axes.spines.right": False,
                         "figure.facecolor": "white", "axes.titleweight": "bold"}):
        rank_labels = {
            "A": "A: Basic tokenization + normalization",
            "B": "B: A + punctuation handling",
            "C": "C: B + stopword removal",
            "D": "D: C + Porter stemming",
        }
        fig, ax = plt.subplots(figsize=(11, 5), layout="constrained")
        for label, condition in results.items():
            freq = list(condition["cf"].values())
            ranks = list(range(1, len(freq) + 1))
            if not freq:
                continue
            ax.plot(ranks, freq, label=rank_labels[label], color=colors[label], linewidth=1.6)
        ax.set(title="Word frequency distributions by preprocessing",
               xlabel="Word frequency rank (linear scale)",
               ylabel="Collection frequency (CF; log scale)")
        ax.set_yscale("log", base=10)
        ax.grid(alpha=0.18)
        ax.legend(title="Cumulative preprocessing", loc="upper right", fontsize=10)
        fig.savefig(output_dir / "rank_frequency.png", dpi=180)
        plt.close(fig)

        fig, axes = plt.subplots(2, 2, figsize=(12, 9), layout="constrained", sharex=True, sharey=True)
        log_x, log_y = [], []
        residual_y = [0.0]
        residual_fig, residual_axes = plt.subplots(2, 2, figsize=(12, 9), layout="constrained", sharex=True, sharey=True)
        for (label, condition), ax, residual_ax in zip(results.items(), axes.flat, residual_axes.flat):
            freq = list(condition["cf"].values())
            x = [math.log10(rank) for rank in range(1, len(freq) + 1)]
            y = [math.log10(value) for value in freq]
            log_x.extend(x)
            log_y.extend(y)
            fit = condition["regression"]
            ax.scatter(x, y, s=5, alpha=0.5, color=colors[label], label="Observed terms", rasterized=True)
            if fit["slope"] is not None:
                predicted = [fit["intercept"] + fit["slope"] * value for value in x]
                log_y.extend(predicted)
                ax.plot(x, predicted, color="#333333", linewidth=1.5, label="Full-range OLS")
                residuals = [a - b for a, b in zip(y, predicted)]
                residual_y.extend(residuals)
                residual_ax.scatter(x, residuals, s=5, alpha=0.5, color=colors[label], rasterized=True)
                r2 = "undefined" if fit["r_squared"] is None else f"{fit['r_squared']:.4f}"
                ax.text(0.04, 0.06, f"b = {fit['zipf_exponent']:.3f}    R² = {r2}\nRMSE (log CF) = {fit['rmse']:.3f}",
                        transform=ax.transAxes, fontsize=10, bbox={"facecolor": "white", "alpha": 0.85, "edgecolor": "none"})
            for name in ("head", "middle"):
                end = condition["segments"][name]["rank_end"]
                if end and end < len(freq):
                    residual_ax.axvline(math.log10(end), color="#777777", alpha=0.45, linestyle=":")
            ax.set(title=f"{condition_labels[label]}  |  V = {len(freq):,}", xlabel="log(rank)", ylabel="log(CF)")
            residual_ax.set(title=condition_labels[label], xlabel="log(rank)", ylabel="Observed - fitted log(CF)")
            for panel in (ax, residual_ax):
                panel.set_box_aspect(2 / 3)
                # Shared axes normally hide inner labels; show them on every panel.
                panel.tick_params(axis="both", labelbottom=True, labelleft=True)
            residual_ax.axhline(0, color="#333333", linewidth=1)
            ax.grid(alpha=0.18)
            residual_ax.grid(alpha=0.18)
            ax.legend(loc="upper right", fontsize=9)
        # Both views use the same rank bounds. Their y bounds remain separate:
        # include all observations/fits for regression, all residuals AND zero for
        # residuals. Padding also handles a constant range without singular axes.
        for values, setters in (
            (log_x, (axes[0, 0].set_xlim, residual_axes[0, 0].set_xlim)),
            (log_y, (axes[0, 0].set_ylim,)),
            (residual_y, (residual_axes[0, 0].set_ylim,)),
        ):
            if values:
                lower, upper = min(values), max(values)
                padding = 0.05 * (upper - lower or 1.0)
                for set_limits in setters:
                    set_limits(lower - padding, upper + padding)
        # Shared axes share locators within a figure. Each figure needs its own
        # locator instance, with identical settings and bounds for identical x ticks.
        for grid in (axes, residual_axes):
            grid[0, 0].xaxis.set_major_locator(MaxNLocator(nbins=6, steps=[1, 2, 5, 10]))
        axes[0, 0].yaxis.set_major_locator(MaxNLocator(nbins=7, steps=[1, 2, 5, 10]))
        residual_axes[0, 0].yaxis.set_major_locator(MaxNLocator(nbins=6, steps=[1, 2, 5, 10]))
        fig.suptitle(f"Zipf (log): {comparison_key}", fontsize=15)
        fig.savefig(output_dir / "log_log.png", dpi=180)
        residual_fig.suptitle(f"Residuals: {comparison_key}\nDotted lines: rank segment boundaries", fontsize=13)
        residual_fig.savefig(output_dir / "residuals.png", dpi=180)
        plt.close(fig)
        plt.close(residual_fig)

        fig, axes = plt.subplots(1, 3, figsize=(14, 4.8), layout="constrained")
        labels = list(results)
        for ax, key, title in zip(axes, ("tokens", "unique_terms", "postings_entries"),
                                 ("Total token occurrences", "Vocabulary size", "Total postings entries (sum DF)")):
            values = [results[label][key] for label in labels]
            bars = ax.bar(labels, values, color=[colors[label] for label in labels], width=0.6)
            ax.bar_label(bars, labels=[f"{value:,}" for value in values], padding=4, fontsize=10)
            ax.set(title=title, xlabel="A/B/C/D cumulative", ylim=(0, max(values, default=0) * 1.17 or 1))
            ax.grid(axis="y", alpha=0.18)
            ax.set_axisbelow(True)
        fig.suptitle(f"Counts and index size proxies: {comparison_key}", fontsize=14)
        fig.savefig(output_dir / "preprocessing_comparison.png", dpi=180)
        plt.close(fig)


def run_experiment(documents: dict[str, Document], output_dir: str | Path, corpus_sha256: str = "") -> dict:
    """Write deterministic tables, plots and JSON for the supplied snapshot."""
    summary = analyze_documents(documents)
    summary["metadata"]["corpus_sha256"] = corpus_sha256
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    fields = ("rank", "term", "cf", "df", "idf")
    regression_rows = []
    comparison_rows = []
    artifacts = {"summary": "summary.json", "regression": "regression.csv", "comparison": "preprocessing_comparison.csv",
                 "cf_df": "cf_df_comparison.csv", "idf": "idf_terms.csv", "terms": {}, "top50": {}, "per_document": {},
                 "figures": ["rank_frequency.png", "log_log.png", "residuals.png", "preprocessing_comparison.png"]}
    for label, condition in summary["conditions"].items():
        artifacts["terms"][label] = f"terms_{label}.csv"
        artifacts["top50"][label] = f"top50_{label}.csv"
        artifacts["per_document"][label] = f"documents_{label}.csv"
        _write_csv(directory / artifacts["terms"][label], _term_rows(condition), fields)
        _write_csv(directory / artifacts["top50"][label], condition["top50"], fields)
        _write_csv(directory / artifacts["per_document"][label], condition["per_document"], ("pmid", "tokens", "unique_terms"))
        for segment, metrics in {"full": condition["regression"], **condition["segments"]}.items():
            regression_rows.append({"condition": label, "segment": segment, **metrics})
        comparison_rows.append({"condition": label, **{key: condition[key] for key in (
            "documents", "tokens", "unique_terms", "average_tokens_per_document", "singleton_terms", "singleton_ratio",
            "singleton_token_share", "top10_token_share", "postings_entries")}, **condition["regression"]})
    _write_csv(directory / "regression.csv", regression_rows, tuple(regression_rows[0]))
    _write_csv(directory / "preprocessing_comparison.csv", comparison_rows, tuple(comparison_rows[0]))
    _write_csv(directory / "cf_df_comparison.csv", summary["selected_terms"], ("condition", "rank", "term", "cf", "df"))
    _write_csv(directory / "idf_terms.csv", summary["selected_terms"], ("condition", *fields))
    _plot_results(summary["conditions"], directory)
    summary["artifacts"] = artifacts
    (directory / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return summary
