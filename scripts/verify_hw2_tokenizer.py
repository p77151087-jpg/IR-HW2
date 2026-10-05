"""Offline verification of the fixed HW1 tokenizer experiment and its artifacts.

Run from any working directory with the HW2 environment::

    .venv-hw2/Scripts/python.exe -X utf8 scripts/verify_hw2_tokenizer.py

The oracle obtains A from whitespace tokens plus HW1 normalize, B from HW1
Token.term, C from the checked-in stoplist, and D from HW1 stem_term.
Counters, CSV checks and numpy least-squares are independent
of the analysis statistics implementation. Only the reproduction step calls
run_experiment; formal artifacts and the corpus are never written.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "tmp/matplotlib"))
os.environ["IR_HW1_OFFLINE_DEMO"] = "1"

import numpy as np

from ir_hw1 import preprocessing as hw1
from ir_hw2 import analysis
from ir_hw2.corpus import DEFAULT_SNAPSHOT, load_corpus

EXPECTED_HW1_SHA256 = "f7108e87d1c19c43e012836adcb6d8b429e4d06c5cdc2bead4a06f71f04919c2"
EXPECTED_CORPUS_SHA256 = "9738b68d03a6e39bed010803aa878cfdc66e0bbcaf005e8ee83d3bcfeb7b2631"
EXPECTED_PIPELINE = "hw2-hw1-four-conditions-v5-log10"
LABELS = ("A", "B", "C", "D")
HISTORY_MAPPING = {label: label for label in LABELS}
METRICS = ("slope", "intercept", "zipf_exponent", "r_squared", "rmse")
OUTPUTS = sorted(
    [f"{kind}_{label}.csv" for label in LABELS for kind in ("terms", "top50", "documents")]
    + ["summary.json", "regression.csv", "preprocessing_comparison.csv", "cf_df_comparison.csv", "idf_terms.csv"]
    + ["rank_frequency.png", "log_log.png", "residuals.png", "preprocessing_comparison.png"]
)


class VerificationError(AssertionError):
    """A failed independent check; CLI reports a nonzero exit status."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise VerificationError(message)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inventory(directory: Path) -> dict[str, str]:
    return {p.relative_to(directory).as_posix(): sha256(p) for p in sorted(directory.rglob("*")) if p.is_file()}


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def close(actual, expected, context: str) -> float:
    actual = float(actual)
    require(math.isfinite(actual) and math.isclose(actual, expected, rel_tol=1e-11, abs_tol=1e-12),
            f"{context}: actual={actual!r}, expected={expected!r}")
    return abs(actual - expected)


def compare_fields(actual: dict, expected: dict, context: str) -> None:
    """Compare named expected fields, preserving exact integer/string contracts."""
    for key, value in expected.items():
        require(key in actual, f"{context}: missing {key}")
        observed = actual[key]
        if isinstance(value, float):
            close(observed, value, f"{context}.{key}")
        elif isinstance(value, int):
            require(str(observed) == str(value), f"{context}.{key}: {observed!r} != {value!r}")
        else:
            require(observed == value, f"{context}.{key}: {observed!r} != {value!r}")


def independent_ols(cf: list[int], start: int, end: int) -> dict:
    """Fit the original ordinal rank interval with numpy.linalg.lstsq, base 10.

    Formal segments contain variable frequencies and >=2 points. Assert these
    conditions explicitly rather than copying analysis's degenerate-fit branches.
    """
    ranks = np.arange(start, end + 1, dtype=np.float64)
    frequencies = np.asarray(cf[start - 1:end], dtype=np.float64)
    require(len(ranks) >= 2 and np.ptp(frequencies) > 0, "Formal OLS segment is degenerate")
    x, y = np.log10(ranks), np.log10(frequencies)
    design = np.column_stack((np.ones(len(x)), x))
    coefficients, _, rank, _ = np.linalg.lstsq(design, y, rcond=None)
    require(int(rank) == 2, "OLS design matrix is rank deficient")
    intercept, slope = coefficients
    residuals = y - design @ coefficients
    sse = float(residuals @ residuals)
    centered = y - np.mean(y)
    sst = float(centered @ centered)
    return {"points": len(x), "rank_start": start, "rank_end": end,
            "slope": float(slope), "intercept": float(intercept), "zipf_exponent": float(-slope),
            "r_squared": 1 - sse / sst, "rmse": math.sqrt(sse / len(x)),
            "log_base": 10, "rmse_space": "log10(CF)", "status": "ok"}


