"""Porter matching, original offsets and dual-index lifecycle; fixtures stay local."""
import copy
import html
import json
import socket
import subprocess
import sys
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from ir_hw1.cli import main
from ir_hw1.index import build_index, load_snapshot, save_index
from ir_hw1.models import Document, TextBlock
from ir_hw1.preprocessing import query_terms, tokenize
from ir_hw1.search import search
from ir_hw1.snippets import make_snippets
from ir_hw1.statistics import compute_statistics
from ir_hw1.storage import StorageError, save_documents
from ir_hw1.sync import sync_raw_folder

ROOT = Path(__file__).resolve().parents[1]


def write_raw(data_dir, pmcid, text):
    (data_dir / "raw").mkdir(exist_ok=True)
    (data_dir / "raw" / f"{pmcid}.xml").write_text(
        f'<article><front><article-meta><article-id pub-id-type="pmc">{pmcid}</article-id>'
        '<title-group><article-title>Synthetic Porter example</article-title></title-group>'
        f'<abstract><p>{html.escape(text)}</p></abstract></article-meta></front>'
        '<body><p>Excluded body.</p></body></article>', encoding="utf-8")


def make_document(pmcid, text):
    doc = Document(pmcid, "Synthetic Porter example", [TextBlock("b0", "body", "Body", text)])
    doc.statistics = compute_statistics(doc)
    return doc


@pytest.fixture
def porter_corpus(tmp_path):
    texts = ["A patient connects.", "Patients connected. The therapy helps.",
             "Connecting therapies help patients."]
    for i, text in enumerate(texts, 1):
        write_raw(tmp_path, f"PMC{i}", text)
    from ir_hw1.corpus import import_bytes
    for path in (tmp_path / "raw").iterdir():
        import_bytes(path.read_bytes(), tmp_path, "test:abstracts", path.relative_to(tmp_path).as_posix(),
                     content_scope="abstract")
    sync_raw_folder(tmp_path)
    return tmp_path


def test_porter_normalization_deduplication_and_protected_terms():
    assert query_terms("CONNECT connected connecting", stemming=True) == ["connect"]
    assert query_terms("therapy therapies", stemming=True) == ["therapi"]
    assert query_terms("therapy therapies") == ["therapy", "therapies"]
    text = "IL-6 COVID-19 patient's 3.5 β-catenin CAFÉ"
    assert query_terms(text, stemming=True) == ["il-6", "covid-19", "patient's", "3.5", "β-catenin", "café"]
    assert [t.text for t in tokenize("Connected patients")] == ["Connected", "patients"]


@pytest.mark.parametrize("query,mode,stemming,expected", [
    ("patient", "AND", False, ["PMC1"]),
    ("patient", "AND", True, ["PMC1", "PMC2", "PMC3"]),
    ("patient therapy", "AND", True, ["PMC2", "PMC3"]),
    ("patient therapy", "AND", False, []),
    ("connect missingxyz", "AND", True, []),
    ("connect missingxyz", "OR", True, ["PMC1", "PMC2", "PMC3"]),
    ("therapy therapies", "AND", True, ["PMC2", "PMC3"]),
    ("therapy therapies", "AND", False, []),
    ("...", "OR", True, []),
])
def test_porter_boolean_results(porter_corpus, query, mode, stemming, expected):
    _, index = load_snapshot(porter_corpus)
    response = search(index, query, mode, stemming=stemming)
    assert response.document_ids == expected
    assert response.stemming is stemming
    if "missingxyz" in query:
        assert response.missing_terms == ["missingxyz"]


