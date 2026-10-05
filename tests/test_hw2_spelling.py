import itertools

import pytest

from ir_hw1.models import Document, TextBlock
from ir_hw2.spelling import _normalize_vocabulary, build_vocabulary, edit_distance, suggest_query


@pytest.mark.parametrize("left,right,expected", [
    ("", "", 0), ("", "abc", 3), ("abc", "", 3), ("kitten", "sitting", 3),
    ("insluin", "insulin", 2), ("glucose", "glucose", 0), ("cancerr", "cancer", 1),
    ("cat", "cut", 1), ("naïve", "naive", 1), ("你好", "您好", 1),
])
def test_hand_calculated_levenshtein(left, right, expected):
    assert edit_distance(left, right) == expected
    assert edit_distance(right, left) == expected
    for bound in range(4):
        assert edit_distance(left, right, bound) == min(expected, bound + 1)


def test_bounded_dp_agrees_with_unbounded_for_small_exhaustive_strings():
    words = [""] + ["".join(chars) for size in range(1, 4) for chars in itertools.product("ab", repeat=size)]
    for source in words:
        for target in words:
            expected = edit_distance(source, target)
            for bound in (0, 1, 2):
                assert edit_distance(source, target, bound) == min(expected, bound + 1)
    with pytest.raises(ValueError, match="non-negative"):
        edit_distance("a", "b", -1)


def test_vocabulary_uses_ordered_text_b_tokens_not_expanded_search_features():
    document = Document("PUBMED1", "Ignored metadata title", [
        TextBlock("title", "title", "", "Stored title"),
        TextBlock("a", "abstract", "Ignored section label", "IL6 GLP-1 glucose glucose."),
        TextBlock("body", "body", "", "treatment glucose"),
    ], pmid="1", back_blocks=[TextBlock("back", "reference", "", "ignoredreference")])
    abstract_vocab = build_vocabulary({"1": document}, abstracts_only=True)
    assert abstract_vocab == {"il6": 1, "glp-1": 1, "glucose": 2}
    assert not {"il", "6", "glp", "1"}.intersection(abstract_vocab)
    search_vocab = build_vocabulary([document])
    assert search_vocab["glucose"] == 3 and search_vocab["treatment"] == 1
    assert search_vocab["stored"] == 1
    assert "ignored" not in search_vocab and "ignoredreference" not in search_vocab


def test_correct_words_are_case_insensitive_and_never_replaced_by_frequent_words():
    result = suggest_query("Insulin insulin GLUCOSE", {"insulin": 1, "insulins": 10000, "Glucose": 2})
    assert result["suggested_query"] == result["original_query"]
    assert result["changes"] == []
    assert all(row["reason"] == "known_word" for row in result["protected_terms"])


def test_typo_suggestions_preserve_offsets_punctuation_spaces_and_case():
    query = "  (Glucsoe),\tinsluin!  cancerr?\nGLP-1"
    result = suggest_query(query, {"glucose": 40, "insulin": 30, "cancer": 50})
    assert result["original_query"] == query
    assert result["suggested_query"] == "  (Glucose),\tinsulin!  cancer?\nGLP-1"
    for change in result["changes"]:
        assert query[change["start"]:change["end"]] == change["original"]
    assert [row["candidates"][0]["distance"] for row in result["changes"]] == [2, 2, 1]
    assert "自行決定" in result["message"]


def test_distance_cf_lexical_ranking_and_top_three_are_deterministic():
    vocab = {"cart": 7, "cast": 7, "cats": 5, "catt": 9, "coats": 99999}
    result = suggest_query("catz", vocab)
    candidates = result["changes"][0]["candidates"]
    assert candidates == [
        {"term": "catt", "distance": 1, "cf": 9},
        {"term": "cats", "distance": 1, "cf": 5},
    ]
    result = suggest_query("catt", {"cart": 7, "cast": 7, "cats": 5, "cath": 5, "coat": 5000})
    assert [row["term"] for row in result["changes"][0]["candidates"]] == ["cart", "cast", "cath"]
    assert result == suggest_query("catt", dict(reversed(list({"cart": 7, "cast": 7, "cats": 5, "cath": 5, "coat": 5000}.items()))))


def test_distance_precedes_frequency_for_long_words():
    result = suggest_query("glucoss", {"glucose": 1, "glaucose": 999999})
    assert result["changes"][0]["suggestion"] == "glucose"
    assert result["changes"][0]["candidates"][0]["distance"] == 1


