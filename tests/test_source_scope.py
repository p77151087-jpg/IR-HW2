"""Input identifiers choose persistent content scope, including PubMed-only records."""
from pathlib import Path
from unittest.mock import Mock

import pytest
from streamlit.testing.v1 import AppTest

from ir_hw1.index import build_index, load_snapshot
from ir_hw1.library import PUBMED_URL, download_pmid, upload_xml, delete_articles, restore_articles
from ir_hw1.purge import purge_articles
from ir_hw1.search import search
from ir_hw1.storage import load_documents
from ir_hw1.sync import sync_raw_folder
from ir_hw1.xml_parser import articles_in_xml, parse_article


PUBMED = b'''<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>999</PMID>
<Article><ArticleTitle>Titleonly</ArticleTitle><Journal><JournalIssue><PubDate><Year>2026</Year></PubDate></JournalIssue></Journal>
<Abstract><AbstractText Label="RESULTS">Abstract therapy works.</AbstractText></Abstract><Language>eng</Language></Article>
</MedlineCitation><PubmedData><ArticleIdList><ArticleId IdType="pubmed">999</ArticleId><ArticleId IdType="doi">10.test/example</ArticleId></ArticleIdList></PubmedData>
</PubmedArticle></PubmedArticleSet>'''
JATS = b'''<article><front><article-meta><article-id pub-id-type="pmc">42</article-id><article-id pub-id-type="pmid">999</article-id>
<title-group><article-title>Titleonly</article-title></title-group><abstract><p>Abstract therapy works.</p></abstract>
<permissions><license xmlns:xlink="http://www.w3.org/1999/xlink" xlink:href="https://creativecommons.org/licenses/by/4.0/">CC BY</license></permissions>
</article-meta></front><body><p>Bodyonly treatments.</p></body></article>'''


@pytest.mark.parametrize("value,raw,scope,identifier", [
    ("999", PUBMED, "abstract", "PMID999"), ("PMID: 999", PUBMED, "abstract", "PMID999"),
    ("pmc42", JATS, "full", "PMC42"),
])
def test_input_routes_to_correct_api_and_scope(tmp_path, monkeypatch, value, raw, scope, identifier):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    client = Mock()
    client.get.return_value = (raw, "https://source.example/test")
    monkeypatch.setattr("ir_hw1.library.PMCClient", lambda: client)
    assert download_pmid(tmp_path, value)[0]["status"] == "imported"
    docs, index = load_snapshot(tmp_path)
    assert docs[identifier].content_scope == scope
    assert search(index, "abstract").document_ids == [identifier]
    assert search(index, "titleonly").document_ids == ([identifier] if scope == "full" else [])
    assert search(index, "bodyonly").document_ids == ([identifier] if scope == "full" else [])
    if scope == "abstract":
        assert client.get.call_args.kwargs == {"endpoint": PUBMED_URL}
        assert client.get.call_args.args[0]["db"] == "pubmed"
        assert docs[identifier].statistics["words"] == 3
        assert docs[identifier].statistics["characters"] == 23
        assert docs[identifier].statistics["characters_no_whitespace"] == 21
        assert docs[identifier].blocks[0].section == "摘要 / RESULTS"
        assert search(index, "results", ranking="tfidf").document_ids == []
        assert docs[identifier].statistics["sentences"] == 1
    else:
        assert client.get.call_args.args[0]["identifier"] == "oai:pubmedcentral.nih.gov:42"
    sync_raw_folder(tmp_path)
    assert load_snapshot(tmp_path)[0][identifier].content_scope == scope


