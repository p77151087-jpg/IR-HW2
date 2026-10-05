from hashlib import sha256
from pathlib import Path

from streamlit.testing.v1 import AppTest


ROOT = Path(__file__).resolve().parents[1]


def test_public_entrypoint_keeps_queries_and_downloads_without_mutation_controls(stored, monkeypatch):
    import ir_hw1.ui_management
    import ir_hw2.analysis
    import ir_hw2.corpus
    import ir_hw2.embeddings
    import ir_hw2.integration

    def prohibited(*args, **kwargs):
        raise AssertionError("The public demo attempted a data-management operation")

    monkeypatch.setenv("IR_HW1_DATA_DIR", str(stored))
    # The entrypoint must force demo mode, even if its environment says otherwise.
    # monkeypatch also restores the process environment for the local-app tests.
    monkeypatch.setenv("IR_HW2_READ_ONLY", "0")
    for module, name in [
        (ir_hw1.ui_management, "show_management"),
        (ir_hw2.analysis, "run_experiment"),
        (ir_hw2.corpus, "fetch_corpus"),
        (ir_hw2.embeddings, "train_word2vec"),
        (ir_hw2.integration, "publish_search_copy"),
    ]:
        monkeypatch.setattr(module, name, prohibited)

    saved = [ROOT / name for name in (
        "reports/hw2/experiment/summary.json", "reports/hw2/experiment/log_log.png",
        "reports/hw2/experiment/residuals.png", "reports/hw2/model/word2vec.model",
    )]
    fingerprints = {path: sha256(path.read_bytes()).hexdigest() for path in saved}
    app = AppTest.from_file(str(ROOT / "cloud_app.py"), default_timeout=30)
    app.session_state["view"] = "文章管理"
    app.run()
    assert not app.exception
    assert "文章管理" not in app.radio(key="view").options
    assert app.radio(key="view").value == "搜尋文章"
    app.text_input(key="query").set_value("cancer treatment")
    app.button(key="submit_search").click().run()
    assert not app.exception
    assert any(metric.label == "符合文章" and metric.value == "3" for metric in app.metric)
    app.button(key="open_PMC2").click().run()
    assert not app.exception
    assert any(metric.label == "單字數" and metric.value == "3" for metric in app.metric)

    app.radio(key="view").set_value("實驗室").run()
    for section in ["語料與前處理", "Zipf 分析", "CF／DF 與 IDF", "Word2Vec", "方法與報告"]:
        app.radio(key="hw2_section").set_value(section).run()
        assert not app.exception and not app.error
        assert not {"hw2_publish", "hw2_fetch", "hw2_analyze", "hw2_train"} & {button.key for button in app.button}
        if section == "CF／DF 與 IDF":
            assert app.radio(key="hw2_vocabulary_scope").value == "全部詞彙"
            app.radio(key="hw2_vocabulary_scope").set_value("選定詞彙").run()
            assert not app.exception
            assert app.get("download_button")
        elif section == "Word2Vec":
            app.text_input(key="hw2_neighbor_query").set_value("GLP-1")
            app.button(key="FormSubmitter:hw2_neighbors_form-查詢近鄰").click().run()
            assert not app.exception and not app.error
            assert any("cosine" in frame.value.columns and len(frame.value) > 0 for frame in app.dataframe)
        elif section == "方法與報告":
            assert len(app.get("download_button")) == 4
    assert fingerprints == {path: sha256(path.read_bytes()).hexdigest() for path in saved}