def test_merged_tf_original_highlights_and_unchanged_statistics():
    doc = make_document("PMC1", "Therapy & therapies <patients>.")
    original = copy.deepcopy(doc.to_dict())
    index = build_index({doc.pmcid: doc})
    response = search(index, "therapy therapies", stemming=True)
    assert response.terms == ["therapi"]
    assert index["porter_postings"]["therapi"]["PMC1"]["tf"] == 2
    assert index["postings"]["therapy"]["PMC1"]["tf"] == 1
    assert index["postings"]["therapies"]["PMC1"]["tf"] == 1
    snippets = make_snippets(doc, index, response.terms, stemming=response.stemming)
    assert snippets[0]["html"] == "<mark>Therapy</mark> &amp; <mark>therapies</mark> &lt;patients&gt;."
    for term, expected in [("therapy", "Therapy"), ("therapies", "therapies")]:
        original_hit = make_snippets(doc, index, [term])[0]["html"]
        assert original_hit.count("<mark>") == 1
        assert f"<mark>{expected}</mark>" in original_hit
    assert doc.to_dict() == original
    assert compute_statistics(doc) == original["statistics"]


@pytest.mark.parametrize("damage", ["legacy", "missing", "mode", "version", "scope"])
def test_old_or_incompatible_index_rebuilt_without_reparsing(porter_corpus, damage):
    _, index = load_snapshot(porter_corpus)
    original_articles = (porter_corpus / "processed/articles.jsonl").read_bytes()
    original_manifest = (porter_corpus / "manifest.jsonl").read_bytes()
    if damage == "legacy":
        index["version"] = 1
        index.pop("porter_postings")
        index.pop("porter_preprocessing")
    elif damage == "missing":
        index.pop("porter_postings")
    else:
        key = "implementation_version" if damage == "version" else damage
        index["porter_preprocessing"][key] = "incompatible"
    save_index(porter_corpus, index)
    with pytest.raises(StorageError):
        load_snapshot(porter_corpus)
    # A search-only index upgrade must not reimport unchanged source files.
    assert sync_raw_folder(porter_corpus).rebuilt
    _, repaired = load_snapshot(porter_corpus)
    assert search(repaired, "therapy", stemming=True).document_ids == ["PMC2", "PMC3"]
    assert (porter_corpus / "processed/articles.jsonl").read_bytes() == original_articles
    assert (porter_corpus / "manifest.jsonl").read_bytes() == original_manifest
    before = (porter_corpus / "index.json").read_bytes()
    assert not sync_raw_folder(porter_corpus).rebuilt
    assert (porter_corpus / "index.json").read_bytes() == before