def test_same_article_switches_scope_offline_and_retains_it(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr("ir_hw1.library.PMCClient", lambda: pytest.fail("Existing XML needs no download"))
    upload_xml(tmp_path, "article.xml", JATS)
    for identifier, scope, hits in [("999", "abstract", []), ("PMC42", "full", ["PMC42"]), ("999", "abstract", [])]:
        assert download_pmid(tmp_path, identifier)[0]["status"] == "updated"
        sync_raw_folder(tmp_path)
        docs, index = load_snapshot(tmp_path)
        assert list(docs) == ["PMC42"]
        assert docs["PMC42"].content_scope == scope
        assert search(index, "treatment", stemming=True).document_ids == hits
    source = tmp_path / docs["PMC42"].raw_path
    source.write_bytes(source.read_bytes().replace(b"therapy", b"kidneys"))
    sync_raw_folder(tmp_path)
    assert load_snapshot(tmp_path)[0]["PMC42"].content_scope == "abstract"
    delete_articles(tmp_path, ["PMC42"])
    restore_articles(tmp_path, ["PMC42"])
    docs, index = load_snapshot(tmp_path)
    assert docs["PMC42"].content_scope == "abstract"
    assert search(index, "kidney", stemming=True).document_ids == ["PMC42"]
    assert search(index, "bodyonly").document_ids == []


def test_pubmed_only_shared_xml_restore_and_purge(tmp_path):
    other = PUBMED.replace(b">999<", b">1000<")
    raw = PUBMED.replace(b"</PubmedArticleSet>", other.replace(b"<PubmedArticleSet>", b""))
    upload_xml(tmp_path, "abstracts.xml", raw)
    delete_articles(tmp_path, ["PMID999"])
    restore_articles(tmp_path, ["PMID999"])
    assert load_documents(tmp_path)["PMID999"].content_scope == "abstract"
    delete_articles(tmp_path, ["PMID999"])
    assert purge_articles(tmp_path, ["PMID999"]) == 1
    sync_raw_folder(tmp_path)
    assert list(load_documents(tmp_path)) == ["PMID1000"]
    assert [d.pmid for p in (tmp_path / "raw").iterdir() for d in map(parse_article, articles_in_xml(p.read_bytes()))] == ["1000"]


def test_missing_abstract_does_not_use_title():
    raw = PUBMED.replace(b'<Abstract><AbstractText Label="RESULTS">Abstract therapy works.</AbstractText></Abstract>', b'')
    doc = parse_article(articles_in_xml(raw)[0])
    assert doc.title == "Titleonly" and not doc.blocks
    assert doc.statistics["words"] == doc.statistics["sentences"] == 0


def test_pubmed_labels_are_metadata_even_when_abstract_is_empty():
    raw = PUBMED.replace(b'Abstract therapy works.', b'')
    doc = parse_article(articles_in_xml(raw)[0])
    assert doc.blocks == []
    assert doc.statistics["characters"] == doc.statistics["words"] == doc.statistics["sentences"] == 0
    assert search(build_index({doc.pmcid: doc}), "results", ranking="tfidf").scores == {}


@pytest.mark.parametrize("own_ids,expected", [
    (b'<ArticleIdList><ArticleId IdType="pmc">PMC42</ArticleId><ArticleId IdType="doi">10.test/own</ArticleId></ArticleIdList>', "PMC42"),
    (b'<ArticleIdList><ArticleId IdType="pubmed">999</ArticleId></ArticleIdList>', "PMID999"),
    (b'', "PMID999"),
])
def test_reference_identifiers_cannot_replace_article_identity(own_ids, expected):
    original = b'<ArticleIdList><ArticleId IdType="pubmed">999</ArticleId><ArticleId IdType="doi">10.test/example</ArticleId></ArticleIdList>'
    references = b'<ReferenceList><Reference><ArticleIdList><ArticleId IdType="pmc">PMC9999</ArticleId><ArticleId IdType="doi">10.test/reference</ArticleId></ArticleIdList></Reference></ReferenceList>'
    raw = PUBMED.replace(original, own_ids + references)
    doc = parse_article(articles_in_xml(raw)[0])
    assert doc.pmcid == expected and doc.pmid == "999"
    assert doc.doi == ("10.test/own" if expected == "PMC42" else "")


def test_wrong_pmid_is_rejected_before_raw_write(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    client = Mock()
    client.get.return_value = (PUBMED.replace(b">999<", b">1000<"), PUBMED_URL)
    monkeypatch.setattr("ir_hw1.library.PMCClient", lambda: client)
    result = download_pmid(tmp_path, "999")[0]
    assert result["status"] == "download_failed" and "不一致" in result["reason"]
    sync_raw_folder(tmp_path)
    assert not load_documents(tmp_path) and not list((tmp_path / "raw").iterdir())


def test_ui_switches_between_abstract_and_full_content(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("IR_HW1_DATA_DIR", str(tmp_path))
    upload_xml(tmp_path, "article.xml", JATS)
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=30).run()
    for value, expected_tab, words in [("999", "摘要", "3"), ("PMC42", "摘要與全文", "6")]:
        app.radio(key="view").set_value("文章管理").run()
        app.text_input(key="download_pmid").set_value(value)
        app.button(key="fetch_pmid").click().run()
        app.radio(key="view").set_value("文章詳情").run()
        assert not app.exception
        assert app.tabs[0].label == expected_tab
        assert any(m.label == "單字數" and m.value == words for m in app.metric)
        assert any("Bodyonly" in m.value for m in app.markdown) == (value == "PMC42")
