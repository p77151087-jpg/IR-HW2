"""Hand-checkable synthetic phrases, UI workflow, and fixed real-corpus checks."""
import html
import json
import re
import socket
import subprocess
import sys
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from ir_hw1.cli import main
from ir_hw1.index import build_index, load_snapshot
from ir_hw1.models import Document, TextBlock
from ir_hw1.search import search
from ir_hw1.snippets import highlight, make_snippets
from ir_hw1.sync import sync_raw_folder

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def phrase_corpus(tmp_path):
    rows = [
        (1, "Exact example", "", ["Cancer treatment helps. Cancer alone is different."]),
        (2, "Separated example", "", ["Cancer is common. Treatment helps."]),
        (3, "Reverse example", "", ["Treatment cancer."]),
        (4, "Plural example", "", ["Cancer treatments help."]),
        (5, "Substring example", "", ["Precancer treatment helps."]),
        (6, "Repeated example", "", ["Cancer treatment and cancer treatment. Cancer alone."]),
        (7, "Cancer", "", ["Treatment helps."]),
        (8, "Abstract example", "Cancer treatment works.", ["Body has no matching words."]),
        (9, "Cancer treatment", "", ["Body has no matching words."]),
        (10, "Comma example", "", ["Cancer, treatment."]),
        (11, "Sentence example", "", ["Cancer. Treatment."]),
        (12, "Paragraph example", "", ["Cancer", "Treatment"]),
    ]
    articles = []
    for number, title, abstract, paragraphs in rows:
        articles.append(
            f'<article><front><article-meta><article-id pub-id-type="pmc">{number}</article-id>'
            f'<title-group><article-title>{html.escape(title)}</article-title></title-group>'
            + '<abstract>' + ''.join(f'<p>{html.escape(p)}</p>' for p in ([abstract] if abstract else paragraphs))
            + '</abstract></article-meta></front><body><p>Cancer treatment bodyonly.</p></body></article>'
        )
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw/phrases.xml").write_text('<articles>' + ''.join(articles) + '</articles>', encoding="utf-8")
    from ir_hw1.corpus import import_bytes
    import_bytes((tmp_path / "raw/phrases.xml").read_bytes(), tmp_path, "test:abstracts", "raw/phrases.xml",
                 content_scope="abstract")
    sync_raw_folder(tmp_path)
    return tmp_path


def test_phrase_order_boundaries_and_fields(phrase_corpus):
    docs, index = load_snapshot(phrase_corpus)
    phrase = search(index, "cancer treatment", "PHRASE", documents=docs)
    assert phrase.document_ids == ["PMC1", "PMC6", "PMC8"]
    assert search(index, "cancer treatment", "AND").document_ids == [
        "PMC1", "PMC2", "PMC3", "PMC6", "PMC8", "PMC10", "PMC11", "PMC12"]
    assert len(search(index, "cancer treatment", "OR").document_ids) == 11
    assert {b.kind for doc_id in phrase.document_ids for b in docs[doc_id].blocks
            if b.id in phrase.phrase_locations[doc_id]} == {"abstract"}
    assert search(index, "bodyonly").document_ids == []
    for doc_id in phrase.document_ids:
        snippets = make_snippets(docs[doc_id], index, phrase.terms, locations=phrase.phrase_locations[doc_id])
        assert snippets and all("<mark>Cancer treatment</mark>" in s["html"] for s in snippets)
    hits = phrase.phrase_locations["PMC6"]
    assert sum(map(len, hits.values())) == 2
    block = next(b for b in docs["PMC6"].blocks if b.id in hits)
    assert highlight(block.text, hits[block.id]).endswith("Cancer alone.")


@pytest.mark.parametrize("query", ["CANCER treatment", " cancer   treatment ", '"cancer treatment"', '“Cancer treatment”'])
def test_phrase_query_normalization(phrase_corpus, query):
    docs, index = load_snapshot(phrase_corpus)
    result = search(index, query, "PHRASE", documents=docs, stemming=True)
    assert result.document_ids == ["PMC1", "PMC6", "PMC8"]
    assert not result.stemming and "Porter" in result.warning


@pytest.mark.parametrize("text,query,expected", [
    ("cancer\t \ntreatment", "cancer treatment", [(0, 18)]),
    ("cancer / treatment", "cancer treatment", []),
    ("cancer—treatment", "cancer treatment", []),
    ("cancer-treatment", "cancer treatment", []),
    ("cancerous treatment", "cancer treatment", []),
    ("very very very", "very very", [(0, 9), (5, 14)]),
    ("very useful", "very very", []),
    ("IL-6 therapy at 3.5 mg", "il-6 therapy", [(0, 12)]),
    ("IL-6 therapy at 3.5 mg", "3.5 mg", [(16, 22)]),
    ("Patient’s therapy", "patient's therapy", [(0, 17)]),
    ("Breast cancer treatment helps.", "breast cancer treatment", [(0, 23)]),
    ("Breast cancer requires treatment.", "breast cancer treatment", []),
    ("Treatment for breast cancer.", "breast cancer treatment", []),
    ("New breast cancer treatment helps.", "new breast cancer treatment", [(0, 27)]),
    ("New breast cancer. Treatment helps.", "new breast cancer treatment", []),
])
def test_phrase_positions(text, query, expected):
    doc = Document("PMC1", "", [TextBlock("b0", "body", "Body", text)])
    docs = {doc.pmcid: doc}
    result = search(build_index(docs), query, "PHRASE", documents=docs)
    assert result.phrase_locations.get("PMC1", {}).get("b0", []) == expected


