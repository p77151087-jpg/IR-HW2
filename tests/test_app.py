from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[1] / "app.py"


@pytest.mark.parametrize("abstract,body,words,sentences", [
    ("", "", 2, 0),
    ("<abstract><p>Available abstract.</p></abstract>", "", 4, 1),
    ("", "<body> </body>", 2, 0),
    ("", "<body><sec><title>Results</title><table><tr><td>Measurement</td></tr></table></sec></body>", 4, 0),
])
def test_ui_displays_available_article_content(tmp_path, monkeypatch, abstract, body, words, sentences):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "article.xml").write_text(
        '<article><front><article-meta><article-id pub-id-type="pmc">700</article-id>'
        '<title-group><article-title>Available article</article-title></title-group>'
        f'{abstract}</article-meta></front>{body}</article>', encoding="utf-8")
    monkeypatch.setenv("IR_HW1_DATA_DIR", str(tmp_path))
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    app.radio(key="view").set_value("文章詳情").run()
    assert not app.exception
    assert len(app.tabs) == 3
    assert app.tabs[0].label == "摘要與全文"
    assert any(m.label == "單字數" and m.value == str(words) for m in app.metric)
    assert any(m.label == "句子數" and m.value == str(sentences) for m in app.metric)
    if abstract:
        assert any("Available abstract." in m.value for m in app.markdown)
    else:
        assert not any(s.key == "sentence_block_PMC700" for s in app.selectbox)


def test_ui_search_open_statistics_restart(stored, monkeypatch):
    monkeypatch.setenv("IR_HW1_DATA_DIR", str(stored))
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    assert not app.exception
    app.text_input(key="query").set_value("cancer treatment")
    app.button[0].click().run()
    assert not app.exception
    assert any(m.label == "符合文章" and m.value == "3" for m in app.metric)
    app.button(key="open_PMC2").click().run()
    assert not app.exception
    assert any(m.label == "單字數" and m.value == "3" for m in app.metric)
    assert len(app.tabs) == 3
    app.radio(key="view").set_value("語料概覽").run()
    assert not app.exception
    assert len(app.dataframe) >= 1
    # Fresh Streamlit session reads the persisted corpus without fetching XML.
    again = AppTest.from_file(str(APP), default_timeout=30).run()
    again.text_input(key="query").set_value("cancer treatment")
    again.button[0].click().run()
    assert any(m.label == "符合文章" and m.value == "3" for m in again.metric)


def test_ui_empty_unknown_and_missing_data(stored, tmp_path, monkeypatch):
    monkeypatch.setenv("IR_HW1_DATA_DIR", str(stored))
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    app.text_input(key="query").set_value("... ")
    app.button[0].click().run()
    assert any("有效關鍵字" in i.value for i in app.info)
    app.text_input(key="query").set_value("nonexistent")
    app.button[0].click().run()
    assert any("找不到" in i.value for i in app.info)
    assert not app.exception
    monkeypatch.setenv("IR_HW1_DATA_DIR", str(tmp_path / "empty"))
    empty = AppTest.from_file(str(APP), default_timeout=30).run()
    assert any("尚無文章" in w.value for w in empty.warning)
    assert not empty.exception


def test_switch_articles_replaces_detail_and_keeps_statistics(stored, monkeypatch):
    monkeypatch.setenv("IR_HW1_DATA_DIR", str(stored))
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    app.radio(key="view").set_value("文章詳情").run()
    for pmcid, title, words in [("PMC2", "Beta", 3), ("PMC3", "Gamma", 2), ("PMC1", "Alpha", 2)]:
        app.selectbox(key="article_choice").set_value(pmcid).run()
        assert not app.exception
        assert len(app.tabs) == 3
        assert [m.value for m in app.markdown if m.value.startswith("<h3>")] == [f"<h3>{title}</h3>"]
        assert any(m.label == "單字數" and m.value == str(words) for m in app.metric)
        assert any(m.label == "句子數" and m.value == "1" for m in app.metric)
    app.radio(key="view").set_value("搜尋文章").run()
    app.text_input(key="query").set_value("cancer treatment")
    app.button[0].click().run()
    for pmcid, title in [("PMC2", "Beta"), ("PMC1", "Alpha"), ("PMC3", "Gamma")]:
        app.button(key="open_" + pmcid).click().run()
        assert not app.exception
        assert len(app.tabs) == 3
        assert [m.value for m in app.markdown if m.value.startswith("<h3>")] == [f"<h3>{title}</h3>"]
        assert any(m.label == "符合文章" and m.value == "3" for m in app.metric)