@pytest.mark.parametrize("query,reason", [
    ("GLP-1", "contains_digits"), ("GLP–1", "contains_digits"), ("BRCA1", "contains_digits"),
    ("p53", "contains_digits"), ("IL6", "contains_digits"), ("1.25", "contains_digits"),
    ("TNF", "short_word"), ("ABCD", "uppercase_abbreviation"), ("mTOR", "mixed_case"),
    ("eGFR", "mixed_case"), ("naïve", "non_ascii"), ("心臟", "non_ascii"),
    ("cancerr-treatment", "compound_term"), ("glucose's", "compound_term"),
    ("cat", "short_word"), ("a" * 65, "long_word"),
])
def test_biomedical_unknowns_protected(query, reason):
    result = suggest_query(query, {"glp": 10, "glucose": 5, "cancer": 5, "naive": 5})
    assert result["original_query"] == result["suggested_query"] == query
    assert result["changes"] == []
    assert result["protected_terms"][0]["reason"] == reason


def test_unknown_without_candidate_is_preserved_and_explained():
    result = suggest_query("qwertyuiop zzzz", {"insulin": 5, "glucose": 8})
    assert result["suggested_query"] == "qwertyuiop zzzz"
    assert len(result["unresolved_terms"]) == 2
    assert "沒有語料候選" in result["message"]
    assert suggest_query("", {})["suggested_query"] == ""


def test_short_words_one_edit_only_and_repeated_typo_spans():
    assert not suggest_query("abdc", {"abcd": 100})["changes"]
    result = suggest_query("cancerr, cancerr", {"cancer": 1})
    assert result["suggested_query"] == "cancer, cancer"
    assert len(result["changes"]) == 2
    assert result["changes"][1]["start"] == 9


@pytest.mark.parametrize("vocabulary", [{"x": 0}, {"x": -1}, {"x": 1.5}, {"x": True}, {1: 2}])
def test_invalid_cf_rejected(vocabulary):
    with pytest.raises(ValueError, match="positive integer"):
        suggest_query("text", vocabulary)


def test_vocabulary_matches_hw1_normalization_for_compounds_decimals_and_unicode():
    document = Document("D1", "", [TextBlock("a", "abstract", "", "GLP-1 GLP‑1 1.5 1.5 Patient’s patient's Café CAFE\u0301 Straße STRASSE")],
                        pmid="1", content_scope="abstract")
    vocabulary = build_vocabulary([document], abstracts_only=True)
    assert vocabulary == {"glp-1": 2, "1.5": 2, "patient's": 2, "café": 2, "strasse": 2}
    assert _normalize_vocabulary({"GLP‑1": 2, "glp-1": 3, "Patient’s": 1, "patient's": 2,
                                  "Café": 4, "CAFE\u0301": 5, "Straße": 6, "STRASSE": 7}) == {
        "glp-1": 5, "patient's": 3, "café": 9, "strasse": 13,
    }
    query = "  GLP‑1 1.5 Patient’s CAFE\u0301 Straße; insulinn"
    result = suggest_query(query, {**vocabulary, "insulin": 10})
    assert result["original_query"] == query
    assert result["suggested_query"] == "  GLP‑1 1.5 Patient’s CAFE\u0301 Straße; insulin"
    assert all(row["reason"] == "known_word" for row in result["protected_terms"])
    assert len(result["changes"]) == 1
    change = result["changes"][0]
    assert query[change["start"]:change["end"]] == "insulinn"
    assert "HW1" in result["settings"]["vocabulary"]
    assert "condition B" in result["settings"]["vocabulary"]


def test_spelling_baseline_retains_stopwords_and_unstemmed_terms():
    document = Document("D1", "", [TextBlock("a", "abstract", "", "The patients and treatments were improving.")],
                        pmid="1", content_scope="abstract")
    assert build_vocabulary([document], abstracts_only=True) == {
        "the": 1, "patients": 1, "and": 1, "treatments": 1, "were": 1, "improving": 1,
    }


@pytest.mark.parametrize("query", ["GLP‑1", "GLP‐1", "BRCA2", "1.50", "1.5", "β-cells", "CAFE\u0301", "ﬁber", "Straße"])
def test_unknown_numeric_and_unicode_forms_are_not_rewritten_after_normalization(query):
    result = suggest_query(query, {"glp-1": 5, "brca1": 5, "1.55": 5, "cells": 100, "cafe": 100,
                                   "fiber": 100, "strass": 100})
    assert result["original_query"] == result["suggested_query"] == query
    assert result["changes"] == []
    assert result["protected_terms"]


def test_casefolded_vocabulary_counts_determine_candidates_without_changing_offsets():
    result = suggest_query("strase", {"Straße": 2, "STRASSE": 3, "phrase": 1})
    assert result["changes"][0]["suggestion"] == "strasse"
    assert result["changes"][0]["candidates"][0] == {"term": "strasse", "distance": 1, "cf": 5}
    assert result["changes"][0]["start"] == 0 and result["changes"][0]["end"] == 6
