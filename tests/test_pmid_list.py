"""PMID text exports are validated before serial, persistent batch imports."""
import io
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests
import streamlit as st
from filelock import FileLock, Timeout
from streamlit.testing.v1 import AppTest

from ir_hw1.corpus import PMCClient
from ir_hw1.index import load_snapshot
from ir_hw1.library import PUBMED_URL, delete_articles, download_pmids
from ir_hw1.pmid_list import MAX_LIST_BYTES, parse_pmid_list
from ir_hw1.search import search
from ir_hw1.storage import load_documents, load_deleted, read_manifest
from ir_hw1.sync import sync_raw_folder

APP = Path(__file__).resolve().parents[1] / "app.py"


def pubmed(pmid):
    return (f'<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>{pmid}</PMID>'
            '<Article><ArticleTitle>Titleonly</ArticleTitle><Abstract><AbstractText>'
            'COVID-19 antibodies respond.</AbstractText></Abstract><Language>eng</Language></Article>'
            '</MedlineCitation></PubmedArticle></PubmedArticleSet>').encode()


def pubmed_set(*pmids):
    return b"<PubmedArticleSet>" + b"".join(pubmed(pmid).removeprefix(b"<PubmedArticleSet>").removesuffix(b"</PubmedArticleSet>") for pmid in pmids) + b"</PubmedArticleSet>"


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig", "utf-16"])
def test_list_encodings_blank_lines_duplicates_and_order(encoding):
    parsed = parse_pmid_list(" 33126180\r\n\nPMID: 39283431\n33126180\n".encode(encoding))
    assert parsed.pmids == ["33126180", "39283431"]
    assert parsed.duplicates == 1


@pytest.mark.parametrize("raw,message", [
    (b"", "沒有 PMID"), (b" \n\r\n", "沒有 PMID"), (b"999\nPMC42", "第 2 行"),
    (b"999,1000", "第 1 行"), (b"999\n0\n-1", "第 2、3 行"),
    ("１２３".encode(), "不是有效 PMID"), (b"\x80", "編碼"),
    (b"1" * (MAX_LIST_BYTES + 1), "1 MiB"),
    ("\n".join(str(x) for x in range(1, 102)).encode(), "最多 100"),
], ids=["empty", "blank", "pmcid", "csv", "nonpositive", "unicode", "encoding", "oversize", "too-many"])
def test_invalid_files_rejected(raw, message):
    with pytest.raises(ValueError, match=message):
        parse_pmid_list(raw)


@pytest.mark.parametrize("values", [[], ["999", "bad"], [str(x) for x in range(1, 102)]])
def test_batch_validates_every_id_before_creating_data(tmp_path, monkeypatch, values):
    monkeypatch.setattr("ir_hw1.library.PMCClient", lambda: pytest.fail("No network for invalid input"))
    data_dir = tmp_path / "data"
    with pytest.raises(ValueError):
        download_pmids(data_dir, values)
    assert not data_dir.exists()


