from pathlib import Path
from unittest.mock import Mock

import pytest
import requests

from ir_hw1.corpus import PMCClient, import_bytes, import_folder
from ir_hw1.storage import load_documents, read_manifest
from ir_hw1.xml_parser import ParseError, articles_in_xml, parse_article


def sample(body='<p>Nested <italic>cancer</italic> text.</p>', namespace="", abstract='<p>Abstract only.</p>'):
    return f'''<article {namespace}><front><article-meta><article-id pub-id-type="pmc">42</article-id>
    <title-group><article-title>A <italic>study</italic></article-title></title-group>
    <abstract>{abstract}</abstract></article-meta></front><body>{body}</body>
    <floats-group><fig id="f1"><caption><p>Unique caption.</p></caption></fig></floats-group>
    <back><ref-list><ref><mixed-citation>Excludedreference.</mixed-citation></ref></ref-list></back></article>'''.encode()


def test_namespace_oai_and_nested():
    article = sample(namespace='xmlns="urn:jats"', abstract='<sec><title>Results</title><p>Nested <italic>cancer</italic> text.</p><fig id="f1"><caption><p>Unique caption.</p></caption></fig><table-wrap><table><tr><th>Group</th><td><p>Cell text</p></td></tr></table></table-wrap></sec>')
    wrapped = b'<OAI-PMH xmlns="urn:oai"><GetRecord><record><metadata>' + article + b'</metadata></record></GetRecord></OAI-PMH>'
    doc = parse_article(articles_in_xml(wrapped)[0], content_scope="abstract")
    texts = [b.text for b in doc.blocks]
    assert doc.pmcid == "PMC42" and doc.title == "A study"
    assert texts == ["Nested cancer text."]
    assert doc.blocks[0].section == "摘要 / Results"
    assert doc.back_blocks == []
    # Full-text mode still includes headings, captions and tables without duplicates.
    full = parse_article(articles_in_xml(wrapped)[0])
    full_texts = [b.text for b in full.blocks]
    assert full_texts.count("Unique caption.") == 1
    assert full_texts.count("Cell text") == 1
    assert "Results" in full_texts and "A study" in full_texts
    assert "Excludedreference." not in full_texts
    assert next(b for b in full.blocks if b.text == "Cell text").narrative is False


def test_nested_paragraph_no_duplication():
    doc = parse_article(articles_in_xml(sample(abstract='<p>Before.<list><list-item><p>Inner.</p></list-item></list>After.</p>'))[0])
    assert [b.text for b in doc.blocks if b.kind == "abstract"] == ["Before.", "Inner.", "After."]


def test_inline_citations_do_not_join_words():
    doc = parse_article(articles_in_xml(sample(abstract='<p>TBM<xref ref-type="bibr">2</xref> improved. Inter<italic>leukin</italic> works.</p>'))[0])
    assert next(b.text for b in doc.blocks if b.kind == "abstract") == "TBM 2 improved. Interleukin works."


@pytest.mark.parametrize("raw", [b"<broken", b"<article/>", sample().replace(b">42<", b">bad<"),
    b'<OAI-PMH><error code="idDoesNotExist">gone</error></OAI-PMH>',
    b'<OAI-PMH><header status="deleted"/></OAI-PMH>',
    b'<!DOCTYPE article [<!ENTITY x SYSTEM "file:///secret">]><article>&x;</article>'])
def test_invalid_xml(raw):
    with pytest.raises(ParseError):
        parse_article(articles_in_xml(raw)[0])


@pytest.mark.parametrize("body", [None, "", "   ", "<sec><title>Results</title></sec>",
                                  "<table><tr><td>Measurement</td></tr></table>"])
def test_import_and_search_available_text_without_narrative_body(tmp_path, body):
    from ir_hw1.index import load_snapshot
    from ir_hw1.library import upload_xml
    from ir_hw1.search import search

    raw = sample(body or "")
    if body is None:
        raw = raw.replace(b"<body></body>", b"")
    assert upload_xml(tmp_path, "article.xml", raw)[0]["status"] == "imported"
    documents, index = load_snapshot(tmp_path)
    doc = documents["PMC42"]
    assert search(index, "abstract").document_ids == ["PMC42"]
    assert doc.content_scope == "full"
    assert search(index, "study").document_ids == ["PMC42"]
    assert any(b.text == "Unique caption." for b in doc.blocks)
    assert any("Excludedreference." in b.text for b in doc.back_blocks)
    assert search(index, "excludedreference").document_ids == []
    assert upload_xml(tmp_path, "article.xml", raw)[0]["status"] == "duplicate"


def test_import_duplicate_update_and_failure(tmp_path):
    first = import_bytes(sample(), tmp_path, "local:test", "raw/test.xml")
    assert first[0]["status"] == "imported"
    assert import_bytes(sample(), tmp_path, "local:test", "raw/test.xml")[0]["status"] == "duplicate"
    assert import_bytes(sample('<p>Changed full text.</p>'), tmp_path, "local:test", "raw/test.xml")[0]["status"] == "updated"
    assert import_bytes(b"<broken", tmp_path, "local:broken", "raw/broken.xml")[0]["status"] == "failed"
    assert len(load_documents(tmp_path)) == 1
    assert len(read_manifest(tmp_path)) == 4


