"""Management tests use fabricated IDs only inside temporary directories."""
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests
from streamlit.testing.v1 import AppTest

from ir_hw1.corpus import OAI_URL, import_folder
from ir_hw1.index import load_snapshot
from ir_hw1.library import (ID_CONVERTER_URL, delete_articles, download_pmid, normalize_pmid,
                            resolve_pmid, restore_articles, upload_xml)
from ir_hw1.search import search
from ir_hw1.storage import load_deleted, load_documents, read_manifest
from ir_hw1.sync import sync_raw_folder

APP = Path(__file__).resolve().parents[1] / "app.py"
FIXTURE = Path(__file__).parent / "fixtures/synthetic.xml"


def fulltext(pmcid="99", pmid="999", license=True):
    permissions = '<permissions><license xmlns:xlink="http://www.w3.org/1999/xlink" xlink:href="https://creativecommons.org/licenses/by/4.0/">CC BY</license></permissions>' if license else ""
    return f'<article xml:lang="en"><front><article-meta><article-id pub-id-type="pmc">{pmcid}</article-id><article-id pub-id-type="pmid">{pmid}</article-id><title-group><article-title>Example</article-title></title-group>{permissions}<abstract><p>Therapies and cancer treatment.</p></abstract></article-meta></front><body><p>Excluded body.</p></body></article>'.encode()


def conversion(**overrides):
    record = {"requested-id": "999", "pmid": 999, "pmcid": "PMC99"}
    record.update(overrides)
    return json.dumps({"status": "ok", "records": [record]}).encode(), ID_CONVERTER_URL


def test_upload_updates_search_and_deduplicates_safely(tmp_path):
    records = upload_xml(tmp_path, "../../anything.XML", fulltext())
    assert records[0]["status"] == "imported"
    docs, index = load_snapshot(tmp_path)
    assert search(index, "cancer treatment", "AND").document_ids == ["PMC99"]
    assert search(index, "therapy", stemming=True).document_ids == ["PMC99"]
    assert (tmp_path / docs["PMC99"].raw_path).is_file()
    assert not (tmp_path.parent / "anything.XML").exists()
    assert docs["PMC99"].source_url == "upload:anything.XML"
    assert upload_xml(tmp_path, "same.xml", fulltext())[0]["status"] == "duplicate"
    assert len(list((tmp_path / "raw").glob("*.xml"))) == 1
    upload_xml(tmp_path, "update.xml", fulltext().replace(b"cancer", b"kidney"))
    assert search(load_snapshot(tmp_path)[1], "kidney").document_ids == ["PMC99"]
    sync_raw_folder(tmp_path)  # Existing imported raw versions must not overwrite the updated snapshot.
    assert search(load_snapshot(tmp_path)[1], "cancer").document_ids == []


def test_upload_invalid_file_keeps_good_snapshot(tmp_path):
    upload_xml(tmp_path, "good.xml", fulltext())
    before = (tmp_path / "processed/articles.jsonl").read_bytes()
    assert upload_xml(tmp_path, "bad.xml", b"<unclosed>")[0]["status"] == "failed"
    assert (tmp_path / "processed/articles.jsonl").read_bytes() == before
    assert len(list((tmp_path / "raw").glob("*.xml"))) == 1
    with pytest.raises(ValueError):
        upload_xml(tmp_path, "paper.pdf", fulltext())
    with pytest.raises(ValueError):
        upload_xml(tmp_path, "empty.xml", b"")


def test_delete_one_from_collection_survives_sync_cli_and_restart(tmp_path):
    upload_xml(tmp_path, "collection.xml", FIXTURE.read_bytes())
    sync_raw_folder(tmp_path)
    assert delete_articles(tmp_path, ["PMC2"]) == 1
    for _ in range(2):
        sync_raw_folder(tmp_path)
        assert search(load_snapshot(tmp_path)[1], "cancer treatment", "AND").document_ids == []
        assert set(load_documents(tmp_path)) == {"PMC1", "PMC3"}
    # Losing the disposable sync cache or rebuilding from raw cannot resurrect it.
    (tmp_path / "raw_sync_state.json").unlink()
    import_folder(tmp_path / "raw", tmp_path)
    sync_raw_folder(tmp_path)
    assert set(load_documents(tmp_path)) == {"PMC1", "PMC3"}
    assert set(load_deleted(tmp_path)) == {"PMC2"}
    assert restore_articles(tmp_path, ["PMC2"]) == 1
    assert search(load_snapshot(tmp_path)[1], "cancer treatment", "AND").document_ids == ["PMC2"]
    assert not load_deleted(tmp_path)


def test_delete_all_and_explicit_reupload(tmp_path):
    upload_xml(tmp_path, "article.xml", fulltext())
    assert delete_articles(tmp_path, ["PMC99", "PMC99"]) == 1
    sync_raw_folder(tmp_path)
    assert not load_documents(tmp_path)
    index = json.loads((tmp_path / "index.json").read_text())
    assert not index["postings"] and not index["porter_postings"]
    assert delete_articles(tmp_path, ["PMC99"]) == 0
    assert upload_xml(tmp_path, "again.xml", fulltext())[0]["restored"]
    assert list(load_snapshot(tmp_path)[0]) == ["PMC99"]