def test_partial_failure_dedupe_retry_restore_and_offline_reload(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    client = Mock()
    client.get.side_effect = [(pubmed_set("1001", "999"), PUBMED_URL)]
    factory = Mock(return_value=client)
    monkeypatch.setattr("ir_hw1.library.PMCClient", factory)
    progress = Mock()
    records = download_pmids(tmp_path, ["999", "1000", "999", "1001"], progress=progress)
    assert [r["status"] for r in records] == ["imported", "download_failed", "imported"]
    assert [r["pmid"] for r in records] == ["999", "1000", "1001"]
    assert factory.call_count == 1 and client.get.call_count == 1
    assert client.get.call_args.args[0]["id"] == "999,1000,1001"
    client.session.close.assert_called_once()
    assert progress.call_args.args == (3, 3, "1001")
    docs, index = load_snapshot(tmp_path)
    assert all(d.content_scope == "abstract" for d in docs.values())
    assert all(d.statistics["words"] == 3 for d in docs.values())
    assert search(index, "antibody", "RELEVANCE", stemming=True).document_ids == ["PMID999", "PMID1001"]
    assert search(index, "titleonly", "RELEVANCE", stemming=True).document_ids == []
    assert any(r["status"] == "download_failed" and r["pmid"] == "1000" for r in read_manifest(tmp_path))
    client.get.side_effect = [(pubmed("1000"), PUBMED_URL)]
    again = download_pmids(tmp_path, ["999", "1000", "1001"])
    assert [r["status"] for r in again] == ["duplicate", "imported", "duplicate"]
    assert client.get.call_count == 2  # Retry fetches only the failed PMID.
    assert client.get.call_args.args[0]["id"] == "1000"
    delete_articles(tmp_path, ["PMID1000"])
    client.get.side_effect = [(pubmed("1000"), PUBMED_URL)]
    assert download_pmids(tmp_path, ["1000"])[0]["restored"]
    assert not load_deleted(tmp_path)
    monkeypatch.setattr("socket.socket.connect", lambda *a, **k: pytest.fail("Offline reload"))
    sync_raw_folder(tmp_path)
    assert len(load_snapshot(tmp_path)[0]) == 3


def test_shared_client_preserves_rate_and_attempt_budget(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr("ir_hw1.library.PMIDS_PER_REQUEST", 2)
    session = Mock()
    def get(endpoint, *, params, **kwargs):
        response = Mock(status_code=200)
        response.iter_content.return_value = [pubmed_set(*params["id"].split(","))]
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        return response
    session.get.side_effect = get
    sleeps = []
    client = PMCClient(session=session, sleeper=sleeps.append, clock=lambda: 0, max_requests=2)
    monkeypatch.setattr("ir_hw1.library.PMCClient", lambda: client)
    records = download_pmids(tmp_path, ["999", "1000", "1001", "1002", "1003", "1004"])
    assert [r["status"] for r in records] == ["imported"] * 4 + ["download_failed"] * 2
    assert client.request_count == session.get.call_count == 2
    assert sleeps == [0, 1.0]
    assert all("請求上限" in r["reason"] for r in records[4:])


def test_batch_writer_lock_rejects_concurrent_update(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr("ir_hw1.library.PMCClient", lambda: pytest.fail("No network while locked"))
    with FileLock(str(tmp_path / ".writer.lock")):
        with pytest.raises(Timeout):
            download_pmids(tmp_path, ["999"])


def test_ui_list_preview_download_feedback_search_and_restart(tmp_path, monkeypatch):
    monkeypatch.setenv("IR_HW1_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    client = Mock()
    client.get.side_effect = [(pubmed("999"), PUBMED_URL)]
    monkeypatch.setattr("ir_hw1.library.PMCClient", lambda: client)
    real_uploader = st.file_uploader
    uploaded = {"raw": None}
    def uploader(*args, **kwargs):
        if kwargs.get("key", "").startswith("pmid_list_upload_"):
            return None if uploaded["raw"] is None else io.BytesIO(uploaded["raw"])
        return real_uploader(*args, **kwargs)
    monkeypatch.setattr(st, "file_uploader", uploader)
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    app.radio(key="view").set_value("文章管理").run()
    assert app.button(key="fetch_pmid_list").disabled
    uploaded["raw"] = b"999\nbad"
    app.run()
    assert any("第 2 行" in w.value for w in app.warning)
    assert app.button(key="fetch_pmid_list").disabled
    client.get.assert_not_called()
    uploaded["raw"] = b"999\n1000\n999\n"
    app.run()
    assert any("2 個不同 PMID" in c.value and "1 個重複" in c.value for c in app.caption)
    app.button(key="fetch_pmid_list").click().run()
    assert not app.exception
    assert any("新增／更新 1 篇" in s.value and "失敗 1 篇" in s.value for s in app.success)
    assert any("部分文章未能加入" in w.value for w in app.warning)
    assert client.get.call_count == 1
    app.run()
    assert client.get.call_count == 1  # A rerun is not a second download.
    app.radio(key="view").set_value("搜尋文章").run()
    app.text_input(key="query").set_value("antibody")
    app.button[0].click().run()
    assert any(m.label == "符合文章" and m.value == "1" for m in app.metric)
    monkeypatch.setattr("socket.socket.connect", lambda *a, **k: pytest.fail("Offline restart"))
    fresh = AppTest.from_file(str(APP), default_timeout=30).run()
    fresh.text_input(key="query").set_value("covid")
    fresh.button[0].click().run()
    assert not fresh.exception
    assert any(m.label == "符合文章" and m.value == "1" for m in fresh.metric)
