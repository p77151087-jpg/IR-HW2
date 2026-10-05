"""Hand-checkable tests: synthetic input is never a formal PubMed experiment."""
import csv
import hashlib
import json
import math
from pathlib import Path

import pytest

from ir_hw1 import preprocessing as hw1_preprocessing
from ir_hw1.models import Document, TextBlock
from ir_hw2 import analysis as analysis_module
from ir_hw2.analysis import (
    STOPWORDS_PATH, abstract_text, analyze_documents, baseline_tokenizer_spec, inverse_document_frequency,
    linear_regression, run_experiment, stopword_spec, tokenize,
)


def document(pmid: str, text: str) -> Document:
    return Document("PMID" + pmid, "TITLE MUST NOT ENTER COUNTS", [
        TextBlock("title", "title", "", "EXCLUDED_TITLE"),
        TextBlock("heading", "heading", "", "EXCLUDED_HEADING"),
        TextBlock("body", "body", "", "EXCLUDED_FULLTEXT"),
        TextBlock("abstract", "abstract", "EXCLUDED_SECTION_LABEL", text),
    ], pmid=pmid, content_scope="abstract")


def small_corpus() -> dict[str, Document]:
    return {"one": document("1", "The cats, cats run."), "two": document("2", "Cats run run.")}


def test_default_a_is_basic_tokenization_with_hw1_normalization():
    text = "CAFÉ cafe\u0301, Straße patient’s GLP‐1 GLP‑1 —"
    expected = ["café", "café,", "strasse", "patient's", "glp-1", "glp-1", "—"]
    assert tokenize(text) == tokenize(text, "A") == expected
    assert tokenize(text) == [hw1_preprocessing.normalize(term) for term in text.split()]
    assert tokenize("IL6 GLP-1 1.5 cats, β-cells — +", "B") == ["il6", "glp-1", "1.5", "cats", "β-cells"]
    assert "il" not in tokenize("IL6", "B")


def test_assignment_abcd_example_has_all_four_processing_conditions():
    text = "The patients GLP-1 improved 3.5 mg."
    assert tokenize(text, "A") == ["the", "patients", "glp-1", "improved", "3.5", "mg."]
    assert tokenize(text, "B") == ["the", "patients", "glp-1", "improved", "3.5", "mg"]
    assert tokenize(text, "C") == ["patients", "glp-1", "improved", "3.5", "mg"]
    assert tokenize(text, "D") == ["patient", "glp-1", "improv", "3.5", "mg"]
    result = analyze_documents({"one": document("1", text)})
    assert list(result["conditions"]) == ["A", "B", "C", "D"]
    assert [r["tokens"] for r in result["conditions"].values()] == [6, 6, 5, 5]
    assert result["metadata"]["reference_condition"] is None


@pytest.mark.parametrize("text,expected", [
    ("GLP-1, IL6 3.5 β-cells", ["glp-1", "il6", "3.5", "β-cells"]),
    ("patient’s patient's GLP‐1 GLP‑1", ["patient's", "patient's", "glp-1", "glp-1"]),
    ("CAFÉ cafe\u0301 Straße Β β İ ß 中文", ["café", "café", "strasse", "β", "β", "i\u0307", "ss", "中文"]),
    ("p x β 5 the a", ["p", "x", "β", "5", "the", "a"]),
    ("'quoted' (GLP-1); can't + --- 3.5", ["quoted", "glp-1", "can't", "3.5"]),
])
def test_baseline_matches_hw1_token_by_token_and_preserves_biomedical_terms(text, expected):
    assert tokenize(text, "B") == expected
    assert tokenize(text, "B") == [token.term for token in hw1_preprocessing.tokenize(text)]


def test_hw1_baseline_stopwords_and_porter_are_strictly_cumulative():
    text = "The cats running drug-induced GLP-1 IL6 3.5 β-cells patient's p x no not without"
    expected_b = ["the", "cats", "running", "drug-induced", "glp-1", "il6", "3.5", "β-cells",
                  "patient's", "p", "x", "no", "not", "without"]
    expected_c = expected_b[1:]
    expected_d = ["cat", "run", "drug-induced", "glp-1", "il6", "3.5", "β-cells",
                  "patient's", "p", "x", "no", "not", "without"]
    assert tokenize(text, "B") == expected_b  # Includes stopwords and isolated letters.
    assert tokenize(text, "C") == expected_c
    assert tokenize(text, "D") == expected_d
    assert tokenize(text, "D") == [hw1_preprocessing.stem_term(term) for term in expected_c]


