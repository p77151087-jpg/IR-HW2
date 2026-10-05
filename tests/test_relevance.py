"""Acceptance tests with independent expected scores and temporary corpora."""
import copy
import html
import json
import math
import socket
import subprocess
import sys
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from ir_hw1.cli import main
from ir_hw1.index import INDEX_VERSION, build_index, load_snapshot, save_index
from ir_hw1.library import delete_articles, restore_articles
from ir_hw1.models import Document, TextBlock
from ir_hw1.relevance import relevance_query, relevance_tokens
from ir_hw1.search import search
from ir_hw1.snippets import highlight, hit_locations, make_snippets
from ir_hw1.statistics import compute_statistics
from ir_hw1.storage import StorageError
from ir_hw1.sync import sync_raw_folder

ROOT = Path(__file__).resolve().parents[1]


def corpus(texts):
    docs = {f"PMC{i}": Document(f"PMC{i}", "Metadata", [TextBlock("b0", "abstract", "Abstract", text)],
                               content_scope="abstract") for i, text in enumerate(texts, 1)}
    for doc in docs.values():
        doc.statistics = compute_statistics(doc)
    return docs, build_index(docs)


def write_xml(path, number, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'<article><front><article-meta><article-id pub-id-type="pmc">{number}</article-id>'
                    '<title-group><article-title>Metadata</article-title></title-group>'
                    f'<abstract><p>{html.escape(text)}</p></abstract></article-meta></front></article>', encoding="utf-8")


@pytest.mark.parametrize("query,message", [("", "有效關鍵字"), ("...", "有效關鍵字"),
    ("the and of", "有效關鍵字"), ("a", "有效關鍵字"), ("b", "過於簡短"),
    ("c", "過於簡短"), ("a b c", "過於簡短")])
@pytest.mark.parametrize("stemming", [False, True])
def test_uninformative_queries_do_not_list_articles(query, message, stemming):
    _, index = corpus(["The vitamin A and vitamin C. T cell. Hepatitis B."])
    response = search(index, query, "RELEVANCE", stemming=stemming)
    assert response.document_ids == [] and response.scores == {} and response.terms == []
    assert message in response.query_message


@pytest.mark.parametrize("query,expected", [("vitamin A", ["vitamin", "a"]),
    ("vitamin B", ["vitamin", "b"]), ("vitamin C", ["vitamin", "c"]),
    ("hepatitis B", ["hepatitis", "b"]), ("hepatitis C", ["hepatitis", "c"]),
    ("B cell", ["b", "cell"]), ("T cells", ["t", "cells"]), ("no not", ["no", "not"])])
def test_contextual_letters_and_negation_are_preserved(query, expected):
    assert relevance_query(query) == (expected, "")
    _, index = corpus([query])
    response = search(index, query, "RELEVANCE")
    assert response.document_ids == ["PMC1"]
    assert response.scores["PMC1"] == pytest.approx(1)
    assert set(index["relevance_postings"]) == set(expected)
    assert [t.term for t in relevance_tokens("vitamin. A")] == ["vitamin"]


def test_hand_calculated_scores_full_and_component_tf_df_and_deduplication():
    _, index = corpus(["the covid COVID19 background", "COVID-19 cancer", "the and of"])
    common, rare, repeated = 1 + math.log(4 / 3), 1 + math.log(4 / 2), 1 + math.log(2)
    norms = {"PMC1": math.sqrt((repeated * common)**2 + 2 * common**2 + rare**2),
             "PMC2": math.sqrt(3 * common**2 + rare**2)}
    broad = {"PMC1": repeated * common / norms["PMC1"], "PMC2": common / norms["PMC2"]}
    specific = {doc_id: common / norm for doc_id, norm in norms.items()}
    for stemming in (False, True):
        assert search(index, "covid", "RELEVANCE", stemming=stemming).scores == pytest.approx(broad)
        for query in ("covid19", "COVID-19", "COVID‑19", "covid19 covid-19"):
            response = search(index, query, "RELEVANCE", stemming=stemming)
            assert response.document_ids == ["PMC2", "PMC1"]
            assert response.terms == ["covid-19"]
            assert response.scores == pytest.approx(specific)
        prefix = "porter_" if stemming else ""
        postings, stats = index[prefix + "relevance_postings"], index[prefix + "relevance_tfidf"]
        assert postings["covid-19"]["PMC1"]["tf"] == 1
        assert postings["covid"]["PMC1"]["tf"] == 2
        assert len(postings["covid"]["PMC1"]["locations"]) == 2
        assert stats["idf"]["covid-19"] == pytest.approx(common)
        assert stats["norms"] == pytest.approx({**norms, "PMC3": 0})
        assert stats["norms"]["PMC3"] == 0 and "the" not in postings