@pytest.mark.parametrize("query", ["", "  ", "...", "unknown unknown"])
def test_phrase_empty_and_no_result(phrase_corpus, query):
    docs, index = load_snapshot(phrase_corpus)
    result = search(index, query, "PHRASE", documents=docs)
    assert result.document_ids == [] and result.phrase_locations == {}
    if query == "unknown unknown":
        assert result.missing_terms == ["unknown"]


@pytest.mark.parametrize("query", ["cancer,treatment", '"cancer" "treatment"', "(cancer treatment)", '"cancer treatment'])
def test_phrase_unsupported_syntax(phrase_corpus, query):
    docs, index = load_snapshot(phrase_corpus)
    with pytest.raises(ValueError, match="精準片語"):
        search(index, query, "PHRASE", documents=docs)


def test_phrase_long_highlight_and_html_safety():
    phrase = " ".join(["therapy"] * 60)
    text = "<script>alert(1)</script> " + phrase + " <unsafe>"
    doc = Document("PMC1", "", [TextBlock("b0", "body", "Body", text)])
    docs = {doc.pmcid: doc}
    index = build_index(docs)
    result = search(index, phrase, "PHRASE", documents=docs)
    snippet = make_snippets(doc, index, result.terms, locations=result.phrase_locations[doc.pmcid])[0]
    assert f"<mark>{phrase}</mark>" in snippet["html"]
    assert "<script>" not in snippet["html"] and "<unsafe>" not in snippet["html"]
    assert snippet["end"] >= len(text) - len(" <unsafe>")

    # Overlapping matches must not be cut through at the edge of the excerpt.
    text = phrase + " therapy"
    doc = Document("PMC1", "", [TextBlock("b0", "body", "Body", text)])
    docs = {doc.pmcid: doc}
    index = build_index(docs)
    result = search(index, phrase, "PHRASE", documents=docs)
    assert len(result.phrase_locations["PMC1"]["b0"]) == 2
    snippet = make_snippets(doc, index, result.terms, locations=result.phrase_locations[doc.pmcid])[0]
    assert snippet["html"] == f"<mark>{text}</mark>"


def test_phrase_cli_and_offline_restart(phrase_corpus, capsys, monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", lambda *a: pytest.fail("No network for local phrase search"))
    assert main(["--data-dir", str(phrase_corpus), "search", "cancer treatment", "--mode", "PHRASE"]) == 0
    output = capsys.readouterr().out
    response, _ = json.JSONDecoder().raw_decode(output)
    assert response["document_ids"] == ["PMC6", "PMC8", "PMC1"]
    assert response["ranking"] == "tfidf"
    before = (phrase_corpus / "index.json").read_bytes()
    script = """
import socket, sys
from pathlib import Path
socket.socket.connect = lambda *a, **kw: (_ for _ in ()).throw(RuntimeError('offline'))
from ir_hw1.index import load_snapshot
from ir_hw1.search import search
d, i = load_snapshot(Path(sys.argv[1]))
assert search(i, 'cancer treatment', 'PHRASE', documents=d).document_ids == ['PMC1', 'PMC6', 'PMC8']
"""
    subprocess.run([sys.executable, "-c", script, str(phrase_corpus)], cwd=ROOT, check=True, capture_output=True)
    assert (phrase_corpus / "index.json").read_bytes() == before


def test_ui_keeps_keyword_ranking_when_query_is_quoted(phrase_corpus, monkeypatch):
    monkeypatch.setenv("IR_HW1_DATA_DIR", str(phrase_corpus))
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    assert not any(t.key == "stemming" for t in app.toggle)
    app.text_input(key="query").set_value('"cancer treatment"')
    app.button[0].click().run()
    assert not app.exception
    assert not any(s.key == "mode" for s in app.selectbox)
    assert not any(t.key == "stemming" for t in app.toggle)
    assert any("特殊搜尋語法" in w.value for w in app.warning)
    docs, index = load_snapshot(phrase_corpus)
    expected = search(index, "cancer treatment", "RELEVANCE", stemming=True)
    assert any(m.label == "符合文章" and m.value == str(len(expected.document_ids)) for m in app.metric)
    # The CLI/API exact-phrase tests above remain separate from the new UI.
    app.text_input(key="query").set_value("unknown unknown")
    app.button[0].click().run()
    assert any("找不到" in m.value for m in app.info)
    app.text_input(key="query").set_value("cancer,treatment")
    app.button[0].click().run()
    assert not app.exception
    assert any(m.label == "符合文章" and m.value == str(len(expected.document_ids)) for m in app.metric)



def test_real_phrase_agrees_with_direct_text_scan(real_corpus):
    docs, index = load_snapshot(real_corpus)
    for phrase in ("cancer treatment", "cardiovascular disease", "tuberculous meningitis", "hiv infection"):
        pattern = re.compile(r"(?<![\w'’‐‑-])" + r"\s+".join(phrase.split()) + r"(?![\w'’‐‑-])", re.I)
        expected = {doc_id for doc_id, doc in docs.items() if any(pattern.search(b.text) for b in doc.blocks)}
        result = search(index, phrase, "PHRASE", documents=docs)
        assert set(result.document_ids) == expected
        for doc_id, blocks in result.phrase_locations.items():
            for bid, spans in blocks.items():
                text = next(b.text for b in docs[doc_id].blocks if b.id == bid)
                assert all(pattern.fullmatch(text[start:end]) for start, end in spans)
