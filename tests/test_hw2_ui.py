import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from ir_hw1.models import Document, TextBlock
from ir_hw2.analysis import run_experiment

ROOT = Path(__file__).resolve().parents[1]


def configure(monkeypatch, tmp_path, stored):
    monkeypatch.setenv("IR_HW1_DATA_DIR", str(stored))
    for key, directory in [("IR_HW2_SNAPSHOT", "snapshot"), ("IR_HW2_OUTPUT", "experiment"), ("IR_HW2_MODEL", "model")]:
        monkeypatch.setenv(key, str(tmp_path / directory))
    return AppTest.from_file(str(ROOT / "app.py"), default_timeout=30)


def test_lab_available_when_library_empty(tmp_path, monkeypatch):
    app = configure(monkeypatch, tmp_path, tmp_path / "empty")
    app.run()
    app.radio(key="view").set_value("實驗室").run()
    assert not app.exception
    assert app.button(key="hw2_analyze").disabled
    assert len(app.dataframe) == 1
    frame = app.dataframe[0].value
    assert frame.iloc[0]["序列"] != frame.iloc[1]["序列"]
    assert list(frame["條件"]) == ["A", "B", "C", "D"]
    assert "glp-1" in frame.iloc[0]["序列"].split(" | ")
    assert "3.5" in frame.iloc[0]["序列"].split(" | ")
    assert "the" in frame.iloc[0]["序列"].split(" | ")
    assert "the" in frame.iloc[1]["序列"].split(" | ")
    assert "the" not in frame.iloc[2]["序列"].split(" | ")
    assert "patient" in frame.iloc[3]["序列"].split(" | ")


def test_pages_do_not_fetch_or_train_on_rerun(tmp_path, stored, monkeypatch):
    import ir_hw2.corpus
    import ir_hw2.embeddings
    def prohibited(*args, **kwargs):
        raise AssertionError("Expensive operation occurred without an explicit click")
    monkeypatch.setattr(ir_hw2.corpus, "fetch_corpus", prohibited)
    monkeypatch.setattr(ir_hw2.embeddings, "train_word2vec", prohibited)
    app = configure(monkeypatch, tmp_path, stored)
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    (snapshot / "snapshot.json").write_text(json.dumps({"query": "fixture", "sha256": "fixture", "selected_pmids": ["1"]}), encoding="utf-8")
    docs = {"1": Document("D1", "exclude", [TextBlock("b0", "abstract", "", "The insulin treatment helps. Insulin works.")], pmid="1", content_scope="abstract")}
    run_experiment(docs, tmp_path / "experiment", "fixture")
    app.run().radio(key="view").set_value("實驗室").run()
    assert not app.exception
    assert app.button(key="hw2_fetch").disabled
    for name in ["Zipf 分析", "CF／DF 與 IDF", "Word2Vec", "方法與報告", "語料與前處理"]:
        app.radio(key="hw2_section").set_value(name).run()
        assert not app.exception
        if name == "Zipf 分析":
            assert app.selectbox(key="hw2_segment_condition").value == "A"
            assert any("log(CF) 空間" in caption.value for caption in app.caption)
            fits = [item.value for item in app.dataframe if "log_base" in item.value.columns]
            assert fits and all(set(frame["log_base"].astype(str)) == {"10"} for frame in fits)
        elif name == "CF／DF 與 IDF":
            assert any("IDF = log(N/DF)" in caption.value for caption in app.caption)
            assert any("不足 20" in warning.value for warning in app.warning)
            assert app.radio(key="hw2_vocabulary_scope").value == "全部詞彙"
            app.radio(key="hw2_vocabulary_scope").set_value("選定詞彙").run()
            assert not app.exception
            assert app.radio(key="hw2_vocabulary_scope").value == "選定詞彙"
            app.radio(key="hw2_idf_view").set_value("代表詞比較").run()
            assert not app.exception
            assert app.radio(key="hw2_idf_view").value == "代表詞比較"
    assert not (tmp_path / "model/metadata.json").exists()


