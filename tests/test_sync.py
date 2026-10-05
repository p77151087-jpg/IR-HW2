"""Automatic folder import; all fabricated PMCID content stays in tmp_path."""
import os
import socket
import hashlib
from pathlib import Path

import pytest
from filelock import FileLock, Timeout
from streamlit.testing.v1 import AppTest

from ir_hw1 import sync
from ir_hw1.corpus import import_folder
from ir_hw1.index import build_index, load_snapshot, save_index
from ir_hw1.search import search
from ir_hw1.storage import load_documents, read_manifest, write_json

FIXTURE = Path(__file__).parent / "fixtures/synthetic.xml"
APP = Path(__file__).resolve().parents[1] / "app.py"


def seed(data_dir):
    raw = data_dir / "raw"
    raw.mkdir(parents=True)
    path = raw / "articles.XML"
    path.write_bytes(FIXTURE.read_bytes())
    return path


def snapshots(data_dir):
    return {name: ((data_dir / name).read_bytes(), (data_dir / name).stat().st_mtime_ns)
            for name in ["processed/articles.jsonl", "index.json", "manifest.jsonl", "raw_sync_state.json"]}


def test_raw_only_boot_noop_and_same_size_timestamp_edit(tmp_path, monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", lambda *a: pytest.fail("Synchronization must stay offline"))
    path = seed(tmp_path)
    first = sync.sync_raw_folder(tmp_path)
    assert (first.imported, first.rebuilt, first.errors) == (3, True, [])
    docs, index = load_snapshot(tmp_path)
    assert set(docs) == {"PMC1", "PMC2", "PMC3"}
    assert search(index, "cancer treatment", "AND").document_ids == ["PMC2"]
    before = snapshots(tmp_path)
    assert not sync.sync_raw_folder(tmp_path).rebuilt
    assert snapshots(tmp_path) == before
    stat = path.stat()
    path.write_bytes(path.read_bytes().replace(b"Cancer", b"Kidney"))
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert path.stat().st_size == stat.st_size
    changed = sync.sync_raw_folder(tmp_path)
    assert (changed.updated, changed.rebuilt) == (3, True)
    _, index = load_snapshot(tmp_path)
    assert search(index, "kidney", "AND").document_ids == ["PMC1", "PMC2"]
    assert search(index, "cancer", "OR").document_ids == []


def test_existing_corpus_bootstrap_preserves_provenance(tmp_path):
    seed(tmp_path)
    import_folder(tmp_path / "raw", tmp_path)
    save_index(tmp_path, build_index(load_documents(tmp_path)))
    original = {n: (tmp_path / n).read_bytes() for n in ["manifest.jsonl", "processed/articles.jsonl", "index.json"]}
    assert not sync.sync_raw_folder(tmp_path).rebuilt
    assert all((tmp_path / name).read_bytes() == raw for name, raw in original.items())


@pytest.mark.parametrize("index_content", [None, "{", "[]", '{"version": -1}'])
def test_missing_corrupt_stale_index_repaired(tmp_path, index_content):
    seed(tmp_path)
    sync.sync_raw_folder(tmp_path)
    if index_content is None:
        (tmp_path / "index.json").unlink()
    else:
        (tmp_path / "index.json").write_text(index_content, encoding="utf-8")
    assert sync.sync_raw_folder(tmp_path).rebuilt
    assert len(load_snapshot(tmp_path)[0]) == 3


def test_invalid_new_file_preserves_corpus_logs_once_and_recovers(tmp_path):
    seed(tmp_path)
    sync.sync_raw_folder(tmp_path)
    bad = tmp_path / "raw/broken.xml"
    bad.write_text("<broken>", encoding="utf-8")
    failed = sync.sync_raw_folder(tmp_path)
    assert not failed.rebuilt and len(failed.errors) == 1
    before = snapshots(tmp_path)
    assert sync.sync_raw_folder(tmp_path).errors == failed.errors
    assert snapshots(tmp_path) == before
    bad.write_bytes(FIXTURE.read_bytes().replace(b'>1</article-id>', b'>4</article-id>'))
    assert sync.sync_raw_folder(tmp_path).imported == 1
    assert len(load_snapshot(tmp_path)[0]) == 4
    assert not sync.sync_raw_folder(tmp_path).rebuilt  # Repeated PMCID remains deduplicated.
    bad.unlink()
    assert sync.sync_raw_folder(tmp_path).rebuilt
    assert len(load_snapshot(tmp_path)[0]) == 3


def test_oversize_file_logs_once_then_recovers(tmp_path, monkeypatch):
    path = seed(tmp_path)
    with monkeypatch.context() as patch:
        patch.setattr(sync, "MAX_XML_BYTES", 10)
        assert "25 MiB" in sync.sync_raw_folder(tmp_path).errors[0]
        sync.sync_raw_folder(tmp_path)
        assert len(read_manifest(tmp_path)) == 1
    assert sync.sync_raw_folder(tmp_path).imported == 3
    assert path.exists()


def test_parser_version_change_reimports_source(tmp_path, monkeypatch):
    seed(tmp_path)
    sync.sync_raw_folder(tmp_path)
    original = sync.import_bytes
    calls = []
    def observed(*args, **kwargs):
        calls.append(args[3])
        return original(*args, **kwargs)
    monkeypatch.setattr(sync, "PARSER_VERSION", "new-rule-for-test")
    monkeypatch.setattr(sync, "import_bytes", observed)
    sync.sync_raw_folder(tmp_path)
    assert calls == ["raw/articles.XML"]


def test_parser_upgrade_retries_rejected_article_in_empty_library(tmp_path):
    raw = b'<article><front><article-meta><article-id pub-id-type="pmc">700</article-id><title-group><article-title>Available article</article-title></title-group><abstract><p>Available abstract.</p></abstract></article-meta></front></article>'
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw/article.xml").write_bytes(raw)
    write_json(tmp_path / "raw_sync_state.json", {
        "policy": {"parser": "jats-blocks-v1", "sentence_rules": sync.SENTENCE_VERSION,
                   "preprocessing": sync.PREPROCESSING},
        "files": {"raw/article.xml": {"sha256": hashlib.sha256(raw).hexdigest(),
                  "records": [{"pmcid": "", "status": "failed", "reason": "缺少實際正文"}]}},
    })
    result = sync.sync_raw_folder(tmp_path)
    assert result.imported == 1 and not result.errors
    documents, index = load_snapshot(tmp_path)
    assert set(documents) == {"PMC700"}
    assert search(index, "abstract").document_ids == ["PMC700"]
    before = snapshots(tmp_path)
    sync.sync_raw_folder(tmp_path)
    assert snapshots(tmp_path) == before


def test_busy_writer_leaves_files_untouched(tmp_path):
    seed(tmp_path)
    with FileLock(str(tmp_path / ".writer.lock")):
        with pytest.raises(Timeout):
            sync.sync_raw_folder(tmp_path)
    assert not (tmp_path / "index.json").exists()


def test_ui_raw_only_refresh_new_article_and_fresh_session(tmp_path, monkeypatch):
    seed(tmp_path)
    monkeypatch.setenv("IR_HW1_DATA_DIR", str(tmp_path))
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    assert not app.exception
    assert any("自動更新" in s.value for s in app.success)
    app.text_input(key="query").set_value("cancer treatment")
    app.button[0].click().run()
    assert any(m.label == "符合文章" and m.value == "3" for m in app.metric)
    (tmp_path / "raw/new.xml").write_bytes(FIXTURE.read_bytes().replace(b'>2</article-id>', b'>4</article-id>'))
    app.run()
    assert not app.exception
    assert any(m.label == "符合文章" and m.value == "4" for m in app.metric)
    app.button(key="open_PMC4").click().run()
    assert any(m.label == "單字數" and m.value == "3" for m in app.metric)
    again = AppTest.from_file(str(APP), default_timeout=30).run()
    assert not again.exception and not again.success
    again.radio(key="view").set_value("語料概覽").run()
    assert any(m.value == "4" for m in again.metric)