def test_raw_updates_refresh_both_indexes(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    xml = raw / "fixture.xml"
    xml.write_bytes((ROOT / "tests/fixtures/synthetic.xml").read_bytes())
    sync_raw_folder(tmp_path)
    _, before = load_snapshot(tmp_path)
    assert search(before, "cancer", stemming=True).document_ids == ["PMC1", "PMC2"]
    xml.write_bytes(xml.read_bytes().replace(b"Cancer", b"Therapies"))
    assert sync_raw_folder(tmp_path).rebuilt
    _, after = load_snapshot(tmp_path)
    assert search(after, "cancer", stemming=True).document_ids == []
    assert search(after, "therapy", stemming=True).document_ids == ["PMC1", "PMC2"]
    assert search(after, "therapies").document_ids == ["PMC1", "PMC2"]
    assert search(after, "therapy").document_ids == []


def test_cli_stemming_option(porter_corpus, capsys):
    assert main(["--data-dir", str(porter_corpus), "search", "connect", "--stemming"]) == 0
    response, _ = json.JSONDecoder().raw_decode(capsys.readouterr().out)
    assert response["stemming"] is True
    # Filtering A/The makes PMC2 and PMC3 equal vectors; IDs break the tie.
    assert response["document_ids"] == ["PMC1", "PMC2", "PMC3"]
    assert response["relevance"] is True
    assert response["ranking"] == "tfidf"


def test_real_corpus_matches_full_scan_and_fresh_offline_process(real_corpus):
    docs, index = load_snapshot(real_corpus)
    queries = ["therapies", "patient", "patients", "connect", "cancer treatment", "connect missingxyz", "..."]
    for stemming in (False, True):
        words = {doc_id: set(query_terms(" ".join(b.text for b in doc.blocks), stemming=stemming))
                 for doc_id, doc in docs.items()}
        for query in queries:
            terms = set(query_terms(query, stemming=stemming))
            for mode in ("AND", "OR"):
                expected = {doc_id for doc_id, vocabulary in words.items()
                            if terms and (terms <= vocabulary if mode == "AND" else bool(terms & vocabulary))}
                assert set(search(index, query, mode, stemming=stemming).document_ids) == expected
    script = """
import socket
def offline(*args, **kwargs):
    raise AssertionError('No network allowed')
socket.socket.connect = offline
from ir_hw1.index import load_snapshot
from ir_hw1.search import search
_, index = load_snapshot()
assert len(search(index, 'therapies').document_ids) == 1
assert len(search(index, 'therapies', stemming=True).document_ids) == 10
"""
    script = "import sys; from pathlib import Path\n" + script.replace("load_snapshot()", "load_snapshot(Path(sys.argv[1]))")
    subprocess.run([sys.executable, "-c", script, str(real_corpus)], cwd=ROOT, check=True, capture_output=True, text=True)


def test_ui_fixed_porter_migrates_old_settings_highlights_and_offline_restart(porter_corpus, monkeypatch):
    for i in range(4, 9):
        write_raw(porter_corpus, f"PMC{i}", "Therapies help.")
    sync_raw_folder(porter_corpus)
    before = (porter_corpus / "index.json").read_bytes()
    monkeypatch.setenv("IR_HW1_DATA_DIR", str(porter_corpus))
    monkeypatch.setattr(socket.socket, "connect", lambda *a: pytest.fail("Porter search must stay offline"))
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    assert not any(t.key == "stemming" for t in app.toggle)
    app.text_input(key="query").set_value("therapy")
    app.button[0].click().run()
    # An older open session cannot turn stemming off or keep an invalid page.
    app.session_state["stemming"] = False
    app.session_state["search_controls"] = {"query": "therapy", "stemming": False}
    app.session_state["result_page"] = 99
    app.session_state["selected_result"] = "PMC1"
    app.run()
    assert not app.exception
    assert any(m.label == "符合文章" and m.value == "7" for m in app.metric)
    assert app.number_input(key="result_page").value == 1
    assert "selected_result" not in app.session_state
    assert "stemming" not in app.session_state
    assert "stemming" not in app.session_state["search_controls"]
    assert any("<mark>therapies</mark>" in m.value for m in app.markdown)
    app.button(key="open_PMC3").click().run()
    assert any(m.label == "單字數" and m.value == "4" for m in app.metric)
    app.checkbox(key="hits_PMC3").check().run()
    assert not app.exception
    app.number_input(key="result_page").set_value(2).run()
    assert app.number_input(key="result_page").value == 2
    app.radio(key="view").set_value("文章管理").run()
    app.radio(key="view").set_value("搜尋文章").run()
    assert not any(t.key == "stemming" for t in app.toggle)
    assert app.text_input(key="query").value == "therapy"
    # Streamlit removes the page widget off-view; returning starts at page one.
    assert app.number_input(key="result_page").value == 1
    app.text_input(key="query").set_value("patients")
    app.button[0].click().run()
    assert not app.exception
    assert app.number_input(key="result_page").value == 1
    assert any(m.label == "符合文章" and m.value == "3" for m in app.metric)
    assert "selected_result" not in app.session_state
    assert (porter_corpus / "index.json").read_bytes() == before
    again = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    assert not any(t.key == "stemming" for t in again.toggle)
    again.text_input(key="query").set_value("therapy")
    again.button[0].click().run()
    assert not again.exception
    assert any(m.label == "符合文章" and m.value == "7" for m in again.metric)
