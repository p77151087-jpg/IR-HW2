"""Our inverted index: term -> doc ID -> tf + original block offsets."""
import json
from datetime import datetime, timezone
from math import isfinite
from pathlib import Path

from .models import Document
from .preprocessing import PORTER_PREPROCESSING, PREPROCESSING, stem_term, tokenize
from .relevance import RELEVANCE_PREPROCESSING, relevance_tokens
from .sentence_splitter import SENTENCE_VERSION
from .storage import DEFAULT_DATA, StorageError, corpus_fingerprint, load_documents, write_json
from .tfidf import TFIDF_VERSION, build_tfidf
from .xml_parser import PARSER_VERSION

INDEX_VERSION = 5


def build_index(documents: dict[str, Document]) -> dict:
    postings: dict = {}
    porter_postings: dict = {}
    relevance_postings: dict = {}
    porter_relevance_postings: dict = {}
    for doc_id, document in documents.items():
        for block in document.blocks:
            for token in tokenize(block.text):
                for table, term in ((postings, token.term), (porter_postings, stem_term(token.term))):
                    posting = table.setdefault(term, {}).setdefault(doc_id, {"tf": 0, "locations": []})
                    posting["tf"] += 1
                    posting["locations"].append([block.id, token.start, token.end])
            for token in relevance_tokens(block.text, include_components=True):
                for table, term in ((relevance_postings, token.term),
                                    (porter_relevance_postings, stem_term(token.term))):
                    posting = table.setdefault(term, {}).setdefault(doc_id, {"tf": 0, "locations": []})
                    posting["tf"] += 1
                    posting["locations"].append([block.id, token.start, token.end])
    return {"version": INDEX_VERSION, "preprocessing": PREPROCESSING.copy(), "parser": PARSER_VERSION,
            "porter_preprocessing": PORTER_PREPROCESSING.copy(), "porter_postings": porter_postings,
            "tfidf_version": TFIDF_VERSION, "tfidf": build_tfidf(postings, documents),
            "porter_tfidf": build_tfidf(porter_postings, documents),
            "relevance_preprocessing": RELEVANCE_PREPROCESSING.copy(),
            "relevance_postings": relevance_postings, "porter_relevance_postings": porter_relevance_postings,
            "relevance_tfidf": build_tfidf(relevance_postings, documents),
            "porter_relevance_tfidf": build_tfidf(porter_relevance_postings, documents),
            "sentence_rules": SENTENCE_VERSION, "created_at": datetime.now(timezone.utc).isoformat(),
            "corpus_sha256": corpus_fingerprint(documents), "document_count": len(documents), "postings": postings}


def save_index(data_dir: Path, index: dict) -> None:
    write_json(data_dir / "index.json", index)


def get_postings(index: dict, *, stemming: bool = False, relevance: bool = False) -> dict:
    """Select matching and highlighting data without changing the shared index."""
    if stemming and index.get("porter_preprocessing") != PORTER_PREPROCESSING:
        raise StorageError("Porter 索引設定不一致，請重新建立索引。")
    if relevance and index.get("relevance_preprocessing") != RELEVANCE_PREPROCESSING:
        raise StorageError("相關性搜尋的前處理設定不一致，請重新建立索引。")
    postings = index.get(("porter_" if stemming else "") + ("relevance_" if relevance else "") + "postings")
    if not isinstance(postings, dict):
        raise StorageError("缺少搜尋索引或索引損壞，請重新建立索引。")
    return postings


def get_tfidf(index: dict, *, stemming: bool = False, relevance: bool = False) -> dict:
    statistics = index.get(("porter_" if stemming else "") + ("relevance_" if relevance else "") + "tfidf")
    if (index.get("tfidf_version") != TFIDF_VERSION or not isinstance(statistics, dict)
            or not isinstance(statistics.get("idf"), dict) or not isinstance(statistics.get("norms"), dict)):
        raise StorageError("TF-IDF 索引缺少資料或版本不一致，請重新建立索引。")
    return statistics


def load_snapshot(data_dir: Path = DEFAULT_DATA) -> tuple[dict[str, Document], dict]:
    documents = load_documents(data_dir)
    if not documents:
        raise StorageError("尚無文章，請先下載或匯入 XML，再建立索引。")
    try:
        index = json.loads((data_dir / "index.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError) as exc:
        raise StorageError("尚未建立索引或索引損壞，請執行 python -m ir_hw1.cli build。") from exc
    if not isinstance(index, dict):
        raise StorageError("索引格式損壞，請重新建立索引。")
    expected = (INDEX_VERSION, PREPROCESSING, PARSER_VERSION, SENTENCE_VERSION, corpus_fingerprint(documents), len(documents))
    observed = tuple(index.get(k) for k in ("version", "preprocessing", "parser", "sentence_rules", "corpus_sha256", "document_count"))
    if observed != expected or not isinstance(index.get("postings"), dict):
        raise StorageError("文章、前處理或索引版本不一致，請重新匯入並建索引。")
    get_postings(index, stemming=True)
    for stemming, relevance in ((False, False), (True, False), (False, True), (True, True)):
        statistics = get_tfidf(index, stemming=stemming, relevance=relevance)
        if (statistics["idf"].keys() != get_postings(index, stemming=stemming, relevance=relevance).keys()
                or statistics["norms"].keys() != documents.keys()
                or any(not isinstance(value, (int, float)) or not isfinite(value) or value < 1
                       for value in statistics["idf"].values())
                or any(not isinstance(value, (int, float)) or not isfinite(value) or value < 0
                       for value in statistics["norms"].values())):
            raise StorageError("TF-IDF 索引資料損壞，請重新建立索引。")
    return documents, index
