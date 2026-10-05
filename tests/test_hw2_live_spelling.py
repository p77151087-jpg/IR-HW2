"""Live draft suggestions must not change the user's committed search."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[1] / "app.py"


def start(stored, monkeypatch):
    monkeypatch.setenv("IR_HW1_DATA_DIR", str(stored))
    return AppTest.from_file(str(APP), default_timeout=30).run()


def test_suggestions_appear_before_search_and_clear_with_draft(stored, monkeypatch):
    app = start(stored, monkeypatch)
    assert app.text_input(key="query").proto.live_debounce_ms == 200
    app.text_input(key="query").set_value("cancerr").run()
    assert not app.exception
    assert app.button(key="adopt_spelling").label == "cancer"
    assert "active_search" not in app.session_state
    assert not app.metric
    app.text_input(key="query").set_value("cancer").run()
    assert not any(button.key == "adopt_spelling" for button in app.button)
    app.text_input(key="query").set_value("").run()
    assert not app.exception
    assert not any(button.key == "adopt_spelling" for button in app.button)
    assert "active_search" not in app.session_state


def test_apptest_preserves_application_socket_guard(monkeypatch):
    import socket
    attempts = []

    def blocked(sock, address):
        attempts.append(address)
        raise RuntimeError("Application network is blocked")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    app = AppTest.from_string(
        "import socket\nwith socket.socket() as sock:\n    sock.connect(('127.0.0.1', 12345))"
    ).run()
    assert len(app.exception) == 1
    assert app.exception[0].message == "Application network is blocked"
    assert attempts == [("127.0.0.1", 12345)]
    assert socket.socket.connect is blocked


def test_draft_keeps_previous_results_until_explicit_search(stored, monkeypatch):
    app = start(stored, monkeypatch)
    app.text_input(key="query").set_value("treatment")
    app.button(key="submit_search").click().run()
    previous_count = next(item.value for item in app.metric if item.label == "符合文章")
    app.text_input(key="query").set_value("cancerr").run()
    assert not app.exception
    assert app.session_state["active_search"] == "treatment"
    assert next(item.value for item in app.metric if item.label == "符合文章") == previous_count
    assert app.button(key="adopt_spelling").label == "cancer"
    app.button(key="submit_search").click().run()
    assert app.session_state["active_search"] == "cancerr"
    assert app.text_input(key="query").value == "cancerr"


def test_click_adopts_suggestion_without_prior_search_and_keeps_other_terms(stored, monkeypatch):
    app = start(stored, monkeypatch)
    app.text_input(key="query").set_value("GLP-1  cancerr, treatment").run()
    assert app.button(key="adopt_spelling").label == "GLP-1  cancer, treatment"
    app.button(key="adopt_spelling").click().run()
    assert not app.exception
    assert app.text_input(key="query").value == "GLP-1  cancer, treatment"
    assert app.session_state["active_search"] == "GLP-1  cancer, treatment"
    assert any("原查詢：GLP-1  cancerr, treatment" in caption.value for caption in app.caption)


def test_stale_suggestion_does_not_overwrite_newer_input(stored, monkeypatch):
    app = start(stored, monkeypatch)
    app.text_input(key="query").set_value("cancerr").run()
    app.text_input(key="query").set_value("treatment")
    app.button(key="adopt_spelling").click().run()
    assert not app.exception
    assert app.text_input(key="query").value == "treatment"
    assert "active_search" not in app.session_state
    assert not any(button.key == "adopt_spelling" for button in app.button)


@pytest.mark.parametrize("query", ["GLP-1 IL-6", "XYZABC AbcDef", "the", "中文", "zzzzzzzzzz"])
def test_protected_or_unresolved_words_are_not_replaced(stored, monkeypatch, query):
    app = start(stored, monkeypatch)
    app.text_input(key="query").set_value(query).run()
    assert not app.exception
    assert app.text_input(key="query").value == query
    assert not any(button.key == "adopt_spelling" for button in app.button)
    assert "active_search" not in app.session_state
