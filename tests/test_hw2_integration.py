from hashlib import sha256

from ir_hw1.search import search
from ir_hw1.index import load_snapshot
from ir_hw1.storage import load_documents
from ir_hw1.sync import sync_raw_folder
from ir_hw1.xml_parser import articles_in_xml, parse_article
from ir_hw2.integration import publish_search_copy


def test_search_copy_preserves_snapshot_and_survives_sync(tmp_path, monkeypatch):
    raw = b'''<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>123</PMID><Article><ArticleTitle>Metadata excluded</ArticleTitle><Abstract><AbstractText Label="METHODS">Insulin therapy helps GLP-1 treatment.</AbstractText></Abstract><Language>eng</Language></Article></MedlineCitation></PubmedArticle></PubmedArticleSet>'''
    source = tmp_path / "snapshot"
    (source / "raw-batches").mkdir(parents=True)
    original = source / "raw-batches/batch.xml"
    original.write_bytes(raw)
    doc = parse_article(articles_in_xml(raw)[0])
    doc.raw_path = "raw-batches/batch.xml"
    doc.sha256 = sha256(raw).hexdigest()
    doc.source_url = "https://pubmed.ncbi.nlm.nih.gov/123/"
    doc.acquired_at = "2026-09-29T00:00:00Z"
    monkeypatch.setattr("ir_hw2.integration.load_corpus", lambda path: {"123": doc})
    target = tmp_path / "search"
    assert publish_search_copy(source, target)["published"] == 1
    sync_raw_folder(target)
    docs, index = load_snapshot(target)
    assert docs["PMID123"].source_url == doc.source_url
    assert docs["PMID123"].content_scope == "abstract"
    assert search(index, "insulin", "RELEVANCE", stemming=True).document_ids == ["PMID123"]
    assert search(index, "metadata", "RELEVANCE", stemming=True).document_ids == []
    assert original.read_bytes() == raw
    assert publish_search_copy(source, target)["library_documents"] == 1
    assert len(list((target / "raw").glob("*.xml"))) == 1
