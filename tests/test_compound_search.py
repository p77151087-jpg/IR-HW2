"""General boundary matching: no disease-specific vocabulary or substring search."""
import copy

import pytest
from streamlit.testing.v1 import AppTest

from ir_hw1.index import build_index
from ir_hw1.models import Document, TextBlock
from ir_hw1.relevance import relevance_query, relevance_tokens
from ir_hw1.search import search
from ir_hw1.snippets import highlight, hit_locations
from tests.test_relevance import ROOT, corpus, write_xml


@pytest.mark.parametrize("stemming", [False, True])
@pytest.mark.parametrize("query,expected", [
    ("covid", {1, 2, 3}), ("covid19", {2, 3}), ("covid-19", {2, 3}),
    ("cov", set()), ("hiv", {4, 5, 6}), ("HIV-1", {4, 6}), ("HIV2", {5}),
    ("IL", {7, 8}), ("IL6", {7, 8}), ("IL-6", {7, 8}),
    ("BRCA", {9, 10}), ("BRCA1", {9}), ("BRCA-2", {10}),
    ("risk", {11}), ("high-risk", {11}), ("high", {11}),
    ("cat", set()), ("H1N1", {13}), ("H1N2", {14}),
    ("state-of-the-art", {15}), ("art", {15}), ("of", set()),
    ("patient's", {16}), ("3.5", {16}), ("3", set()),
])
def test_boundaries_and_specific_numbers(query, expected, stemming):
    _, index = corpus(["covid", "COVID-19", "COVID19", "HIV-1", "HIV-2", "HIV1",
                       "IL-6", "IL6", "BRCA1", "BRCA-2", "high-risk", "education",
                       "H1N1", "H1N2", "state-of-the-art", "patient's 3.5"])
    response = search(index, query, "RELEVANCE", stemming=stemming)
    assert set(response.document_ids) == {f"PMC{i}" for i in expected}


@pytest.mark.parametrize("text,query,marked", [
    ("COVID19", "covid", "<mark>COVID</mark>19"),
    ("COVID‑19", "covid19", "<mark>COVID‑19</mark>"),
    ("IL‐6", "il", "<mark>IL</mark>‐6"),
    ("IL6", "il-6", "<mark>IL6</mark>"),
    ("BRCA2", "brca", "<mark>BRCA</mark>2"),
    ("β-catenin", "β", "<mark>β</mark>-catenin"),
    ("CAFE\u0301-2", "café", "<mark>CAFE\u0301</mark>-2"),
    ("Straße-2", "strasse", "<mark>Straße</mark>-2"),
    ("high-risk", "risk", "high-<mark>risk</mark>"),
])
def test_unicode_and_component_offsets(text, query, marked):
    text = "<unsafe> & " + text
    docs, index = corpus([text])
    before = copy.deepcopy(docs["PMC1"].to_dict())
    response = search(index, query, "RELEVANCE")
    locations = hit_locations(index, "PMC1", response.terms, relevance=True)
    assert highlight(text, locations["b0"]) == "&lt;unsafe&gt; &amp; " + marked
    assert docs["PMC1"].to_dict() == before


def test_query_compounds_do_not_become_or_and_do_not_cross_tokens_or_blocks():
    docs, index = corpus(["HIV-2 treatment", "HIV-1", "HIV 1", "HIV,1", "HIV-11"])
    assert search(index, "HIV-1", "RELEVANCE").document_ids == ["PMC2"]
    # Ordinary multi-keyword relevance remains a union of complete conditions.
    assert set(search(index, "HIV-1 treatment", "RELEVANCE").document_ids) == {"PMC1", "PMC2"}
    docs["PMC6"] = Document("PMC6", "Metadata", [TextBlock("b0", "abstract", "A", "HIV"),
                                               TextBlock("b1", "abstract", "B", "1")])
    assert search(build_index(docs), "HIV-1", "RELEVANCE").document_ids == ["PMC2"]


def test_features_deduplicate_spellings_preserve_real_occurrences_and_legacy():
    docs, index = corpus(["IL6 IL-6 IL‐6 risk-risk therapies-2"])
    postings = index["relevance_postings"]
    for term in ("il", "6", "il-6"):
        assert postings[term]["PMC1"]["tf"] == 3
        assert len(postings[term]["PMC1"]["locations"]) == 3
    assert postings["risk"]["PMC1"]["tf"] == 2
    assert relevance_query("IL6 IL-6 IL‐6") == (["il-6"], "")
    assert search(index, "IL6 IL-6", "RELEVANCE").scores == search(index, "IL6", "RELEVANCE").scores
    assert search(index, "therapy", "RELEVANCE", stemming=True).document_ids == ["PMC1"]
    assert search(index, "therapy", "RELEVANCE").document_ids == []
    assert search(index, "il", "OR").document_ids == []
    assert search(index, "IL6 IL-6", "PHRASE", documents=docs).document_ids == ["PMC1"]
    assert relevance_query("and-of a-b")[0] == []
    assert [t.term for t in relevance_tokens("IL6", include_components=True)] == ["il-6", "il", "6"]


def test_ui_generic_matching_specificity_and_fresh_session(tmp_path, monkeypatch):
    write_xml(tmp_path / "raw/one.xml", 1, "IL-6 and BRCA1.")
    write_xml(tmp_path / "raw/two.xml", 2, "IL-7 and BRCA2.")
    monkeypatch.setenv("IR_HW1_DATA_DIR", str(tmp_path))
    for _ in range(2):
        app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
        for query, ids, marked in [("IL", {"PMC1", "PMC2"}, "<mark>IL</mark>-6"),
                                   ("IL6", {"PMC1"}, "<mark>IL-6</mark>"),
                                   ("BRCA1", {"PMC1"}, "<mark>BRCA1</mark>")]:
            app.text_input(key="query").set_value(query)
            app.button[0].click().run()
            assert not app.exception
            assert {b.key[5:] for b in app.button if b.key and b.key.startswith("open_")} == ids
            assert any(marked in m.value for m in app.markdown)
            app.button(key="open_PMC1").click().run()
            assert any("article-text" in m.value and marked in m.value for m in app.markdown)