def test_folder_import_preserves_good_files(tmp_path):
    folder = tmp_path / "incoming"
    folder.mkdir()
    (folder / "good.xml").write_bytes(sample())
    (folder / "bad.xml").write_bytes(b"<broken")
    records = import_folder(folder, tmp_path / "data")
    assert sorted(r["status"] for r in records) == ["failed", "imported"]
    assert (tmp_path / "data" / records[1]["raw_path"]).exists()


def response(status, payload=b"<article/>", headers=None):
    result = Mock()
    result.status_code = status
    result.headers = headers or {}
    result.__enter__ = Mock(return_value=result)
    result.__exit__ = Mock(return_value=False)
    result.iter_content.return_value = [payload]
    if status >= 400:
        result.raise_for_status.side_effect = requests.HTTPError(f"HTTP {status}")
    return result


def test_http_backoff_and_rate_limit():
    session = Mock(headers={})
    session.get.side_effect = [response(429, headers={"Retry-After": "2"}), response(503), response(200)]
    sleeps = []
    client = PMCClient(session=session, sleeper=sleeps.append, clock=lambda: 0)
    assert client.get({"verb": "GetRecord"})[0] == b"<article/>"
    assert client.request_count == 3
    assert 2 in sleeps and 4 in sleeps and 1 in sleeps
    assert session.headers["Accept-Encoding"] == "gzip, deflate"


def test_http_permanent_failure_no_retry():
    session = Mock(headers={})
    session.get.return_value = response(404)
    with pytest.raises(requests.HTTPError):
        PMCClient(session=session, sleeper=lambda _: None).get({})
    assert session.get.call_count == 1


def test_http_timeout_bounded_and_cap():
    session = Mock(headers={})
    session.get.side_effect = requests.Timeout("offline")
    with pytest.raises(requests.Timeout):
        PMCClient(session=session, sleeper=lambda _: None).get({})
    assert session.get.call_count == 3
    with pytest.raises(ValueError, match="100"):
        PMCClient(session=session, sleeper=lambda _: None, max_requests=0).get({})


def licensed_sample(number="42"):
    return sample().replace(b">42<", f">{number}<".encode()).replace(b"</article-meta>",
        b'<permissions><license xmlns:xlink="http://www.w3.org/1999/xlink" xlink:href="https://creativecommons.org/licenses/by/4.0/"><license-p>Creative Commons Attribution</license-p></license></permissions></article-meta>')


def test_downloader_resumption_and_duplicate(tmp_path, monkeypatch):
    from ir_hw1.corpus import OAI_URL, download_corpus
    from ir_hw1.storage import write_json
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    client = Mock()
    page = b'<OAI-PMH><ListIdentifiers><header><identifier>oai:pubmedcentral.nih.gov:42</identifier></header><resumptionToken>next-page</resumptionToken></ListIdentifiers></OAI-PMH>'
    page2 = page.replace(b":42<", b":43<").replace(b">next-page<", b"><")
    client.get.side_effect = [(page, OAI_URL), (licensed_sample(), OAI_URL), (page2, OAI_URL), (licensed_sample("43"), OAI_URL)]
    monkeypatch.setattr("ir_hw1.corpus.PMCClient", lambda: client)
    assert download_corpus(tmp_path / "data", count=1)[0]["status"] == "imported"
    assert download_corpus(tmp_path / "data", count=1)[0]["pmcid"] == "PMC43"
    assert client.get.call_args_list[2].args[0] == {"verb": "ListIdentifiers", "resumptionToken": "next-page"}
    assert len(load_documents(tmp_path / "data")) == 2
    calls = client.get.call_count
    assert download_corpus(tmp_path / "data", count=1, pmcids=["PMC42"]) == []
    assert client.get.call_count == calls


def test_downloader_keeps_failed_request_pending(tmp_path, monkeypatch):
    import json
    from ir_hw1.corpus import download_corpus
    from ir_hw1.storage import write_json
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    data = tmp_path / "data"
    write_json(data / "download_state.json", {"signature": {"from": "2025-01-01", "until": "2025-01-02", "set": "pmc-open"},
        "pending": ["PMC42"], "token": "", "started": True})
    client = Mock()
    client.get.side_effect = requests.Timeout("offline")
    monkeypatch.setattr("ir_hw1.corpus.PMCClient", lambda: client)
    assert download_corpus(data, count=1)[0]["status"] == "download_failed"
    assert json.loads((data / "download_state.json").read_text())["pending"] == ["PMC42"]


def test_downloader_quarantines_unknown_license(tmp_path, monkeypatch):
    from ir_hw1.corpus import OAI_URL, download_corpus
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    client = Mock()
    client.get.return_value = (sample(), OAI_URL)
    monkeypatch.setattr("ir_hw1.corpus.PMCClient", lambda: client)
    data = tmp_path / "data"
    records = download_corpus(data, count=1, pmcids=["PMC42"])
    assert records[0]["status"] == "failed"
    assert not (data / "raw/PMC42.xml").exists()
    assert (data / "rejected/PMC42.xml").exists()
    assert not load_documents(data)


def test_downloader_wrong_id_does_not_replace_raw(tmp_path, monkeypatch):
    from ir_hw1.corpus import OAI_URL, download_corpus
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    client = Mock()
    client.get.return_value = (licensed_sample("43"), OAI_URL)
    monkeypatch.setattr("ir_hw1.corpus.PMCClient", lambda: client)
    data = tmp_path / "data"
    records = download_corpus(data, count=1, pmcids=["PMC42"])
    assert records[0]["status"] == "download_failed"
    assert not (data / "raw/PMC42.xml").exists()
