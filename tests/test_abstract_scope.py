"""Abstract-only content, search boundaries and migration from full-text snapshots."""
import hashlib

from ir_hw1.index import build_index, load_snapshot, save_index
from ir_hw1.models import Document, TextBlock
from ir_hw1.search import search
from ir_hw1.statistics import compute_statistics
from ir_hw1.storage import load_documents, save_documents, write_json
from ir_hw1.sync import PREPROCESSING, SENTENCE_VERSION, sync_raw_folder
from ir_hw1.xml_parser import PARSER_VERSION, articles_in_xml, parse_article


RAW = b'''<article><front><article-meta><article-id pub-id-type="pmc">42</article-id>
<title-group><article-title>Titleonly therapies</article-title></title-group>
<abstract><sec><title>Background</title><p>Abstract therapy works.</p></sec>
<sec><title>Results</title><p>Another result.</p></sec></abstract>
<abstract abstract-type="summary"><p>Second abstract.</p></abstract>
</article-meta></front><body><p>Bodyonly treatments.</p></body>
<floats-group><fig><caption><p>Figureonly cancers.</p></caption></fig></floats-group>
<back><ref-list><ref><mixed-citation>Referenceonly.</mixed-citation></ref></ref-list></back></article>'''


def assert_abstract_scope(docs, index):
    doc = docs["PMC42"]
    assert doc.title == "Titleonly therapies"
    assert [b.text for b in doc.blocks] == [
        "Abstract therapy works.", "Another result.", "Second abstract."]
    assert doc.blocks[0].section == "摘要 / Background"
    assert doc.back_blocks == []
    assert doc.statistics["words"] == 7
    text = "Abstract therapy works.\nAnother result.\nSecond abstract."
    assert doc.statistics["characters"] == len(text)
    assert doc.statistics["characters_no_whitespace"] == len("".join(text.split()))
    assert doc.statistics["sentences"] == 3
    for stemming in (False, True):
        for query in ("titleonly", "bodyonly", "treatment", "figureonly", "cancer", "referenceonly", "background"):
            assert search(index, query, stemming=stemming).document_ids == []
            assert search(index, query, stemming=stemming, ranking="tfidf").scores == {}
        assert search(index, "abstract", stemming=stemming).document_ids == ["PMC42"]
    assert search(index, "therapies").document_ids == []  # The title isn't indexed.
    assert search(index, "therapies", stemming=True).document_ids == ["PMC42"]
    assert search(index, "abstract therapy", "PHRASE", documents=docs).document_ids == ["PMC42"]
    assert search(index, "bodyonly treatments", "PHRASE", documents=docs).document_ids == []


def test_structured_and_multiple_abstracts_only():
    doc = parse_article(articles_in_xml(RAW)[0], content_scope="abstract")
    docs = {doc.pmcid: doc}
    assert_abstract_scope(docs, build_index(docs))


def test_abstract_word_counts_use_whitespace_without_changing_search_tokens():
    blocks = [TextBlock("b0", "abstract", "Abstract", "IgG/IgM\t4/30."),
              TextBlock("b1", "abstract", "Abstract", "n = 19 ± 2."),
              TextBlock("b2", "abstract", "Abstract", "COVID-19/SARS-CoV-2.")]
    doc = Document("PMC42", "Metadata only", blocks, content_scope="abstract")
    stats = compute_statistics(doc)
    assert stats["words"] == 8
    assert [b["words"] for b in stats["blocks"]] == [2, 5, 1]
    index = build_index({doc.pmcid: doc})
    assert sum(hits[doc.pmcid]["tf"] for hits in index["postings"].values()) == 9
    assert search(index, "igg igm", ranking="tfidf").document_ids == [doc.pmcid]
    doc.content_scope = "full"
    full = compute_statistics(doc)
    assert full["words"] == 9
    for key in ("characters", "characters_no_whitespace", "sentences"):
        assert full[key] == stats[key]