def test_partial_matches_stopword_equivalence_unknowns_ties_and_low_scores():
    _, index = corpus(["cancer treatment", "cancer", "treatment", "the and of"])
    simple = search(index, "cancer treatment", "RELEVANCE")
    assert simple.document_ids == ["PMC1", "PMC2", "PMC3"]
    assert simple.scores == pytest.approx({"PMC1": 1, "PMC2": 1 / math.sqrt(2), "PMC3": 1 / math.sqrt(2)})
    assert search(index, "the treatment of cancer", "RELEVANCE").scores == pytest.approx(simple.scores)
    assert search(index, "unknown", "RELEVANCE").document_ids == []
    partial = search(index, "cancer unknown", "RELEVANCE")
    assert set(partial.document_ids) == {"PMC1", "PMC2"} and partial.missing_terms == ["unknown"]
    _, long_index = corpus(["covid-19 " + " ".join(f"background{i}" for i in range(200))])
    low = search(long_index, "covid", "RELEVANCE")
    assert low.document_ids == ["PMC1"] and 0 < low.scores["PMC1"] < .1


def test_offsets_statistics_legacy_phrase_and_specific_virus_types():
    text = "The vitamin A & <unsafe> COVID‑19 covid19. T cell. HIV-2."
    docs, index = corpus([text])
    before = copy.deepcopy(docs["PMC1"].to_dict())
    for stemming in (False, True):
        response = search(index, "covid", "RELEVANCE", stemming=stemming)
        hits = hit_locations(index, "PMC1", response.terms, relevance=True, stemming=stemming,
                             query="covid", document=docs["PMC1"])
        assert [text[start:end] for start, end in hits["b0"]] == ["COVID", "covid"]
        snippet = make_snippets(docs["PMC1"], index, response.terms, relevance=True,
                                stemming=stemming, query="covid")[0]["html"]
        assert "<mark>COVID</mark>‑19" in snippet and "<mark>covid</mark>19" in snippet
        assert "&lt;unsafe&gt;" in snippet and "<unsafe>" not in snippet
        assert search(index, "HIV-1", "RELEVANCE", stemming=stemming).document_ids == []
        assert search(index, "cov", "RELEVANCE", stemming=stemming).document_ids == []
        assert search(index, "HIV-2", "RELEVANCE", stemming=stemming).document_ids == ["PMC1"]
    assert docs["PMC1"].to_dict() == before
    assert compute_statistics(docs["PMC1"]) == before["statistics"]
    assert "the" in index["postings"] and "a" in index["postings"]
    assert search(index, "the vitamin a", "PHRASE", documents=docs).document_ids == ["PMC1"]


