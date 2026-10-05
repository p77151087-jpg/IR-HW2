"""Permanent-deletion tests operate only on disposable synthetic corpora."""
import hashlib
import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from ir_hw1.index import load_snapshot
from ir_hw1.library import delete_articles, restore_articles, upload_xml
from ir_hw1.purge import purge_articles
from ir_hw1.search import search
from ir_hw1.storage import StorageError, load_deleted, load_documents, read_manifest
from ir_hw1.sync import sync_raw_folder
from ir_hw1.xml_parser import articles_in_xml, parse_article

FIXTURE = Path(__file__).parent / "fixtures/synthetic.xml"
APP = Path(__file__).resolve().parents[1] / "app.py"


def test_purge_single_removes_all_versions_and_allows_explicit_reimport(tmp_path):
    from xml.etree import ElementTree as ET
    raw = ET.tostring(articles_in_xml(FIXTURE.read_bytes())[0])
    upload_xml(tmp_path, "article.xml", raw)
    upload_xml(tmp_path, "new.xml", raw.replace(b"Cancer", b"Kidney"))
    (tmp_path / "raw/copy.XML").write_bytes(raw)
    deleted_id = parse_article(articles_in_xml(raw)[0]).pmcid
    assert purge_articles(tmp_path, [deleted_id]) == 0  # Live articles cannot be purged directly.
    delete_articles(tmp_path, [deleted_id])
    assert purge_articles(tmp_path, [deleted_id, deleted_id]) == 1
    assert not list((tmp_path / "raw").iterdir())
    assert not load_deleted(tmp_path) and not load_documents(tmp_path)
    assert not (tmp_path / "purge_pending.json").exists()
    sync_raw_folder(tmp_path)
    assert not json.loads((tmp_path / "index.json").read_text())["porter_postings"]
    assert restore_articles(tmp_path, [deleted_id]) == 0
    assert read_manifest(tmp_path)[-1]["status"] == "purged"
    upload_xml(tmp_path, "again.xml", raw)
    assert deleted_id in load_documents(tmp_path)


def test_shared_xml_preserves_live_and_trashed_siblings_and_latest_version(tmp_path):
    from xml.etree import ElementTree as ET
    upload_xml(tmp_path, "collection.xml", FIXTURE.read_bytes())
    original = load_documents(tmp_path)
    shared_path = tmp_path / original["PMC1"].raw_path
    newer = ET.tostring(articles_in_xml(FIXTURE.read_bytes())[2]).replace(b"Treatment", b"Kidney")
    upload_xml(tmp_path, "newer.xml", newer)
    latest = load_documents(tmp_path)["PMC3"].to_dict()
    delete_articles(tmp_path, ["PMC1", "PMC2"])
    assert purge_articles(tmp_path, ["PMC2"]) == 1
    assert {parse_article(n).pmcid for n in articles_in_xml(shared_path.read_bytes())} == {"PMC1", "PMC3"}
    assert load_documents(tmp_path)["PMC3"].to_dict() == latest
    sync_raw_folder(tmp_path)
    assert load_documents(tmp_path)["PMC3"].to_dict() == latest
    assert search(load_snapshot(tmp_path)[1], "kidney").document_ids == ["PMC3"]
    assert set(load_deleted(tmp_path)) == {"PMC1"}
    restore_articles(tmp_path, ["PMC1"])
    restored = load_documents(tmp_path)["PMC1"]
    assert restored.blocks == original["PMC1"].blocks
    assert restored.statistics == original["PMC1"].statistics
    assert restored.sha256 == hashlib.sha256(shared_path.read_bytes()).hexdigest()
    assert set(load_snapshot(tmp_path)[0]) == {"PMC1", "PMC3"}


def test_shared_xml_updates_active_sibling_hash_and_both_indexes(tmp_path):
    upload_xml(tmp_path, "collection.xml", FIXTURE.read_bytes().replace(b"<articles>", b'<articles xmlns="urn:test:jats">'))
    before = load_documents(tmp_path)
    delete_articles(tmp_path, ["PMC2"])
    purge_articles(tmp_path, ["PMC2"])
    sync_raw_folder(tmp_path)
    docs, index = load_snapshot(tmp_path)
    assert set(docs) == {"PMC1", "PMC3"}
    for key, doc in docs.items():
        assert doc.blocks == before[key].blocks and doc.statistics == before[key].statistics
        assert doc.sha256 == hashlib.sha256((tmp_path / doc.raw_path).read_bytes()).hexdigest()
    assert search(index, "cancer treatment", "AND").document_ids == []
    assert search(index, "cancer treatment", "AND", stemming=True).document_ids == []