def test_v5_abstract_statistics_upgrade_preserves_retrieval_and_raw(tmp_path):
    raw = RAW.replace(b"Abstract therapy works.", b"IgG/IgM 4/30.")
    (tmp_path / "raw").mkdir()
    source = tmp_path / "raw/article.xml"
    source.write_bytes(raw)
    doc = parse_article(articles_in_xml(raw)[0], content_scope="abstract")
    doc.raw_path = "raw/article.xml"
    doc.sha256 = hashlib.sha256(raw).hexdigest()
    # v5 counted tokenizer terms: four in the first paragraph, eight in total.
    doc.statistics["words"] = 8
    doc.statistics["blocks"][0]["words"] = 4
    docs = {doc.pmcid: doc}
    save_documents(tmp_path, docs)
    previous = build_index(docs)
    previous["parser"] = "jats-source-scope-v5"
    save_index(tmp_path, previous)
    write_json(tmp_path / "raw_sync_state.json", {
        "policy": {"parser": "jats-source-scope-v5", "sentence_rules": SENTENCE_VERSION,
                   "preprocessing": PREPROCESSING},
        "files": {doc.raw_path: {"sha256": doc.sha256,
                  "records": [{"pmcid": doc.pmcid, "status": "imported"}]}},
    })
    assert sync_raw_folder(tmp_path).rebuilt
    current, index = load_snapshot(tmp_path)
    assert current[doc.pmcid].statistics["words"] == 6
    assert current[doc.pmcid].statistics["blocks"][0]["words"] == 2
    for key in ("postings", "porter_postings", "tfidf", "porter_tfidf"):
        assert index[key] == previous[key]
    assert source.read_bytes() == raw
    assert not sync_raw_folder(tmp_path).rebuilt


def test_full_scope_keeps_headings_and_empty_abstract_does_not_count_them():
    full = parse_article(articles_in_xml(RAW)[0])
    assert any(b.kind == "heading" and b.text == "Background" for b in full.blocks)
    empty = RAW.replace(b'<p>Abstract therapy works.</p>', b'').replace(b'<p>Another result.</p>', b'')
    empty = empty.replace(b'<p>Second abstract.</p>', b'')
    doc = parse_article(articles_in_xml(empty)[0], content_scope="abstract")
    assert doc.blocks == []
    assert doc.statistics["characters"] == doc.statistics["words"] == doc.statistics["sentences"] == 0


def test_upgrade_replaces_old_content_and_both_indexes_without_changing_raw(tmp_path):
    (tmp_path / "raw").mkdir()
    source = tmp_path / "raw/article.xml"
    source.write_bytes(RAW)
    sync_raw_folder(tmp_path)
    docs = load_documents(tmp_path)
    doc = docs["PMC42"]
    doc.content_scope = "abstract"
    # Reproduce the previous published snapshot while leaving the raw XML intact.
    doc.blocks += [TextBlock("old-title", "title", "Title", doc.title, False),
                   TextBlock("old-body", "body", "Body", "Bodyonly treatments.")]
    doc.back_blocks = [TextBlock("old-back", "back", "References", "Referenceonly.")]
    doc.statistics = compute_statistics(doc)
    save_documents(tmp_path, docs)
    old_index = build_index(docs)
    old_index["parser"] = "jats-source-scope-v4"
    save_index(tmp_path, old_index)
    write_json(tmp_path / "raw_sync_state.json", {
        "policy": {"parser": "jats-source-scope-v4", "sentence_rules": SENTENCE_VERSION,
                   "preprocessing": PREPROCESSING},
        "files": {"raw/article.xml": {"sha256": hashlib.sha256(RAW).hexdigest(),
                  "records": [{"pmcid": "PMC42", "status": "imported"}]}},
    })
    result = sync_raw_folder(tmp_path)
    assert result.rebuilt and not result.errors
    current, index = load_snapshot(tmp_path)
    assert index["parser"] == PARSER_VERSION
    assert_abstract_scope(current, index)
    assert source.read_bytes() == RAW
    snapshot = (tmp_path / "index.json").read_bytes()
    assert not sync_raw_folder(tmp_path).rebuilt
    assert (tmp_path / "index.json").read_bytes() == snapshot