@pytest.mark.parametrize("query,partial", [
    ("covid", True), ("CoViD", True), ("the covid", True),
    ("covid19", False), ("covid-19", False), ("COVID‑19", False),
    ("covid covid19 covid-19", False),
])
@pytest.mark.parametrize("stemming", [False, True])
def test_full_and_component_highlights_preserve_original_offsets(query, partial, stemming):
    text = "& <unsafe> COVID-19, Covid19, covid, COVID‑19."
    docs, index = corpus([text, "covid-19 treatment"])
    document = docs["PMC1"]
    before = copy.deepcopy(index)
    response = search(index, query, "RELEVANCE", stemming=stemming)
    assert set(response.document_ids) == {"PMC1", "PMC2"}
    bare = "<mark>covid</mark>" if partial or query.startswith("covid covid19") else "covid"
    expected = ("&amp; &lt;unsafe&gt; <mark>COVID</mark>-19, <mark>Covid</mark>19, "
                "<mark>covid</mark>, <mark>COVID</mark>‑19." if partial else
                "&amp; &lt;unsafe&gt; <mark>COVID-19</mark>, <mark>Covid19</mark>, "
                f"{bare}, <mark>COVID‑19</mark>.")
    locations = hit_locations(index, "PMC1", response.terms, relevance=True,
                              stemming=stemming, query=query, document=document)
    assert highlight(text, locations["b0"]) == expected
    assert make_snippets(document, index, response.terms, relevance=True,
                         stemming=stemming, query=query)[0]["html"] == expected
    # The index supplies exact component offsets, even without the original query.
    assert make_snippets(document, index, response.terms, relevance=True,
                         stemming=stemming)[0]["html"] == expected
    assert index == before


@pytest.mark.parametrize("damage", ["v3", "v4", "policy", "postings", "porter_postings", "idf", "norm"])
def test_offline_upgrade_repairs_relevance_without_reimport(stored, monkeypatch, damage):
    monkeypatch.setattr(socket.socket, "connect", lambda *a: pytest.fail("Upgrade stays offline"))
    sync_raw_folder(stored)
    _, index = load_snapshot(stored)
    before = {name: (stored / name).read_bytes() for name in ["raw/synthetic.xml", "processed/articles.jsonl", "manifest.jsonl"]}
    if damage in {"v3", "v4"}:
        index["version"] = int(damage[1:])
        for key in list(index):
            if "relevance" in key:
                del index[key]
    elif damage == "policy":
        index["relevance_preprocessing"]["vocabulary_sha256"] = "old-policy"
    elif damage in {"postings", "porter_postings"}:
        index.pop("porter_relevance_postings" if damage.startswith("porter") else "relevance_postings")
    elif damage == "idf":
        index["relevance_tfidf"]["idf"]["cancer"] = float("nan")
    else:
        index["porter_relevance_tfidf"]["norms"]["PMC1"] = -1
    save_index(stored, index)
    with pytest.raises(StorageError):
        load_snapshot(stored)
    assert sync_raw_folder(stored).rebuilt
    _, upgraded = load_snapshot(stored)
    assert upgraded["version"] == INDEX_VERSION
    assert search(upgraded, "the cancer", "RELEVANCE").document_ids
    assert all((stored / name).read_bytes() == value for name, value in before.items())
    assert not sync_raw_folder(stored).rebuilt