def test_frequency_scope_search_and_pagination_use_full_saved_vocabulary():
    def frequency_page():
        import json
        from pathlib import Path
        from ir_hw2.ui import _show_frequencies
        output = Path('reports/hw2/experiment')
        _show_frequencies(json.loads((output / 'summary.json').read_text(encoding='utf-8')), output)

    summary = json.loads((ROOT / 'reports/hw2/experiment/summary.json').read_text(encoding='utf-8'))
    count = len(summary['conditions']['B']['cf'])
    app = AppTest.from_function(frequency_page, default_timeout=30).run()
    assert not app.exception
    assert app.radio(key='hw2_vocabulary_scope').value == '全部詞彙'
    assert app.metric[0].value == f'{count:,}'
    assert len(app.dataframe[0].value) == 50
    app.number_input(key='hw2_vocabulary_page').set_value(2).run()
    assert app.dataframe[0].value.iloc[0]['排名'] == 51
    app.text_input(key='hw2_vocabulary_query').set_value('INSULIN').run()
    assert not app.exception
    assert app.number_input(key='hw2_vocabulary_page').value == 1
    assert app.dataframe[0].value['詞彙'].str.contains('insulin', case=False, regex=False).all()
    assert app.metric[0].value == f'{count:,}'  # Table filtering never changes chart scope.
    app.radio(key='hw2_vocabulary_scope').set_value('選定詞彙').run()
    assert not app.exception
    assert app.metric[0].value == f"{len(summary['selected_terms']):,}"
    assert app.dataframe[-1].value['詞彙'].tolist() == [row['term'] for row in summary['selected_terms']]
    app.text_input(key='hw2_vocabulary_query').set_value('no_such_term_987654321').run()
    assert any('沒有符合' in item.value for item in app.info)
    app.radio(key='hw2_vocabulary_scope').set_value('全部詞彙').run()
    assert app.metric[0].value == f'{count:,}'
    assert not app.exception


def test_condition_selectors_start_at_a_and_keep_explicit_choices(tmp_path, stored, monkeypatch):
    app = configure(monkeypatch, tmp_path, stored)
    docs = {"1": Document("D1", "exclude", [TextBlock("b0", "abstract", "", "The patients improve. GLP-1 helps.")], pmid="1", content_scope="abstract")}
    run_experiment(docs, tmp_path / "experiment", "fixture")
    # Simulate a previously opened page that still remembers C.
    app.session_state["hw2_top_condition"] = "D"
    app.session_state["hw2_segment_condition"] = "C"
    app.run().radio(key="view").set_value("實驗室").run()
    assert not app.exception
    assert app.selectbox(key="hw2_top_condition").value == "A"
    assert app.selectbox(key="hw2_top_condition").options == ["A", "B", "C", "D"]
    app.selectbox(key="hw2_top_condition").set_value("C").run()
    app.run()
    assert app.selectbox(key="hw2_top_condition").value == "C"
    app.radio(key="hw2_section").set_value("Zipf 分析").run()
    assert app.selectbox(key="hw2_segment_condition").value == "A"
    app.selectbox(key="hw2_segment_condition").set_value("C").run()
    app.run()
    assert app.selectbox(key="hw2_segment_condition").value == "C"
    assert not app.exception