def test_baseline_tokenizer_contract_is_hashed_and_independent_of_analysis_version(monkeypatch):
    spec = baseline_tokenizer_spec()
    assert spec["implementation"] == "ir_hw1.preprocessing.tokenize"
    assert spec["version"] == hw1_preprocessing.TOKENIZER_VERSION
    assert spec["regex"] == hw1_preprocessing.TOKEN_RE.pattern
    assert spec["normalization"]["unicode_form"] == "NFC"
    assert spec["normalization"]["casefold"] is True
    assert spec["source_sha256"] == hashlib.sha256(Path(hw1_preprocessing.__file__).read_bytes()).hexdigest()
    assert not any(spec[key] for key in ("remove_stopwords", "stemming", "search_feature_expansion", "isolated_letter_filter"))
    assert "pipeline_version" not in spec and "log_base" not in spec
    monkeypatch.setattr(analysis_module, "PIPELINE_VERSION", "statistics-only-future-version")
    assert baseline_tokenizer_spec() == spec
    assert json.loads(json.dumps(spec)) == spec


def test_stopwords_are_fixed_hashed_and_negations_survive():
    assert tokenize("the no not without and", "C") == ["no", "not", "without"]
    spec = stopword_spec()
    assert spec["version"] == "hw2-function-words-v1"
    assert spec["sha256"] == hashlib.sha256(STOPWORDS_PATH.read_bytes()).hexdigest()
    assert spec["count"] == len(set(spec["words"]))


def test_porter_uses_disclosed_nltk_martin_extensions():
    assert tokenize("The cats running studies βeta IL6", "D") == ["cat", "run", "studi", "βeta", "il6"]
    metadata = analyze_documents(small_corpus())["metadata"]
    assert metadata["stemming"]["mode"] == "MARTIN_EXTENSIONS"
    assert metadata["stemming"]["self_implemented"] is False


def test_hand_counted_cf_df_and_idf_across_conditions():
    conditions = analyze_documents(small_corpus())["conditions"]
    assert conditions["A"]["cf"] == {"cats": 2, "run.": 2, "cats,": 1, "run": 1, "the": 1}
    assert conditions["A"]["unique_terms"] == 5
    assert conditions["B"]["cf"] == {"cats": 3, "run": 3, "the": 1}
    assert conditions["B"]["df"] == {"cats": 2, "run": 2, "the": 1}
    assert conditions["B"]["tokens"] == 7
    assert conditions["B"]["average_tokens_per_document"] == 3.5
    assert conditions["C"]["cf"] == {"cats": 3, "run": 3}
    assert conditions["D"]["cf"] == {"cat": 3, "run": 3}
    the = next(row for row in conditions["B"]["top50"] if row["term"] == "the")
    cats = next(row for row in conditions["B"]["top50"] if row["term"] == "cats")
    assert the["idf"] == pytest.approx(math.log10(2))
    assert cats["idf"] == 0  # In particular, NOT the search formula's +1.
    assert conditions["B"]["postings_entries"] == 5
    for result in conditions.values():
        assert sum(result["cf"].values()) == result["tokens"]
        assert sum(row["tokens"] for row in result["per_document"]) == result["tokens"]
        assert all(1 <= result["df"][term] <= min(cf, result["documents"]) for term, cf in result["cf"].items())


def test_df_counts_each_document_once_but_cf_counts_each_occurrence():
    result = analyze_documents({"one": document("1", "glucose glucose glucose"),
                                "two": document("2", "insulin")})["conditions"]["B"]
    assert result["cf"]["glucose"] == 3
    assert result["df"]["glucose"] == 1


def test_compound_and_decimal_hand_counts_do_not_add_search_features():
    result = analyze_documents({"one": document("1", "GLP-1, IL6 3.5 β-cells GLP‑1"),
                                "two": document("2", "glp-1 IL6 3.5")})
    baseline = result["conditions"]["B"]
    assert baseline["cf"] == {"glp-1": 3, "3.5": 2, "il6": 2, "β-cells": 1}
    assert baseline["df"] == {"glp-1": 2, "3.5": 2, "il6": 2, "β-cells": 1}
    assert baseline["tokens"] == 8
    assert baseline["unique_terms"] == 4
    assert not {"glp", "1", "il", "6", "3", "5", "β", "cells"} & baseline["cf"].keys()
    assert result["conditions"]["C"]["cf"] == baseline["cf"]
    assert result["conditions"]["D"]["cf"] == baseline["cf"]


