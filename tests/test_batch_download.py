"""Batch requests must improve latency without admitting unrelated/rejected XML."""
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests
from streamlit.testing.v1 import AppTest

from ir_hw1 import library
from ir_hw1.corpus import PMCClient
from ir_hw1.index import load_snapshot
from ir_hw1.storage import StorageError, load_documents, read_manifest
from ir_hw1.sync import sync_raw_folder
from tests.test_pmid_list import APP, pubmed, pubmed_set


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    client = Mock()
    monkeypatch.setattr(library, "PMCClient", lambda: client)
    return client


def test_ten_pmids_one_request_one_index_update(tmp_path, monkeypatch, client):
    ids = [str(n) for n in range(101, 111)]
    client.get.return_value = pubmed_set(*reversed(ids)), library.PUBMED_URL
    refresh = Mock(wraps=library.refresh_index)
    monkeypatch.setattr(library, "refresh_index", refresh)
    results = library.download_pmids(tmp_path, ids)
    assert [r["pmid"] for r in results] == ids
    assert all(r["status"] == "imported" for r in results)
    assert client.get.call_count == refresh.call_count == 1
    assert len(load_snapshot(tmp_path)[0]) == 10
    monkeypatch.setattr(library, "PMCClient", lambda: pytest.fail("All exist: no new client"))
    assert all(r["status"] == "duplicate" for r in library.download_pmids(tmp_path, ids))


def test_rejected_foreign_and_duplicate_ids_never_enter_raw(tmp_path, client):
    foreign_language = pubmed("1000").replace(b">eng<", b">fre<")
    raw = pubmed_set("999", "1001", "1001", "888").replace(b"</PubmedArticleSet>", foreign_language.removeprefix(b"<PubmedArticleSet>"))
    client.get.return_value = raw, library.PUBMED_URL
    results = library.download_pmids(tmp_path, ["999", "1000", "1001", "1002"])
    assert [r["status"] for r in results] == ["imported"] + ["download_failed"] * 3
    sync_raw_folder(tmp_path)
    assert list(load_documents(tmp_path)) == ["PMID999"]
    assert len(list((tmp_path / "raw").glob("*.xml"))) == 1


@pytest.mark.parametrize("exc", [requests.ConnectionError("offline"), requests.Timeout("slow"), ValueError("service unavailable")])
def test_service_failure_stops_remaining_chunks(tmp_path, client, exc):
    client.get.side_effect = exc
    records = library.download_pmids(tmp_path, [str(n) for n in range(1, 51)])
    assert client.get.call_count == 1
    assert len(records) == 50 and all(r["status"] == "download_failed" for r in records)
    assert not load_documents(tmp_path)


def test_real_retry_budget_is_not_multiplied_by_articles(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    session = Mock(headers={})
    session.get.side_effect = requests.ConnectionError("offline")
    sleeps = []
    client = PMCClient(session=session, sleeper=sleeps.append, clock=lambda: 0)
    monkeypatch.setattr(library, "PMCClient", lambda: client)
    records = library.download_pmids(tmp_path, [str(n) for n in range(1, 51)])
    assert len(records) == 50
    assert session.get.call_count == 3
    assert sum(sleeps) == 8  # Two backoffs plus simulated request spacing, once for the batch.


def test_prior_chunk_survives_later_transport_failure(tmp_path, monkeypatch, client):
    monkeypatch.setattr(library, "PMIDS_PER_REQUEST", 2)
    client.get.side_effect = [(pubmed_set("999", "1000"), library.PUBMED_URL), requests.Timeout()]
    results = library.download_pmids(tmp_path, ["999", "1000", "1001", "1002", "1003"])
    assert [r["status"] for r in results] == ["imported"] * 2 + ["download_failed"] * 3
    assert len(load_snapshot(tmp_path)[0]) == 2
    assert client.get.call_count == 2


def test_storage_failure_is_not_reported_as_network_failure(tmp_path, monkeypatch, client):
    client.get.return_value = pubmed_set("999", "1000"), library.PUBMED_URL
    real_import = library.import_bytes
    def fail_second(raw, *args, **kwargs):
        if b"<PMID>1000</PMID>" in raw:
            raise StorageError("disk failure")
        return real_import(raw, *args, **kwargs)
    monkeypatch.setattr(library, "import_bytes", fail_second)
    with pytest.raises(StorageError, match="disk failure"):
        library.download_pmids(tmp_path, ["999", "1000"])
    assert list(load_snapshot(tmp_path)[0]) == ["PMID999"]
    assert not any(r["status"] == "download_failed" for r in read_manifest(tmp_path))


def test_offline_demo_blocks_download_immediately_and_disables_ui(tmp_path, monkeypatch):
    monkeypatch.setenv("IR_HW1_OFFLINE_DEMO", "1")
    monkeypatch.setenv("IR_HW1_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(library, "PMCClient", lambda: pytest.fail("Offline demo must not attempt HTTP"))
    for call, value in [(library.download_pmid, "999"), (library.download_pmids, ["999"])]:
        with pytest.raises(ValueError, match="離線展示模式"):
            call(tmp_path, value)
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    app.radio(key="view").set_value("文章管理").run()
    assert not app.exception
    assert app.button(key="fetch_pmid").disabled
    assert app.button(key="fetch_pmid_list").disabled
    assert any("離線展示模式" in w.value for w in app.warning)
