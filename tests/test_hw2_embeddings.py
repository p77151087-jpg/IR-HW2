from copy import deepcopy
import json

import numpy as np
import pytest

from ir_hw1.models import Document, TextBlock
from ir_hw1.preprocessing import tokenize as hw1_tokenize
from ir_hw2 import analysis
from ir_hw2.analysis import baseline_tokenizer_spec
from ir_hw2.embeddings import TrainingConfig, load_word2vec, neighbors, sentence_records, train_word2vec


def corpus():
    return {"D2": Document("D2", "TITLE EXCLUDED", [TextBlock("b0", "abstract", "Methods", "Insulin reduces glucose. Glucose improves insulin.")], pmid="2", content_scope="abstract"),
            "D1": Document("D1", "OTHER TITLE", [TextBlock("b0", "abstract", "LABEL EXCLUDED", "Patients receive insulin. Patients receive treatment."),
                                                  TextBlock("b1", "abstract", "Results", "Treatment reduces glucose.")], pmid="1", content_scope="abstract")}


def test_word_order_and_boundaries():
    records = sentence_records(corpus())
    assert [r["pmid"] for r in records] == ["1", "1", "1", "2", "2"]
    assert [r["tokens"] for r in records] == [
        ["patients", "receive", "insulin"], ["patients", "receive", "treatment"],
        ["treatment", "reduces", "glucose"], ["insulin", "reduces", "glucose"],
        ["glucose", "improves", "insulin"]]
    assert records[2]["block_id"] == "b1"
    assert records[0]["start"] == 0


def test_train_reload_exact_and_oov(tmp_path):
    config = TrainingConfig(vector_size=12, min_count=1, epochs=6, sample=0)
    meta = train_word2vec(corpus(), tmp_path / "first", "fixture", config)
    model, loaded = load_word2vec(tmp_path / "first", "fixture")
    assert loaded == meta
    assert meta["schema_version"] == 2
    assert meta["preprocessing_condition"] == "B"
    assert "condition B" in meta["preprocessing"]
    assert meta["baseline_tokenizer"] == baseline_tokenizer_spec()
    assert len(model.wv) == 7
    result = neighbors(model, "INSULIN", 3)
    assert result["status"] == "ok" and len(result["neighbors"]) == 3
    assert all(np.isfinite(item["cosine"]) for item in result["neighbors"])
    assert neighbors(model, "zzznothinghere")["status"] == "oov"
    assert neighbors(model, "GLP-1")["status"] == "oov"
    assert neighbors(model, "GLP-1 receptor")["status"] == "invalid_query"
    second_meta = train_word2vec(corpus(), tmp_path / "second", "fixture", config)
    second, _ = load_word2vec(tmp_path / "second")
    np.testing.assert_array_equal(model.wv.vectors, second.wv.vectors)
    assert meta["vectors_sha256"] == second_meta["vectors_sha256"]
    with pytest.raises(ValueError, match="快照"):
        load_word2vec(tmp_path / "first", "different")
    path = tmp_path / "first/word2vec.model"
    path.write_bytes(path.read_bytes() + b"corruption")
    with pytest.raises(ValueError, match="SHA"):
        load_word2vec(tmp_path / "first")


def test_validation_and_empty_training(tmp_path):
    with pytest.raises(ValueError):
        TrainingConfig(workers=2).validate()
    with pytest.raises(ValueError):
        TrainingConfig(epochs=0).validate()
    with pytest.raises(ValueError):
        sentence_records({})
    docs = corpus()
    docs["D2"].pmid = "1"
    with pytest.raises(ValueError, match="PMID"):
        sentence_records(docs)
    with pytest.raises(ValueError, match="足夠"):
        train_word2vec(corpus(), tmp_path, config=TrainingConfig(min_count=100))
    assert not (tmp_path / "metadata.json").exists()


def test_hw1_compound_decimal_and_unicode_training_sequences(tmp_path):
    text = "GLP-1 improves HbA1c by 1.5. Café CAFE\u0301 β-cells receive GLP‑1. Patient’s STRASSE Straße improve."
    docs = {"1": Document("D1", "Excluded title", [TextBlock("a0", "abstract", "Excluded label", text)],
                          pmid="1", content_scope="abstract")}
    records = sentence_records(docs)
    expected = [token.term for token in hw1_tokenize(text)]
    assert [term for record in records for term in record["tokens"]] == expected
    assert expected.count("glp-1") == 2
    assert expected.count("café") == 2 and expected.count("strasse") == 2
    assert "1.5" in expected and "patient's" in expected and "β-cells" in expected
    assert not {"glp", "1", "5", "β", "cells"}.intersection(expected)
    for record in records:
        assert record["tokens"] == [token.term for token in hw1_tokenize(text[record["start"]:record["end"]])]
    meta = train_word2vec(docs, tmp_path, "compound-fixture", TrainingConfig(vector_size=8, min_count=1, epochs=2, sample=0))
    model, loaded = load_word2vec(tmp_path, "compound-fixture")
    assert meta == loaded
    for query, term in [("GLP-1", "glp-1"), ("GLP‑1", "glp-1"), ("1.5", "1.5"),
                        ("CAFE\u0301", "café"), ("Straße", "strasse"), ("Patient’s", "patient's"), ("by", "by")]:
        result = neighbors(model, query)
        assert result["status"] == "ok" and result["term"] == term
    assert neighbors(model, "GLP-1 receptor")["status"] == "invalid_query"
    assert "兩詞" in neighbors(model, "GLP-1 receptor")["message"]