def test_title_heading_section_and_fulltext_never_enter_analysis():
    doc = document("1", "target")
    assert abstract_text(doc) == "target"
    result = analyze_documents({"one": doc})
    assert result["conditions"]["B"]["cf"] == {"target": 1}


def test_multiple_abstract_blocks_share_one_df_document():
    doc = document("1", "target")
    doc.blocks.append(TextBlock("a2", "abstract", "second label", "target"))
    result = analyze_documents({"one": doc})["conditions"]["B"]
    assert result["cf"] == {"target": 2}
    assert result["df"] == {"target": 1}


def test_empty_after_stopwords_retains_original_document_population():
    result = analyze_documents({"one": document("1", "the"), "two": document("2", "cats")})
    assert result["conditions"]["C"]["documents"] == 2
    assert result["conditions"]["C"]["top50"][0]["idf"] == pytest.approx(math.log10(2))
    empty = analyze_documents({"one": document("1", "the")})["conditions"]["D"]
    assert empty["tokens"] == empty["unique_terms"] == 0
    assert empty["regression"]["status"] == "insufficient_points"


def test_ties_have_ordinal_ranks_in_lexical_order():
    result = analyze_documents({"one": document("1", "zebra beta alpha")})
    assert [(row["rank"], row["term"]) for row in result["conditions"]["B"]["top50"]] == [
        (1, "alpha"), (2, "beta"), (3, "zebra")]


@pytest.mark.parametrize("corpus,match", [
    ({}, "empty document"),
    ({"one": document("1", " ")}, "empty abstract"),
    ({"one": document("", "text")}, "valid PMID"),
    ({"one": document("1", "a"), "two": document("1", "b")}, "Duplicate PMID"),
])
def test_invalid_inputs_fail_explicitly(corpus, match):
    with pytest.raises(ValueError, match=match):
        analyze_documents(corpus)


def test_unknown_condition_is_rejected():
    for label in ("E", "unknown"):
        with pytest.raises(ValueError, match="Unknown preprocessing"):
            tokenize("text", label)


@pytest.mark.parametrize("n,df", [(0, 1), (1, 0), (1, 2)])
def test_invalid_idf_population(n, df):
    with pytest.raises(ValueError):
        inverse_document_frequency(n, df)


@pytest.mark.parametrize("n,df,expected", [(1000, 100, 1), (100, 1, 2), (1000, 1000, 0)])
def test_idf_base10_matches_hand_calculated_powers_of_ten(n, df, expected):
    # N/DF = 10 -> 1; N/DF = 100 -> 2; DF=N -> 0, without smoothing.
    assert inverse_document_frequency(n, df) == expected


def test_exact_power_law_recovers_slope_intercept_and_log_rmse():
    fit = linear_regression([1, 2, 4, 8], [100, 50, 25, 12.5])
    assert fit["slope"] == pytest.approx(-1)
    assert fit["zipf_exponent"] == pytest.approx(1)
    assert fit["intercept"] == pytest.approx(2)  # log10(100)=2 at rank 1.
    assert fit["r_squared"] == pytest.approx(1)
    assert fit["rmse"] == pytest.approx(0, abs=1e-14)
    assert fit["log_base"] == 10
    assert fit["rmse_space"] == "log10(CF)"


def test_regression_on_decimal_powers_matches_hand_calculated_line():
    # x=(0,1,2), y=(2,1,0), so y=2-x exactly in base 10.
    fit = linear_regression([1, 10, 100], [100, 10, 1])
    assert fit["slope"] == -1
    assert fit["intercept"] == 2
    assert fit["zipf_exponent"] == 1
    assert fit["r_squared"] == 1
    assert fit["rmse"] == 0


def test_regression_rmse_is_calculated_in_log10_space_with_divisor_n():
    ranks, frequencies = [1, 2, 3, 4], [50, 22, 16, 2]
    fit = linear_regression(ranks, frequencies)
    errors = [math.log10(cf) - fit["intercept"] - fit["slope"] * math.log10(r)
              for r, cf in zip(ranks, frequencies)]
    assert fit["rmse"] == pytest.approx(math.sqrt(sum(e * e for e in errors) / 4))