def test_missing_raw_is_safe_and_purges_backup(tmp_path):
    upload_xml(tmp_path, "collection.xml", FIXTURE.read_bytes())
    raw_path = tmp_path / load_documents(tmp_path)["PMC1"].raw_path
    raw_path.unlink()
    # External removal excludes articles from search, retaining recoverable backups.
    sync_raw_folder(tmp_path)
    assert not load_documents(tmp_path)
    purge_articles(tmp_path, ["PMC1"])
    assert set(load_deleted(tmp_path)) == {"PMC2", "PMC3"}
    assert not load_documents(tmp_path)


def test_corrupted_shared_source_refuses_before_any_delete(tmp_path):
    upload_xml(tmp_path, "collection.xml", FIXTURE.read_bytes())
    raw_path = tmp_path / load_documents(tmp_path)["PMC1"].raw_path
    delete_articles(tmp_path, ["PMC1"])
    raw_path.write_bytes(b"broken")
    with pytest.raises(StorageError, match="此次尚未刪除"):
        purge_articles(tmp_path, ["PMC1"])
    assert set(load_deleted(tmp_path)) == {"PMC1"}
    assert set(load_documents(tmp_path)) == {"PMC2", "PMC3"}
    assert not (tmp_path / "purge_pending.json").exists()


def test_interrupted_purge_recovers_on_restart(tmp_path, monkeypatch):
    import ir_hw1.purge as module
    upload_xml(tmp_path, "collection.xml", FIXTURE.read_bytes())
    delete_articles(tmp_path, ["PMC2"])
    original_save = module.save_documents
    monkeypatch.setattr(module, "save_documents", lambda *args: (_ for _ in ()).throw(OSError("simulated interruption")))
    with pytest.raises(OSError, match="interruption"):
        purge_articles(tmp_path, ["PMC2"])
    assert (tmp_path / "purge_pending.json").exists()
    with pytest.raises(StorageError, match="永久刪除尚未完成"):
        load_documents(tmp_path)
    monkeypatch.setattr(module, "save_documents", original_save)
    sync_raw_folder(tmp_path)  # Same startup path as the application; replays the stored plan.
    assert set(load_snapshot(tmp_path)[0]) == {"PMC1", "PMC3"}
    assert not load_deleted(tmp_path) and not (tmp_path / "purge_pending.json").exists()
    assert sum(r["status"] == "purged" for r in read_manifest(tmp_path)) == 1


def test_outside_path_is_never_deleted(tmp_path):
    from ir_hw1.purge import managed_path
    outside = tmp_path / "outside.xml"
    outside.write_bytes(FIXTURE.read_bytes())
    for relative in ("../outside.xml", "raw/../../outside.xml", "outside.xml", str(outside)):
        with pytest.raises(StorageError):
            managed_path(tmp_path, relative)
    assert outside.exists()


def test_corrupt_recovery_journal_fails_with_actionable_error(tmp_path):
    (tmp_path / "purge_pending.json").write_text("broken", encoding="utf-8")
    with pytest.raises(StorageError, match="恢復紀錄損壞"):
        sync_raw_folder(tmp_path)


def test_ui_requires_confirmation_and_removes_trash_entry(tmp_path, monkeypatch):
    monkeypatch.setenv("IR_HW1_DATA_DIR", str(tmp_path))
    upload_xml(tmp_path, "collection.xml", FIXTURE.read_bytes())
    delete_articles(tmp_path, ["PMC2"])
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    app.radio(key="view").set_value("文章管理").run()
    app.button(key="trash_all").click().run()
    app.button(key="purge_articles").click().run()
    assert any("請勾選確認" in w.value for w in app.warning)
    assert "PMC2" in load_deleted(tmp_path)
    app.checkbox[0].set_value(True)
    app.button(key="purge_articles").click().run()
    assert not app.exception and not load_deleted(tmp_path)
    assert any("已永久刪除 1 篇" in s.value for s in app.success)
    again = AppTest.from_file(str(APP), default_timeout=30).run()
    again.radio(key="view").set_value("文章管理").run()
    assert again.button(key="purge_articles").disabled
    assert set(load_snapshot(tmp_path)[0]) == {"PMC1", "PMC3"}