def test_mutations_and_fresh_offline_process(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(socket.socket, "connect", lambda *a: pytest.fail("Local corpus stays offline"))
    one, two = tmp_path / "raw/one.xml", tmp_path / "raw/two.xml"
    write_xml(one, 1, "COVID-19 therapies")
    sync_raw_folder(tmp_path)
    write_xml(two, 2, "covid19")
    sync_raw_folder(tmp_path)
    docs, index = load_snapshot(tmp_path)
    for key in ("relevance_tfidf", "porter_relevance_tfidf"):
        assert index[key]["idf"]["covid-19"] == 1
    initial = search(index, "covid", "RELEVANCE")
    assert initial.document_ids == ["PMC2", "PMC1"]
    delete_articles(tmp_path, ["PMC2"])
    _, deleted = load_snapshot(tmp_path)
    assert search(deleted, "covid", "RELEVANCE").document_ids == ["PMC1"]
    restore_articles(tmp_path, ["PMC2"])
    _, restored = load_snapshot(tmp_path)
    assert search(restored, "covid", "RELEVANCE").scores == initial.scores
    write_xml(two, 2, "vitamin C")
    sync_raw_folder(tmp_path)
    _, changed = load_snapshot(tmp_path)
    assert search(changed, "covid", "RELEVANCE").document_ids == ["PMC1"]
    assert changed["relevance_tfidf"]["idf"]["covid-19"] == pytest.approx(1 + math.log(3 / 2))
    assert search(changed, "therapy", "RELEVANCE", stemming=True).document_ids == ["PMC1"]
    assert search(changed, "therapy", "RELEVANCE").document_ids == []
    assert main(["--data-dir", str(tmp_path), "search", "the covid"]) == 0
    response, _ = json.JSONDecoder().raw_decode(capsys.readouterr().out)
    assert response["relevance"] and response["document_ids"] == ["PMC1"]
    script = """
import socket, sys
from pathlib import Path
socket.socket.connect = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('offline'))
from ir_hw1.index import load_snapshot
from ir_hw1.search import search
_, index = load_snapshot(Path(sys.argv[1]))
assert search(index, 'covid19', 'RELEVANCE').document_ids == ['PMC1']
assert search(index, 'the', 'RELEVANCE').document_ids == []
"""
    persisted = (tmp_path / "index.json").read_bytes()
    subprocess.run([sys.executable, "-X", "utf8", "-c", script, str(tmp_path)], cwd=ROOT, check=True, capture_output=True)
    assert (tmp_path / "index.json").read_bytes() == persisted
    one.unlink()
    sync_raw_folder(tmp_path)
    _, removed = load_snapshot(tmp_path)
    assert search(removed, "covid", "RELEVANCE").document_ids == []
    assert next(b.text for b in docs["PMC1"].blocks if b.kind == "abstract") == "COVID-19 therapies"


def test_ui_validation_component_highlight_and_old_session_migration(tmp_path, monkeypatch):
    write_xml(tmp_path / "raw/one.xml", 1, "The COVID-19 treatment and vitamin A.")
    monkeypatch.setenv("IR_HW1_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(socket.socket, "connect", lambda *a: pytest.fail("UI stays offline"))
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    assert not app.exception
    app.session_state["active_search"] = ("covid", "PHRASE")
    app.session_state["search_controls"] = {"query": "covid", "mode": "PHRASE", "stemming": False}
    app.run()
    assert not app.exception and not any(s.key == "mode" for s in app.selectbox)
    assert not any(t.key == "stemming" for t in app.toggle)
    assert "stemming" not in app.session_state["search_controls"]
    assert any("<mark>COVID</mark>-19" in m.value for m in app.markdown)
    assert any(c.value.startswith("相關性：") and c.value.endswith("%") for c in app.caption)
    assert all("TF-IDF" not in c.value for c in app.caption)
    app.button(key="open_PMC1").click().run()
    assert not app.exception
    assert any("article-text" in m.value and "<mark>COVID</mark>-19" in m.value for m in app.markdown)
    before_stats = [(m.label, m.value) for m in app.metric if m.label in {"單字數", "句子數"}]
    app.run()
    app.button(key="open_PMC1").click().run()
    assert before_stats == [(m.label, m.value) for m in app.metric if m.label in {"單字數", "句子數"}]
    assert any("article-text" in m.value and "<mark>COVID</mark>-19" in m.value for m in app.markdown)
    # Editing an unsubmitted query must not alter the active result's highlighting.
    app.text_input(key="query").set_value("covid-19").run()
    assert any("<mark>COVID</mark>-19" in m.value for m in app.markdown)
    app.button[0].click().run()
    app.button(key="open_PMC1").click().run()
    assert not app.exception
    assert any("article-text" in m.value and "<mark>COVID-19</mark>" in m.value for m in app.markdown)
    for query, message in [("the and of", "有效關鍵字"), ("a b c", "過於簡短")]:
        app.text_input(key="query").set_value(query)
        app.button[0].click().run()
        assert not app.exception and any(message in i.value for i in app.info)
        assert not any(b.key and b.key.startswith("open_") for b in app.button)
    app.text_input(key="query").set_value('"vitamin A"')
    app.button[0].click().run()
    assert not app.exception and any("特殊搜尋語法" in w.value for w in app.warning)
    assert any("<mark>A</mark>" in m.value for m in app.markdown)
    app.radio(key="view").set_value("文章管理").run()
    app.radio(key="view").set_value("搜尋文章").run()
    assert not app.exception and not any(s.key == "mode" for s in app.selectbox)
    assert app.text_input(key="query").value == '"vitamin A"'