@pytest.mark.parametrize("constant", [1, 3, 100])
def test_constant_frequency_has_undefined_r_squared(constant):
    fit = linear_regression([1, 2, 3], [constant] * 3)
    assert fit["r_squared"] is None
    assert fit["slope"] == fit["rmse"] == 0
    assert fit["status"] == "constant_frequency"


@pytest.mark.parametrize("ranks,cf", [([], []), ([1], [2])])
def test_empty_or_single_regression_does_not_invent_metrics(ranks, cf):
    fit = linear_regression(ranks, cf)
    assert fit["r_squared"] is fit["slope"] is fit["rmse"] is None
    assert fit["status"] == "insufficient_points"


@pytest.mark.parametrize("ranks,cf", [([1], [1, 2]), ([0, 1], [2, 1]), ([1, 2], [1, 0]),
                                        ([1, 2], [1, float("nan")])])
def test_invalid_regression_arguments(ranks, cf):
    with pytest.raises(ValueError):
        linear_regression(ranks, cf)


def test_repeated_rank_regression_is_undefined():
    assert linear_regression([1, 1], [1, 2])["status"] == "constant_rank"


def test_summary_and_source_hash_are_stable_across_mapping_order():
    corpus = small_corpus()
    first = analyze_documents(corpus)
    assert analyze_documents(dict(reversed(list(corpus.items())))) == first
    corpus["one"].title = "A different title still excluded"
    assert analyze_documents(corpus) == first
    corpus["one"].blocks[-1].text += " altered"
    assert analyze_documents(corpus)["metadata"]["source_text_sha256"] != first["metadata"]["source_text_sha256"]


def test_analysis_records_base10_for_all_conditions_and_segments():
    corpus = {str(i): document(str(i), "common") for i in range(1, 11)}
    corpus["1"].blocks[-1].text += " rare"
    summary = analyze_documents(corpus)
    assert summary["metadata"]["pipeline_version"] == "hw2-hw1-four-conditions-v5-log10"
    assert summary["metadata"]["baseline_tokenizer"] == baseline_tokenizer_spec()
    assert summary["metadata"]["primary_comparison"] == ["A", "B", "C", "D"]
    assert summary["metadata"]["reference_condition"] is None
    assert list(summary["conditions"]) == ["A", "B", "C", "D"]
    assert all(row["condition"] == "B" for row in summary["selected_terms"])
    assert summary["metadata"]["log_base"] == 10
    assert summary["metadata"]["idf"].startswith("log10(N/DF)")
    for condition in summary["conditions"].values():
        rows = {row["term"]: row for row in condition["top50"]}
        assert rows["rare"]["idf"] == 1  # Appears in 1 of 10 documents.
        assert rows["common"]["idf"] == 0  # Appears in all 10 documents.
        for regression in [condition["regression"], *condition["segments"].values()]:
            assert regression["log_base"] == 10
            assert regression["rmse_space"] == "log10(CF)"


def test_segment_boundaries_are_disjoint_complete_and_minimum_size_exposed():
    # Exactly 1000 terms: standard 1%, next 9%, remaining 90% without adjustment.
    tokens = " ".join(f"word{i}" for i in range(1000))
    result = analyze_documents({"one": document("1", tokens)})["conditions"]["B"]
    assert [(s["rank_start"], s["rank_end"], s["points"]) for s in result["segments"].values()] == [
        (1, 10, 10), (11, 100, 90), (101, 1000, 900)]
    assert all(s["r_squared"] is None for s in result["segments"].values())
    assert len(analyze_documents({"one": document("1", tokens)})["selected_terms"]) >= 20


def test_run_experiment_exports_reloadable_tables_figures_and_config(tmp_path: Path):
    summary = run_experiment(small_corpus(), tmp_path, corpus_sha256="synthetic-test-only")
    assert json.loads((tmp_path / "summary.json").read_text(encoding="utf-8")) == summary
    assert summary["metadata"]["corpus_sha256"] == "synthetic-test-only"
    for condition in "ABCD":
        with (tmp_path / f"terms_{condition}.csv").open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        assert sum(int(row["cf"]) for row in rows) == summary["conditions"][condition]["tokens"]
        assert (tmp_path / f"top50_{condition}.csv").is_file()
    assert (tmp_path / "regression.csv").read_text(encoding="utf-8-sig").count("\n") == 17
    assert len(list(tmp_path.iterdir())) == 21
    assert len(list(tmp_path.glob("*.csv"))) == 16
    for image in summary["artifacts"]["figures"]:
        assert (tmp_path / image).read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
