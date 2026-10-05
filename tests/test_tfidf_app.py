"""Search shows relevance automatically, across navigation and corpus changes."""
import socket
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from ir_hw1.index import INDEX_VERSION, load_snapshot
from ir_hw1.search import search

APP = Path(__file__).resolve().parents[1] / "app.py"


def test_existing_session_rechecks_index_after_code_upgrade(stored, monkeypatch):
    from ir_hw1 import sync

    monkeypatch.setenv("IR_HW1_DATA_DIR", str(stored))
    original = sync.sync_raw_folder
    calls = []

    def observed(path):
        calls.append(path)
        return original(path)

    monkeypatch.setattr(sync, "sync_raw_folder", observed)
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    assert len(calls) == 1
    # Before this feature, an open session cached only path/raw/file signatures.
    app.session_state["synced_signature"] = app.session_state["synced_signature"][:3]
    app.run()
    assert not app.exception and len(calls) == 2
    assert app.session_state["synced_signature"][-1] == INDEX_VERSION
    app.run()
    assert len(calls) == 2


def result_ids(app):
    return [button.key.removeprefix("open_") for button in app.button
            if button.key and button.key.startswith("open_")]


def test_automatic_scores_order_details_navigation_and_restart(stored, monkeypatch):
    monkeypatch.setenv("IR_HW1_DATA_DIR", str(stored))
    monkeypatch.setattr(socket.socket, "connect", lambda *a: pytest.fail("Search stays offline"))
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    assert not any(s.label == "結果排序" for s in app.selectbox)
    app.text_input(key="query").set_value("cancer treatment")
    app.button[0].click().run()
    assert not app.exception
    assert result_ids(app) == ["PMC2", "PMC1", "PMC3"]
    docs, index = load_snapshot(stored)
    expected = search(index, "cancer treatment", "RELEVANCE", stemming=True)
    score_labels = [c.value for c in app.caption if c.value.startswith("相關性：")]
    assert score_labels == [f"相關性：{expected.scores[d]:.0%}" for d in expected.document_ids]
    app.button(key="open_PMC2").click().run()
    assert not app.exception and any(m.label == "單字數" and m.value == "3" for m in app.metric)
    app.radio(key="view").set_value("語料概覽").run()
    app.radio(key="view").set_value("搜尋文章").run()
    assert result_ids(app) == expected.document_ids
    assert not any(t.key == "stemming" for t in app.toggle)
    assert not app.exception and result_ids(app) == expected.document_ids
    assert not any(s.key == "mode" for s in app.selectbox)
    app.text_input(key="query").set_value('"cancer treatment"')
    app.button[0].click().run()
    assert not app.exception and result_ids(app) == expected.document_ids
    assert any("特殊搜尋語法" in w.value for w in app.warning)
    assert any("<mark>Cancer</mark> <mark>treatment</mark>" in m.value for m in app.markdown)
    assert any(c.value.startswith("相關性：") for c in app.caption)
    app.text_input(key="query").set_value("unknown")
    app.button[0].click().run()
    assert not app.exception and not result_ids(app)
    assert not any(c.value.startswith("相關性：") for c in app.caption)
    again = AppTest.from_file(str(APP), default_timeout=30).run()
    again.text_input(key="query").set_value("cancer treatment")
    again.button[0].click().run()
    assert not again.exception and result_ids(again) == expected.document_ids
