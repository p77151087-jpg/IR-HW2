"""Hand-calculated cosine scores and ranking lifecycle; never edit live data."""
import json
import math
import socket
from collections import Counter

import pytest

from ir_hw1.cli import main
from ir_hw1.index import build_index, load_snapshot, save_index
from ir_hw1.models import Document, TextBlock
from ir_hw1.preprocessing import query_terms, stem_term, tokenize
from ir_hw1.search import search
from ir_hw1.storage import StorageError
from ir_hw1.sync import sync_raw_folder


def corpus(texts):
    docs = {doc_id: Document(doc_id, "Metadata only", [TextBlock("b0", "abstract", "Abstract", text)])
            for doc_id, text in texts.items()}
    return docs, build_index(docs)


def test_hand_calculated_log_tf_idf_and_full_document_norm():
    _, index = corpus({"PMC1": "cancer background background", "PMC2": "cancer cancer treatment",
                       "PMC3": "treatment", "PMC4": ""})
    # N includes the empty article. DF counts articles, not occurrences.
    common = 1 + math.log(5 / 3)
    rare = 1 + math.log(5 / 2)
    repeated = 1 + math.log(2)
    result = search(index, "cancer", ranking="tfidf")
    assert result.document_ids == ["PMC2", "PMC1"]
    assert result.scores == pytest.approx({
        "PMC1": common / math.sqrt(common**2 + (repeated * rare)**2),
        "PMC2": repeated / math.sqrt(repeated**2 + 1),
    })
    assert index["tfidf"]["idf"]["cancer"] == pytest.approx(common)
    assert index["tfidf"]["norms"]["PMC4"] == 0


def test_rare_query_word_weighs_more_and_ties_use_numeric_ids():
    _, index = corpus({"PMC10": "common", "PMC2": "common", "PMC3": "rare", "PMC4": "common"})
    result = search(index, "common rare", "OR", ranking="tfidf")
    assert result.document_ids == ["PMC3", "PMC2", "PMC4", "PMC10"]
    assert result.scores["PMC3"] > result.scores["PMC2"]
    assert result.scores["PMC2"] == result.scores["PMC10"]


@pytest.mark.parametrize("mode", ["AND", "OR", "PHRASE"])
def test_ranking_keeps_match_set_and_phrase_offsets(mode):
    docs, index = corpus({"PMC1": "cancer treatment background", "PMC2": "treatment cancer",
                          "PMC3": "cancer treatment", "PMC4": "cancer"})
    plain = search(index, "cancer treatment", mode, documents=docs)
    ranked = search(index, "cancer treatment", mode, documents=docs, ranking="tfidf")
    assert set(ranked.document_ids) == set(plain.document_ids)
    assert ranked.phrase_locations == plain.phrase_locations
    assert ranked.document_ids[0] == ("PMC2" if mode != "PHRASE" else "PMC3")
    assert all(0 < score <= 1 for score in ranked.scores.values())


def test_query_deduplication_unknowns_and_zero_vectors():
    _, index = corpus({"PMC1": "cancer cancer", "PMC2": ""})
    single = search(index, "cancer", ranking="tfidf")
    repeated = search(index, "CANCER cancer unknown", "OR", ranking="tfidf")
    assert single.scores == repeated.scores == {"PMC1": 1.0}
    assert repeated.missing_terms == ["unknown"]
    for query in ("", "...", "unknown", "cancer unknown"):
        response = search(index, query, ranking="tfidf")
        assert response.document_ids == [] and response.scores == {}
    assert search(build_index({}), "cancer", ranking="tfidf").scores == {}
    with pytest.raises(ValueError, match="排序"):
        search(index, "cancer", ranking="invalid")


def test_porter_merges_tf_and_df_and_phrase_uses_original_vectors():
    docs, index = corpus({"PMC1": "therapy therapies other", "PMC2": "therapy", "PMC3": "other"})
    idf = 1 + math.log(4 / 3)
    repeated = 1 + math.log(2)
    porter = search(index, "therapy therapies", stemming=True, ranking="tfidf")
    assert porter.terms == ["therapi"]
    assert porter.scores == pytest.approx({"PMC1": repeated / math.sqrt(repeated**2 + 1), "PMC2": 1})
    assert index["porter_tfidf"]["idf"]["therapi"] == pytest.approx(idf)
    original = search(index, "therapy", ranking="tfidf")
    phrase = search(index, "therapy", "PHRASE", stemming=True, documents=docs, ranking="tfidf")
    assert not phrase.stemming and phrase.scores == original.scores
    assert original.scores["PMC1"] != porter.scores["PMC1"]


