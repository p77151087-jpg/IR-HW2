"""Folder changes and batch management use disposable synthetic files only."""
import json
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from streamlit.testing.v1 import AppTest

from ir_hw1.cli import main
from ir_hw1.index import load_snapshot
from ir_hw1.library import delete_articles, restore_articles, upload_xml
from ir_hw1.search import search
from ir_hw1.storage import StorageError, load_deleted, load_documents, read_manifest
from ir_hw1.sync import raw_signature, sync_raw_folder
from ir_hw1.xml_parser import articles_in_xml

ROOT = Path(__file__).resolve().parents[1]
RAW = (ROOT / "tests/fixtures/synthetic.xml").read_bytes()


def seed(path):
    (path / "raw").mkdir()
    source = path / "raw/articles.xml"
    source.write_bytes(RAW)
    sync_raw_folder(path)
    return source


@pytest.mark.parametrize("operation", ["move", "delete"])
def test_external_removal_and_return_updates_both_indexes(tmp_path, operation):
    source = seed(tmp_path)
    if operation == "move":
        source.rename(tmp_path / "outside.xml")
    else:
        source.unlink()
    assert sync_raw_folder(tmp_path).removed == 3
    assert not load_documents(tmp_path)
    index = json.loads((tmp_path / "index.json").read_text())
    assert index["postings"] == index["porter_postings"] == {}
    before = read_manifest(tmp_path)
    (tmp_path / "raw_sync_state.json").unlink()
    sync_raw_folder(tmp_path)
    assert read_manifest(tmp_path) == before
    source.write_bytes(RAW)
    assert sync_raw_folder(tmp_path).restored == 3
    assert not load_deleted(tmp_path)
    assert search(load_snapshot(tmp_path)[1], "cancer treatment").document_ids == ["PMC2"]


def test_rename_inside_raw_preserves_article_and_updates_source(tmp_path):
    source = seed(tmp_path)
    source.rename(tmp_path / "raw/renamed.XML")
    sync_raw_folder(tmp_path)
    docs, _ = load_snapshot(tmp_path)
    assert set(docs) == {"PMC1", "PMC2", "PMC3"}
    assert all(d.raw_path == "raw/renamed.XML" for d in docs.values())
    assert not load_deleted(tmp_path)


def test_duplicate_source_falls_back_to_actual_remaining_version(tmp_path):
    old = ET.tostring(articles_in_xml(RAW)[0])
    upload_xml(tmp_path, "old.xml", old)
    upload_xml(tmp_path, "new.xml", old.replace(b"Cancer", b"Kidney"))
    sync_raw_folder(tmp_path)
    latest_path = tmp_path / load_documents(tmp_path)["PMC1"].raw_path
    latest_path.unlink()
    sync_raw_folder(tmp_path)
    docs, index = load_snapshot(tmp_path)
    assert (tmp_path / docs["PMC1"].raw_path).exists()
    assert search(index, "kidney").document_ids == []
    assert search(index, "cancer").document_ids == ["PMC1"]


@pytest.mark.parametrize("changed", [b"<broken>", ET.tostring(articles_in_xml(RAW)[0])])
def test_changed_xml_never_keeps_removed_article_searchable(tmp_path, changed):
    source = seed(tmp_path)
    source.write_bytes(changed)
    sync_raw_folder(tmp_path)
    assert "PMC2" not in load_documents(tmp_path)
    assert "PMC2" in load_deleted(tmp_path)
    source.write_bytes(RAW)
    sync_raw_folder(tmp_path)
    assert set(load_documents(tmp_path)) == {"PMC1", "PMC2", "PMC3"}


def test_explicit_trash_stays_deleted_when_files_return_and_batch_restore_is_atomic(tmp_path):
    source = seed(tmp_path)
    delete_articles(tmp_path, ["PMC1", "PMC2"])
    source.unlink()
    sync_raw_folder(tmp_path)
    with pytest.raises(StorageError, match="尚未還原任何文章"):
        restore_articles(tmp_path, ["PMC1", "PMC2"])
    source.write_bytes(RAW)
    sync_raw_folder(tmp_path)
    assert set(load_documents(tmp_path)) == {"PMC3"}
    # Renamed shared source can still be restored; parse it once for the batch.
    source.rename(tmp_path / "raw/renamed.xml")
    assert restore_articles(tmp_path, ["PMC1", "PMC2"]) == 2
    sync_raw_folder(tmp_path)
    assert set(load_documents(tmp_path)) == {"PMC1", "PMC2", "PMC3"}


def test_cli_search_synchronizes_deleted_raw_before_matching(tmp_path, capsys):
    seed(tmp_path).unlink()
    assert main(["--data-dir", str(tmp_path), "search", "cancer"]) == 0
    response, _ = json.JSONDecoder().raw_decode(capsys.readouterr().out)
    assert response["document_ids"] == []


def test_watch_signature_and_app_refresh_drop_existing_search_result(tmp_path, monkeypatch):
    source = seed(tmp_path)
    before = raw_signature(tmp_path)
    monkeypatch.setenv("IR_HW1_DATA_DIR", str(tmp_path))
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    app.text_input(key="query").set_value("cancer treatment")
    app.button[0].click().run()
    assert any(m.label == "符合文章" and m.value == "3" for m in app.metric)
    source.unlink()
    assert raw_signature(tmp_path) != before
    app.run()
    assert not app.exception and not app.metric
    assert any("尚無文章" in w.value for w in app.warning)


def test_batch_select_filter_clear_restore_and_purge(tmp_path, monkeypatch):
    seed(tmp_path)
    monkeypatch.setenv("IR_HW1_DATA_DIR", str(tmp_path))
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    app.radio(key="view").set_value("文章管理").run()
    app.text_input(key="active_filter").set_value("PMC2").run()
    app.button(key="active_all").click().run()
    assert app.session_state["active_selected_0"] == ["PMC2"]
    app.text_input(key="active_filter").set_value("").run()
    assert app.session_state["active_selected_0"] == ["PMC2"]
    app.button(key="active_all").click().run()
    assert len(app.session_state["active_selected_0"]) == 3
    app.button(key="active_clear").click().run()
    assert app.button(key="delete_articles").disabled
    app.button(key="active_all").click().run()
    app.button(key="delete_articles").click().run()
    assert not load_documents(tmp_path) and len(load_deleted(tmp_path)) == 3
    app.button(key="trash_all").click().run()
    app.button(key="restore_articles").click().run()
    assert len(load_documents(tmp_path)) == 3 and not load_deleted(tmp_path)
    app.button(key="active_all").click().run()
    app.button(key="delete_articles").click().run()
    app.button(key="trash_all").click().run()
    app.checkbox[0].set_value(True).run()
    app.button(key="purge_articles").click().run()
    assert not app.exception and not load_documents(tmp_path) and not load_deleted(tmp_path)
    assert not list((tmp_path / "raw").glob("*.xml"))