def test_navigation_reuses_snapshot_but_detects_same_size_raw_edit(stored, monkeypatch):
    import os
    from ir_hw1 import sync

    monkeypatch.setenv("IR_HW1_DATA_DIR", str(stored))
    original_sync = sync.sync_raw_folder
    calls = []
    def observed_sync(path):
        calls.append(path)
        return original_sync(path)
    monkeypatch.setattr(sync, "sync_raw_folder", observed_sync)
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    assert len(calls) == 1
    for view in ("文章詳情", "語料概覽", "搜尋文章"):
        app.radio(key="view").set_value(view).run()
        assert not app.exception
    assert not any(t.key == "stemming" for t in app.toggle)
    app.text_input(key="query").set_value("patients")
    app.button[0].click().run()
    assert len(calls) == 1  # Navigation and search reuse the existing snapshot.

    source = stored / "raw/synthetic.xml"
    previous = source.stat()
    source.write_bytes(source.read_bytes().replace(b"Cancer", b"Kidney"))
    os.utime(source, ns=(previous.st_atime_ns, previous.st_mtime_ns))
    app.text_input(key="query").set_value("kidney")
    app.button[0].click().run()
    assert not app.exception and len(calls) == 2
    assert any(m.label == "符合文章" and m.value == "2" for m in app.metric)


def test_cached_navigation_observes_external_library_changes(stored, monkeypatch):
    from ir_hw1.library import delete_articles

    monkeypatch.setenv("IR_HW1_DATA_DIR", str(stored))
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    app.text_input(key="query").set_value("cancer")
    app.button[0].click().run()
    assert any(m.label == "符合文章" and m.value == "2" for m in app.metric)
    delete_articles(stored, ["PMC1"])
    app.run()
    assert not app.exception
    assert any(m.label == "符合文章" and m.value == "1" for m in app.metric)
    assert not any(button.key == "open_PMC1" for button in app.button)


def test_repeated_download_and_search_keep_views_separate(stored, monkeypatch):
    """Repeated submits/reruns must not retain widgets from the previous view.

    This checks server-rendered state; actual rapid clicks need a browser test.
    """
    monkeypatch.setenv("IR_HW1_DATA_DIR", str(stored))
    requests = []

    def existing_article(data_dir, pmid):
        requests.append(pmid)
        return [{"pmcid": "PMC2", "pmid": pmid, "status": "duplicate", "reason": "文章已在本機"}]

    monkeypatch.setattr("ir_hw1.ui_management.download_pmid", existing_article)
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    app.text_input(key="query").set_value("cancer treatment")
    app.button[0].click().run()
    for _ in range(3):
        app.radio(key="view").set_value("文章管理").run()
        assert not any(t.key == "query" for t in app.text_input)
        assert not app.toggle
        app.text_input(key="download_pmid").set_value("2")
        for _ in range(2):
            app.button(key="fetch_pmid").click().run()
            assert not app.exception
            assert len(app.tabs) == 3
            result_tables = [frame for frame in app.dataframe if "結果" in frame.value.columns]
            assert len(result_tables) == 1  # Other tabs also contain article selection tables.
            assert list(result_tables[0].value["結果"]) == ["已存在"]
        app.radio(key="view").set_value("搜尋文章").run()
        for _ in range(2):
            app.button[0].click().run()
            assert not app.exception and not app.tabs
            assert not any(t.key == "download_pmid" for t in app.text_input)
            assert app.text_input(key="query").value == "cancer treatment"
            assert not any(s.key == "mode" for s in app.selectbox)
            assert any(m.label == "符合文章" and m.value == "3" for m in app.metric)
    assert requests == ["2"] * 6