@pytest.mark.parametrize("damage", ["legacy", "missing", "porter", "formula", "idf", "norm"])
def test_upgrade_and_repair_without_reimport(stored, damage):
    sync_raw_folder(stored)
    _, index = load_snapshot(stored)
    original = {name: (stored / name).read_bytes() for name in ("processed/articles.jsonl", "manifest.jsonl", "raw/synthetic.xml")}
    if damage == "legacy":
        index["version"] = 2
        for key in ("tfidf_version", "tfidf", "porter_tfidf"):
            index.pop(key)
    elif damage == "missing":
        index.pop("tfidf")
    elif damage == "porter":
        index.pop("porter_tfidf")
    elif damage == "formula":
        index["tfidf_version"] = "old"
    elif damage == "idf":
        index["tfidf"]["idf"].pop("cancer")
    else:
        index["porter_tfidf"]["norms"]["PMC1"] = "broken"
    save_index(stored, index)
    with pytest.raises(StorageError):
        load_snapshot(stored)
    assert sync_raw_folder(stored).rebuilt
    _, repaired = load_snapshot(stored)
    assert search(repaired, "cancer", ranking="tfidf").scores
    assert all((stored / name).read_bytes() == content for name, content in original.items())
    assert not sync_raw_folder(stored).rebuilt


def test_corpus_changes_refresh_both_ranking_tables(stored):
    sync_raw_folder(stored)
    _, before = load_snapshot(stored)
    raw = stored / "raw/extra.xml"
    raw.write_text('<article><front><article-meta><article-id pub-id-type="pmc">4</article-id>'
                   '<title-group><article-title>Cancer</article-title></title-group>'
                   '</article-meta></front></article>', encoding="utf-8")
    sync_raw_folder(stored)
    _, added = load_snapshot(stored)
    for key in ("tfidf", "porter_tfidf"):
        assert added[key]["idf"]["cancer"] == pytest.approx(1 + math.log(5 / 4))
    assert search(added, "cancer", ranking="tfidf").document_ids[0] == "PMC4"
    raw.write_text(raw.read_text(encoding="utf-8").replace("Cancer", "Therapies"), encoding="utf-8")
    sync_raw_folder(stored)
    _, changed = load_snapshot(stored)
    assert "PMC4" not in search(changed, "cancer", ranking="tfidf").scores
    assert search(changed, "therapy", stemming=True, ranking="tfidf").scores == {"PMC4": 1.0}
    raw.unlink()
    sync_raw_folder(stored)
    _, removed = load_snapshot(stored)
    for key in ("tfidf", "porter_tfidf"):
        assert removed[key] == before[key]


def test_cli_automatically_scores_and_uses_persisted_data_offline(stored, capsys, monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", lambda *a: pytest.fail("TF-IDF must stay offline"))
    assert main(["--data-dir", str(stored), "search", "cancer treatment", "--mode", "OR"]) == 0
    response, _ = json.JSONDecoder().raw_decode(capsys.readouterr().out)
    assert response["ranking"] == "tfidf"
    assert response["document_ids"] == ["PMC2", "PMC1", "PMC3"]
    persisted = (stored / "index.json").read_bytes()
    _, reloaded = load_snapshot(stored)
    assert response["scores"] == search(reloaded, "cancer treatment", "OR", ranking="tfidf").scores
    assert (stored / "index.json").read_bytes() == persisted


@pytest.mark.parametrize("stemming", [False, True])
def test_real_corpus_scores_agree_with_direct_document_vectors(real_corpus, stemming):
    docs, index = load_snapshot(real_corpus)
    counts = {doc_id: Counter(stem_term(t.term) if stemming else t.term
                             for block in doc.blocks for t in tokenize(block.text))
              for doc_id, doc in docs.items()}
    df = Counter(term for terms in counts.values() for term in terms)
    idf = {term: 1 + math.log((len(docs) + 1) / (frequency + 1)) for term, frequency in df.items()}
    vectors = {doc_id: {term: (1 + math.log(tf)) * idf[term] for term, tf in terms.items()}
               for doc_id, terms in counts.items()}
    for query in ("cancer treatment", "therapies patients", "HIV unknownxyz", "..."):
        weights = {term: idf[term] for term in query_terms(query, stemming=stemming) if term in idf}
        qnorm = math.sqrt(sum(v * v for v in weights.values()))
        result = search(index, query, "OR", stemming=stemming, ranking="tfidf")
        expected = {}
        for doc_id, vector in vectors.items():
            dot = sum(weight * vector.get(term, 0) for term, weight in weights.items())
            if dot:
                expected[doc_id] = dot / (qnorm * math.sqrt(sum(v * v for v in vector.values())))
        assert result.scores == pytest.approx(expected)
        assert list(result.scores[d] for d in result.document_ids) == sorted(result.scores.values(), reverse=True)