def count_oracle(documents: dict, stored: dict, stopwords: frozenset[str]) -> dict:
    """Check every ordered sequence, then accumulate counts without HW2 helpers."""
    aggregates = {label: {"cf": Counter(), "df": Counter(), "per_document": [],
                          "sequence_hasher": hashlib.sha256(), "sequence_documents": 0} for label in LABELS}
    texts = []
    for doc in sorted(documents.values(), key=lambda document: int(document.pmid)):
        # Independently establish exactly how abstract blocks are joined.
        text = "\n".join(block.text for block in doc.blocks if block.kind == "abstract")
        require(analysis.abstract_text(doc) == text, f"Abstract body mismatch: {doc.pmid}")
        texts.append([doc.pmid, text])
        b = [token.term for token in hw1.tokenize(text)]
        c = [term for term in b if term not in stopwords]
        ordered = {"A": [hw1.normalize(term) for term in text.split()], "B": b,
                   "C": c, "D": [hw1.stem_term(term) for term in c]}
        require(analysis.tokenize(text) == ordered["A"], f"Default tokenizer must equal whitespace-normalized A: PMID {doc.pmid}")
        for label, terms in ordered.items():
            require(analysis.tokenize(text, label) == terms, f"Ordered {label} sequence mismatch: PMID {doc.pmid}")
            aggregate = aggregates[label]
            local_cf = Counter(terms)
            local_df = set(terms)
            require(sum(local_cf.values()) == len(terms), f"Per-document CF mismatch: {doc.pmid}/{label}")
            aggregate["cf"].update(local_cf)
            aggregate["df"].update(local_df)
            aggregate["per_document"].append({"pmid": doc.pmid, "tokens": len(terms), "unique_terms": len(local_df)})
            payload = json.dumps([doc.pmid, terms], ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
            aggregate["sequence_hasher"].update(payload)
            aggregate["sequence_documents"] += 1
    text_sha = hashlib.sha256(json.dumps(texts, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()
    require(text_sha == stored["metadata"]["source_text_sha256"], "Abstract source fingerprint changed")
    require([pmid for pmid, _ in texts] == stored["metadata"]["pmids"], "Stored experiment PMID order changed")
    for label, aggregate in aggregates.items():
        aggregate["sequence_sha256"] = aggregate.pop("sequence_hasher").hexdigest()
        aggregate["source_text_sha256"] = text_sha
    return aggregates


def verify_conditions(aggregates: dict, stored: dict, experiment: Path, count: int) -> tuple[dict, list]:
    comparisons = read_csv(experiment / "preprocessing_comparison.csv")
    require([r["condition"] for r in comparisons] == list(LABELS), "Comparison CSV condition order differs")
    regression_rows = read_csv(experiment / "regression.csv")
    require(len(regression_rows) == 16, "Expected 16 full/head/middle/tail regression fits")
    regression_lookup = {(r["condition"], r["segment"]): r for r in regression_rows}
    require(len(regression_lookup) == 16, "Duplicate regression CSV rows")
    condition_evidence, fits = {}, []
    for label, aggregate in aggregates.items():
        cf, df = aggregate["cf"], aggregate["df"]
        terms = sorted(cf, key=lambda term: (-cf[term], term))
        freq = [cf[term] for term in terms]
        tokens, vocabulary, postings = sum(freq), len(terms), sum(df.values())
        current = stored["conditions"][label]
        require(dict(cf) == current["cf"] and dict(df) == current["df"], f"{label}: independently counted CF/DF differs")
        require(list(current["cf"]) == terms and list(current["df"]) == terms, f"{label}: stable ordinal rank/tie order differs")
        require(all(1 <= df[t] <= count and df[t] <= cf[t] for t in terms), f"{label}: CF/DF bounds violated")
        require(sum(r["tokens"] for r in aggregate["per_document"]) == tokens, f"{label}: sum of per-document CF differs")
        require(sum(r["unique_terms"] for r in aggregate["per_document"]) == postings, f"{label}: sum of per-document DF differs")
        require(aggregate["per_document"] == current["per_document"], f"{label}: JSON per-document counts differ")
        per_document = read_csv(experiment / f"documents_{label}.csv")
        require(len(per_document) == count, f"{label}: document CSV row count differs")
        for actual, expected in zip(per_document, aggregate["per_document"]):
            compare_fields(actual, expected, f"{label}.document.{expected['pmid']}")
        rows = [{"rank": rank, "term": term, "cf": cf[term], "df": df[term], "idf": math.log10(count / df[term])}
                for rank, term in enumerate(terms, 1)]
        for filename, expected_rows in ((f"terms_{label}.csv", rows), (f"top50_{label}.csv", rows[:50])):
            csv_rows = read_csv(experiment / filename)
            require(len(csv_rows) == len(expected_rows), f"{filename}: row count differs")
            for actual, expected in zip(csv_rows, expected_rows):
                compare_fields(actual, expected, f"{filename}.rank{expected['rank']}")
        require(len(current["top50"]) == 50, f"{label}: expected 50 JSON top terms")
        for actual, expected in zip(current["top50"], rows[:50]):
            compare_fields(actual, expected, f"{label}.JSON.top50")
        singletons = sum(f == 1 for f in freq)
        metrics = {"documents": count, "tokens": tokens, "unique_terms": vocabulary,
                   "average_tokens_per_document": tokens / count, "postings_entries": postings,
                   "singleton_terms": singletons, "singleton_ratio": singletons / vocabulary,
                   "singleton_token_share": singletons / tokens, "top10_token_share": sum(freq[:10]) / tokens}
        compare_fields(current, metrics, f"{label}.summary")
        comparison = next(r for r in comparisons if r["condition"] == label)
        compare_fields(comparison, metrics, f"{label}.comparison.csv")
        # These fixed formal corpora have >1,000 types: percentage boundaries
        # are determined directly, without calling analysis._segments.
        require(vocabulary >= 1000, "This formal verifier expects a vocabulary of at least 1,000 terms")
        head_end, middle_end = vocabulary // 100, vocabulary // 10
        bounds = {"full": (1, vocabulary), "head": (1, head_end),
                  "middle": (head_end + 1, middle_end), "tail": (middle_end + 1, vocabulary)}
        for segment, (start, end) in bounds.items():
            fit = independent_ols(freq, start, end)
            observed = current["regression"] if segment == "full" else current["segments"][segment]
            compare_fields(observed, fit, f"{label}.{segment}.JSON.OLS")
            compare_fields(regression_lookup[(label, segment)], fit, f"{label}.{segment}.CSV.OLS")
            if segment == "full":
                compare_fields(comparison, fit, f"{label}.comparison.csv.OLS")
            errors = {key: abs(float(observed[key]) - fit[key]) for key in METRICS}
            fits.append({"condition": label, "segment": segment, **fit, "max_absolute_error": max(errors.values()),
                         "absolute_errors": errors})
        condition_evidence[label] = {**metrics, "verified_ordered_documents": aggregate["sequence_documents"],
                                     "sequence_sha256": aggregate["sequence_sha256"], "sum_cf": tokens, "sum_df": postings,
                                     "terms_csv_rows_checked": vocabulary, "top50_rows_checked": 50,
                                     "per_document_rows_checked": count, "all_cf_df_bounds_valid": True,
                                     "counts_equal_stored_json_and_csv": True}
    return condition_evidence, fits


def verify_selected_terms(stored: dict, aggregates: dict, experiment: Path, count: int) -> dict:
    selected = stored["selected_terms"]
    require(len(selected) >= 20, "Need at least 20 selected CF/DF comparison terms")
    require(len({r["term"] for r in selected}) == len(selected), "Selected terms are not unique")
    ranks = {term: rank for rank, term in enumerate(sorted(aggregates["B"]["cf"], key=lambda t: (-aggregates["B"]["cf"][t], t)), 1)}
    cf_rows, idf_rows = read_csv(experiment / "cf_df_comparison.csv"), read_csv(experiment / "idf_terms.csv")
    require(len(cf_rows) == len(idf_rows) == len(selected), "Selected table lengths differ")
    max_error = 0.0
    for row, cf_row, idf_row in zip(selected, cf_rows, idf_rows):
        term = row["term"]
        require(term in ranks, f"Selected term is OOV: {term}")
        df, cf = aggregates["B"]["df"][term], aggregates["B"]["cf"][term]
        expected = {"condition": "B", "rank": ranks[term], "term": term, "cf": cf, "df": df}
        compare_fields(cf_row, expected, f"selected CF/DF: {term}")
        expected["idf"] = math.log10(count / df)
        compare_fields(row, expected, f"selected JSON IDF: {term}")
        compare_fields(idf_row, expected, f"selected CSV IDF: {term}")
        max_error = max(max_error, abs(float(idf_row["idf"]) - expected["idf"]))
    return {"condition": "B", "cf_df_terms_checked": len(selected), "idf_terms_checked": len(idf_rows),
            "formula": "log10(N/DF)", "max_absolute_error": max_error, "no_smoothing": True}


def history_comparison(stored: dict, history: Path) -> dict:
    old = read_json(history / "summary.json")
    require(old["metadata"]["pipeline_version"] == "hw2-hw1-tokenizer-v3-log10", "Expected archived four-condition HW1 tokenizer pipeline")
    require(old["metadata"]["corpus_sha256"] == stored["metadata"]["corpus_sha256"], "Historical corpus differs; comparison would be confounded")
    require(old["metadata"]["source_text_sha256"] == stored["metadata"]["source_text_sha256"], "Historical abstract text differs")
    result = {"path": str(history), "pipeline_version": old["metadata"]["pipeline_version"],
              "summary_sha256": sha256(history / "summary.json"), "same_corpus_sha256": True,
              "mapping_current_to_previous": HISTORY_MAPPING,
              "interpretation": "Restored four-condition assignment: current A/B/C/D equal archived same-named A/B/C/D, including the whitespace-normalized A condition. All four are primary conditions; no condition is designated reference-only.",
              "conditions": {}}
    for label, previous_label in HISTORY_MAPPING.items():
        before_condition, after_condition = old["conditions"][previous_label], stored["conditions"][label]
        require(before_condition == after_condition, f"Mapped history changed: current {label} != archived {previous_label}")
        result["conditions"][label] = {"previous_condition": previous_label, "all_condition_data_equal": True,
                                       "cf_equal": True, "df_equal": True, "per_document_equal": True}
        for key in ("documents", "tokens", "unique_terms", "postings_entries"):
            before, after = before_condition[key], after_condition[key]
            result["conditions"][label][key] = {"previous": before, "current": after, "delta": after - before}
        for key in METRICS:
            before, after = before_condition["regression"][key], after_condition["regression"][key]
            result["conditions"][label][key] = {"previous": before, "current": after, "delta": after - before}
    require(old["selected_terms"] == stored["selected_terms"], "Selected B terms differ from the archived four-condition experiment")
    result["selected_terms_equal_after_mapping"] = True
    return result


def verify(args: argparse.Namespace) -> dict:
    snapshot, experiment, reproduce = args.snapshot.resolve(), args.experiment.resolve(), args.reproduce_dir.resolve()
    require(reproduce.is_relative_to((ROOT / "tmp").resolve()), "Reproduction output must be inside the HW2 tmp directory")
    require(not reproduce.is_relative_to(snapshot) and not reproduce.is_relative_to(experiment), "Reproduction may not overwrite inputs")
    require(experiment.is_dir(), f"Experiment does not exist: {experiment}")
    snapshot_before, formal_before = inventory(snapshot), inventory(experiment)
    require(sorted(formal_before) == OUTPUTS, "Formal experiment must contain exactly the expected 21 artifacts")
    source_hash = sha256(ROOT / "ir_hw1/preprocessing.py")
    require(source_hash == EXPECTED_HW1_SHA256, "HW1 preprocessing source changed from the original baseline")
    manifest = read_json(snapshot / "snapshot.json")
    require(manifest["sha256"] == args.expected_corpus_sha256, "Snapshot is not the expected fixed corpus")
    documents = load_corpus(snapshot)
    require(len(documents) == args.expected_documents, f"Expected {args.expected_documents} documents, got {len(documents)}")
    stored = read_json(experiment / "summary.json")
    metadata = stored["metadata"]
    require(metadata["pipeline_version"] == analysis.PIPELINE_VERSION == EXPECTED_PIPELINE, "Unexpected analysis pipeline version")
    require(metadata["corpus_sha256"] == manifest["sha256"], "Experiment/corpus fingerprint mismatch")
    require(metadata["baseline_tokenizer"]["source_sha256"] == source_hash, "Stored baseline source fingerprint mismatch")
    require(metadata["analysis_code_sha256"] == sha256(Path(analysis.__file__)), "Formal experiment was built with different analysis code")
    require(list(stored["conditions"]) == list(LABELS) and analysis.CONDITIONS == LABELS, "Exactly four conditions A/B/C/D are required")
    require(metadata["primary_comparison"] == list(LABELS) and metadata["reference_condition"] is None, "Primary/reference condition contract differs")
    require(metadata["log_base"] == 10, "Experiment must use base 10")
    stopwords_file = ROOT / "resources/hw2_stopwords.json"
    stopword_data = read_json(stopwords_file)
    require(metadata["stopwords"]["sha256"] == sha256(stopwords_file), "Stopword resource changed")
    stopwords = frozenset(stopword_data["words"])
    require(len(stopwords) == len(stopword_data["words"]), "Stopword resource has duplicates")
    print(f"已驗證固定語料與版本：{len(documents):,} 篇；逐篇核對四組 A／B／C／D 完整詞序。", flush=True)
    aggregates = count_oracle(documents, stored, stopwords)
    condition_evidence, fits = verify_conditions(aggregates, stored, experiment, len(documents))
    selected = verify_selected_terms(stored, aggregates, experiment, len(documents))
    probe = "IL6 GLP-1 GLP‑1RA 3.5 β-cells TNF-α can't Straße e\u0301"
    expected_probe = ["il6", "glp-1", "glp-1ra", "3.5", "β-cells", "tnf-α", "can't", "strasse", "é"]
    require([t.term for t in hw1.tokenize(probe)] == expected_probe, "HW1 edge-case probe changed")
    require(analysis.tokenize(probe, "B") == expected_probe, "HW2 introduced extra feature expansion/filtering")
    require(analysis.tokenize(probe) == [hw1.normalize(term) for term in probe.split()], "Default tokenizer must equal whitespace-normalized A")
    previous_pipeline = history_comparison(stored, args.history.resolve())
    print("CF／DF、全部 CSV、16 組獨立 OLS 與封存同名 A/B/C/D 已核對；正在重跑 21 個輸出檔。", flush=True)
    analysis.run_experiment(documents, reproduce, corpus_sha256=manifest["sha256"])
    repeated = inventory(reproduce)
    require(sorted(repeated) == OUTPUTS, "Reproduction must contain exactly the expected 21 artifacts")
    require(formal_before == repeated, "Reproduction SHA256 mismatch: " + ", ".join(n for n in OUTPUTS if formal_before[n] != repeated[n]))
    artifacts = [{"file": name, "sha256": formal_before[name], "bytes": (experiment / name).stat().st_size,
                  "byte_identical": (experiment / name).read_bytes() == (reproduce / name).read_bytes()} for name in OUTPUTS]
    require(all(a["byte_identical"] for a in artifacts), "Reproduced bytes differ")
    require(snapshot_before == inventory(snapshot), "Verifier changed the sealed snapshot")
    require(formal_before == inventory(experiment), "Verifier changed the formal experiment")
    return {"pipeline_version": metadata["pipeline_version"], "primary_comparison": list(LABELS), "reference_condition": None,
            "default_condition": "A",
            "baseline_tokenizer": metadata["baseline_tokenizer"],
            "source": {"method": "Direct source inspection plus independent runtime oracles", "hw1_preprocessing_sha256": source_hash,
                       "hw1_original_hash_unchanged": True, "analysis_code_sha256": metadata["analysis_code_sha256"],
                       "verifier_sha256": sha256(Path(__file__))},
            "corpus": {"path": str(snapshot), "documents": len(documents), "abstracts_sha256": manifest["sha256"],
                       "snapshot_json_sha256": snapshot_before["snapshot.json"], "source_text_sha256": aggregates["A"]["source_text_sha256"],
                       "all_snapshot_files_unchanged": True, "snapshot_files_checked": len(snapshot_before), "raw_hashes_verified_by_load_corpus": True},
            "stopwords": {"version": stopword_data["version"], "sha256": sha256(stopwords_file), "count": len(stopwords)},
            "conditions": condition_evidence, "selected_terms": selected,
            "no_search_expansion": {"verified_formal_documents": len(documents), "basis": "Every explicit B sequence equals raw HW1 Token.term sequence, with no added/dropped terms; default calls separately match whitespace-normalized A", "probe": probe, "expected_B": expected_probe},
            "independent_regression": {"method": "numpy.linalg.lstsq on [1, log10(rank)]", "numpy_version": np.__version__,
                                       "log_base": 10, "rmse_space": "log10(CF)", "fits_checked": len(fits),
                                       "tolerance": {"relative": 1e-11, "absolute": 1e-12},
                                       "maximum_absolute_error": max(f["max_absolute_error"] for f in fits), "fits": fits},
            "reproduction": {"path": str(reproduce), "formal_path": str(experiment), "artifacts_checked": len(artifacts),
                             "all_bytes_identical": True, "formal_files_unchanged": True, "artifacts": artifacts},
            "previous_pipeline_comparison": previous_pipeline}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument("--experiment", type=Path, default=ROOT / "reports/hw2/experiment")
    parser.add_argument("--history", type=Path, default=ROOT / "reports/hw2/history/hw1-four-conditions-20260930/experiment")
    parser.add_argument("--reproduce-dir", type=Path, default=ROOT / "tmp/hw2-four-conditions-final")
    parser.add_argument("--expected-documents", type=int, default=1000)
    parser.add_argument("--expected-corpus-sha256", default=EXPECTED_CORPUS_SHA256)
    args = parser.parse_args()
    started = time.perf_counter()
    report = {"schema_version": 1, "verified_at_utc": datetime.now(timezone.utc).isoformat(),
              "offline": True, "command": ".venv-hw2/Scripts/python.exe -X utf8 scripts/verify_hw2_tokenizer.py"}
    try:
        report.update(verify(args))
        report["passed"] = True
    except Exception as error:
        report.update(passed=False, error={"type": type(error).__name__, "message": str(error)})
    report["elapsed_seconds"] = round(time.perf_counter() - started, 3)
    path = ROOT / "reports/hw2/tokenizer_verification.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    print(json.dumps({"passed": report["passed"], "output": str(path), "elapsed_seconds": report["elapsed_seconds"],
                      **({"error": report["error"]} if not report["passed"] else {"documents": report["corpus"]["documents"], "reproduced_artifacts": len(OUTPUTS), "fits": 16})}, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