def test_different_tokenizer_summary_is_not_shown_as_hw1(tmp_path, stored, monkeypatch):
    app = configure(monkeypatch, tmp_path, stored)
    docs = {"1": Document("D1", "exclude", [TextBlock("b0", "abstract", "", "The GLP-1 treatment helps.")], pmid="1", content_scope="abstract")}
    output = tmp_path / "experiment"
    summary = run_experiment(docs, output, "fixture")
    summary["metadata"]["baseline_tokenizer"]["version"] = "different-tokenizer"
    (output / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    app.run().radio(key="view").set_value("實驗室").run()
    app.radio(key="hw2_section").set_value("Zipf 分析").run()
    assert not app.exception
    assert any("不同的切詞規則" in warning.value for warning in app.warning)
    assert not app.dataframe
    assert not app.get("imgs")


def test_old_tokenizer_model_requires_explicit_retraining(tmp_path, stored, monkeypatch):
    app = configure(monkeypatch, tmp_path, stored)
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    (snapshot / "snapshot.json").write_text(json.dumps({"sha256": "fixture", "selected_pmids": ["1"]}), encoding="utf-8")
    model = tmp_path / "model"
    model.mkdir()
    (model / "metadata.json").write_text(json.dumps({"vocabulary_size": 10, "sentences": 2, "documents": 1}), encoding="utf-8")
    app.run().radio(key="view").set_value("實驗室").run()
    app.radio(key="hw2_section").set_value("Word2Vec").run()
    assert not app.exception
    assert any("不同的切詞規則" in warning.value for warning in app.warning)
    assert not any(item.key == "hw2_neighbor_query" for item in app.text_input)


def word2vec_fixture(tmp_path):
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    (snapshot / "snapshot.json").write_text(json.dumps({"sha256": "fixture", "selected_pmids": ["1"]}), encoding="utf-8")
    return {"1": Document("D1", "", [TextBlock("b0", "abstract", "", "The semaglutide and insulin treatments help GLP-1 patients. " * 2)],
                          pmid="1", content_scope="abstract")}


def test_word2vec_missing_dependency_explains_how_to_restart(tmp_path, stored, monkeypatch):
    import builtins
    word2vec_fixture(tmp_path)
    original_import = builtins.__import__

    def without_gensim(name, globals=None, locals=None, fromlist=(), level=0):
        if name in ("embeddings", "ir_hw2.embeddings"):
            raise ModuleNotFoundError("No module named 'gensim'", name="gensim")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", without_gensim)
    app = configure(monkeypatch, tmp_path, stored)
    app.run().radio(key="view").set_value("實驗室").run()
    app.radio(key="hw2_section").set_value("Word2Vec").run()
    assert not app.exception
    assert any("Word2Vec 套件無法載入" in item.value for item in app.error)
    assert any("setup_hw2.ps1" in item.value and "start_demo.ps1" in item.value for item in app.code)
    assert not any(item.key in ("hw2_train", "FormSubmitter:hw2_neighbors_form-查詢近鄰") for item in app.button)


@pytest.mark.parametrize("query,expected_message", [
    ("GLP-1", "上下文相似性"),
    ("zzzznotincorpus", "不在模型詞彙"),
    ("GLP-1 receptor", "兩詞"),
])
def test_word2vec_form_loads_saved_model_and_queries(tmp_path, stored, monkeypatch, query, expected_message):
    from ir_hw2.embeddings import TrainingConfig, train_word2vec
    docs = word2vec_fixture(tmp_path)
    train_word2vec(docs, tmp_path / "model", "fixture", TrainingConfig(vector_size=8, min_count=1, epochs=2, sample=0))
    app = configure(monkeypatch, tmp_path, stored)
    app.run().radio(key="view").set_value("實驗室").run()
    app.radio(key="hw2_section").set_value("Word2Vec").run()
    app.text_input(key="hw2_neighbor_query").set_value(query)
    app.button(key="FormSubmitter:hw2_neighbors_form-查詢近鄰").click().run()
    assert not app.exception and not app.error
    assert any(expected_message in item.value for item in app.info)
    if query == "GLP-1":
        assert len(app.dataframe) == 1
        frame = app.dataframe[0].value
        assert "semaglutide" in set(frame["term"])
        assert "glp-1" not in set(frame["term"])
        assert frame["cosine"].between(-1, 1).all()
    else:
        assert not app.dataframe


def test_word2vec_train_button_saves_a_queryable_model(tmp_path, stored, monkeypatch):
    import ir_hw2.corpus
    docs = word2vec_fixture(tmp_path)
    monkeypatch.setattr(ir_hw2.corpus, "load_corpus", lambda snapshot: docs)
    app = configure(monkeypatch, tmp_path, stored)
    app.run().radio(key="view").set_value("實驗室").run()
    app.radio(key="hw2_section").set_value("Word2Vec").run()
    assert not (tmp_path / "model/metadata.json").exists()
    app.button(key="hw2_train").click().run()
    assert not app.exception and not app.error
    assert (tmp_path / "model/word2vec.model").exists()
    app.button(key="FormSubmitter:hw2_neighbors_form-查詢近鄰").click().run()
    assert not app.exception and not app.error
    assert len(app.dataframe) == 1


def test_legacy_log_summary_is_not_relabelled_as_base10(tmp_path, stored, monkeypatch):
    app = configure(monkeypatch, tmp_path, stored)
    output = tmp_path / "experiment"
    output.mkdir()
    # A pre-migration artifact must not appear under new log captions.
    (output / "summary.json").write_text(json.dumps({
        "conditions": {c: {"regression": {"log_base": "e"}} for c in "ABCD"}
    }), encoding="utf-8")
    app.run().radio(key="view").set_value("實驗室").run()
    app.radio(key="hw2_section").set_value("Zipf 分析").run()
    assert not app.exception
    assert any("舊版對數底數" in warning.value for warning in app.warning)
    assert not app.dataframe
    assert not app.get("imgs")


def test_spelling_requires_explicit_adoption(tmp_path, stored, monkeypatch):
    import ir_hw2.spelling
    app = configure(monkeypatch, tmp_path, stored)
    monkeypatch.setattr(ir_hw2.spelling, "suggest_query", lambda query, vocabulary: {
        "original_query": query, "suggested_query": "cancer", "changes": [{"original": query, "suggestion": "cancer"}]
    } if query == "cancerr" else {"original_query": query, "suggested_query": query, "changes": []})
    app.run()
    app.text_input(key="query").set_value("cancerr")
    app.button(key="submit_search").click().run()
    assert not app.exception
    assert app.session_state["active_search"] == "cancerr"
    assert app.text_input(key="query").value == "cancerr"
    app.button(key="adopt_spelling").click().run()
    assert not app.exception
    assert app.session_state["active_search"] == "cancer"
    assert app.text_input(key="query").value == "cancer"
    assert any("原查詢：cancerr" in caption.value for caption in app.caption)