@pytest.mark.parametrize("value", ["", "cancer", "PMC99", "123,456", "-1", "0", "１２３"])
def test_pmid_input_rejects_other_ids(value):
    with pytest.raises(ValueError):
        normalize_pmid(value)


@pytest.mark.parametrize("record,message", [
    ({"pmcid": ""}, "找不到"), ({"status": "error"}, "找不到"),
    ({"live": False, "release-date": "2099-01-01"}, "尚未公開"),
    ({"pmid": "1000"}, "不一致"),
])
def test_pmid_unavailable_and_identity(record, message):
    client = Mock()
    client.get.return_value = conversion(**record)
    with pytest.raises(ValueError, match=message):
        resolve_pmid(client, "999")
    assert client.get.call_args.kwargs == {"endpoint": ID_CONVERTER_URL}
    assert client.get.call_args.args[0]["idtype"] == "pmid"


@pytest.mark.parametrize("response", [b"not json", b"[]", b'{"status":"error"}', b'{"status":"ok","records":null}'])
def test_conversion_invalid_response(response):
    client = Mock()
    client.get.return_value = response, ID_CONVERTER_URL
    with pytest.raises(ValueError, match="格式異常"):
        resolve_pmid(client, "999")


def test_pmid_download_deduplicate_and_restore(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    client = Mock()
    client.get.side_effect = [(fulltext(), OAI_URL)] * 2
    monkeypatch.setattr("ir_hw1.library.PMCClient", lambda: client)
    assert download_pmid(tmp_path, "PMID: 999")[0]["status"] == "imported"
    assert load_snapshot(tmp_path)[0]["PMC99"].pmid == "999"
    assert download_pmid(tmp_path, "999")[0]["status"] == "duplicate"
    assert client.get.call_count == 1
    delete_articles(tmp_path, ["PMC99"])
    assert download_pmid(tmp_path, "999")[0]["restored"]
    assert list(load_snapshot(tmp_path)[0]) == ["PMC99"]
    assert client.session.close.call_count == 2
    assert read_manifest(tmp_path)[-1]["status"] == "imported"


@pytest.mark.parametrize("raw,message", [(fulltext("100"), "不一致"),
                                        (fulltext(license=False), "授權"), (b"<broken>", "XML")])
def test_download_bad_fulltext_does_not_leak_into_autosync(tmp_path, monkeypatch, raw, message):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    client = Mock()
    client.get.return_value = (raw, OAI_URL)
    monkeypatch.setattr("ir_hw1.library.PMCClient", lambda: client)
    result = download_pmid(tmp_path, "PMC99")[0]
    assert result["status"] == "download_failed" and message in result["reason"]
    sync_raw_folder(tmp_path)
    assert not load_documents(tmp_path) and not list((tmp_path / "raw").glob("*.xml"))
    client.session.close.assert_called_once()


def test_download_network_failure_logged(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    client = Mock()
    client.get.side_effect = requests.Timeout("offline")
    monkeypatch.setattr("ir_hw1.library.PMCClient", lambda: client)
    assert "網路" in download_pmid(tmp_path, "999")[0]["reason"]
    assert read_manifest(tmp_path)[-1]["status"] == "download_failed"


def test_ui_management_empty_download_delete_restore(tmp_path, monkeypatch):
    monkeypatch.setenv("IR_HW1_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    client = Mock()
    client.get.return_value = (fulltext(), OAI_URL)
    monkeypatch.setattr("ir_hw1.library.PMCClient", lambda: client)
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    app.radio(key="view").set_value("文章管理").run()
    assert not app.exception
    app.button(key="import_xml").click().run()
    assert any("先選擇 XML" in w.value for w in app.warning)
    app.text_input(key="download_pmid").set_value("999")
    app.button(key="fetch_pmid").click().run()
    assert not app.exception and len(load_documents(tmp_path)) == 1
    app.radio(key="view").set_value("搜尋文章").run()
    app.text_input(key="query").set_value("therapy")
    assert not any(t.key == "stemming" for t in app.toggle)
    app.button[0].click().run()
    assert any(m.label == "符合文章" and m.value == "1" for m in app.metric)
    app.radio(key="view").set_value("文章管理").run()
    app.radio(key="view").set_value("搜尋文章").run()
    assert app.text_input(key="query").value == "therapy"
    assert not any(t.key == "stemming" for t in app.toggle)
    assert any(m.label == "符合文章" and m.value == "1" for m in app.metric)
    app.radio(key="view").set_value("文章管理").run()
    app.button(key="active_all").click().run()
    app.button(key="delete_articles").click().run()
    assert not app.exception and not load_documents(tmp_path)
    again = AppTest.from_file(str(APP), default_timeout=30).run()
    again.radio(key="view").set_value("文章管理").run()
    again.button(key="trash_all").click().run()
    again.button(key="restore_articles").click().run()
    assert not again.exception and len(load_documents(tmp_path)) == 1