@pytest.mark.parametrize("change", [
    "legacy_schema", "missing_spec", "old_regex", "normalization", "dependency", "source_hash", "stopwords", "expansion",
])
def test_model_rejects_missing_or_stale_tokenizer_even_for_identical_corpus(tmp_path, monkeypatch, change):
    import ir_hw2.embeddings as embeddings
    meta = train_word2vec(corpus(), tmp_path, "same-corpus", TrainingConfig(vector_size=8, min_count=1, epochs=2, sample=0))
    mutated = deepcopy(meta)
    if change == "legacy_schema":
        mutated["schema_version"] = 1
        mutated.pop("baseline_tokenizer")
    elif change == "missing_spec":
        mutated.pop("baseline_tokenizer")
    elif change == "old_regex":
        mutated["baseline_tokenizer"]["regex"] = r"[\p{L}\p{M}\p{N}]+"
    elif change == "normalization":
        mutated["baseline_tokenizer"]["normalization"]["casefold"] = False
    elif change == "dependency":
        mutated["baseline_tokenizer"]["dependencies"]["regex"] = "different-version"
    elif change == "source_hash":
        mutated["baseline_tokenizer"]["source_sha256"] = "0" * 64
    elif change == "stopwords":
        mutated["baseline_tokenizer"]["remove_stopwords"] = True
    else:
        mutated["baseline_tokenizer"]["search_feature_expansion"] = True
    (tmp_path / "metadata.json").write_text(json.dumps(mutated), encoding="utf-8")

    def should_not_deserialize(*args, **kwargs):
        pytest.fail("An incompatible tokenizer must be rejected before deserializing the model")

    monkeypatch.setattr(embeddings.Word2Vec, "load", should_not_deserialize)
    with pytest.raises(ValueError, match="tokenizer.*重新訓練|tokenizer.*不符"):
        load_word2vec(tmp_path, "same-corpus")


def test_model_compatibility_is_independent_of_statistical_pipeline_version(tmp_path, monkeypatch):
    meta = train_word2vec(corpus(), tmp_path, "same-corpus", TrainingConfig(vector_size=8, min_count=1, epochs=2, sample=0))
    monkeypatch.setattr(analysis, "PIPELINE_VERSION", "only-statistical-log-base-changed")
    _, loaded = load_word2vec(tmp_path, "same-corpus")
    assert loaded == meta


def test_model_compatibility_preserves_same_tokenizer_under_previous_baseline_label(tmp_path):
    meta = train_word2vec(corpus(), tmp_path, "same-corpus", TrainingConfig(vector_size=8, min_count=1, epochs=2, sample=0))
    meta.pop("preprocessing_condition")
    meta["preprocessing"] = meta["preprocessing"].replace("condition B", "condition A")
    (tmp_path / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    _, loaded = load_word2vec(tmp_path, "same-corpus")
    assert loaded == meta


def test_baseline_sentences_retain_stopwords_without_stemming():
    docs = {"1": Document("D1", "", [TextBlock("a0", "abstract", "", "The patients and treatments were improving.")],
                          pmid="1", content_scope="abstract")}
    assert sentence_records(docs)[0]["tokens"] == ["the", "patients", "and", "treatments", "were", "improving"]


@pytest.mark.parametrize("artifact", ["sentences", "vectors"])
def test_model_tokenizer_compatibility_does_not_bypass_existing_hash_checks(tmp_path, artifact):
    meta = train_word2vec(corpus(), tmp_path, "same-corpus", TrainingConfig(vector_size=8, min_count=1, epochs=2, sample=0))
    if artifact == "sentences":
        path = tmp_path / "sentences.jsonl"
        path.write_bytes(path.read_bytes() + b"\n")
    else:
        meta["vectors_sha256"] = "0" * 64
        (tmp_path / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    with pytest.raises(ValueError, match="SHA|向量"):
        load_word2vec(tmp_path, "same-corpus")
