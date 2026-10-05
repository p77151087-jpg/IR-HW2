"""Relevance retrieval, with compatible Boolean and exact phrase APIs."""
import re
from dataclasses import dataclass, field
from time import perf_counter

from .index import get_postings, get_tfidf
from .models import Document
from .preprocessing import query_terms, tokenize
from .relevance import relevance_query
from .storage import doc_sort_key
from .tfidf import cosine_scores


@dataclass
class SearchResponse:
    document_ids: list[str]
    terms: list[str]
    missing_terms: list[str]
    elapsed_ms: float
    warning: str = ""
    stemming: bool = False
    phrase_locations: dict[str, dict[str, list[tuple[int, int]]]] = field(default_factory=dict)
    ranking: str = "document_id"
    scores: dict[str, float] = field(default_factory=dict)
    relevance: bool = False
    query_message: str = ""


def phrase_terms(query: str) -> list[str]:
    """Preserve order/repetition; accept optional quotes around one whole phrase."""
    query = query.strip()
    if len(query) >= 2 and (query[0], query[-1]) in {('"', '"'), ('“', '”')}:
        query = query[1:-1].strip()
    tokens = tokenize(query)
    if not tokens:
        return []
    if (tokens[0].start != 0 or tokens[-1].end != len(query)
            or any(not query[a.end:b.start].isspace() for a, b in zip(tokens, tokens[1:]))):
        raise ValueError("精準片語請輸入以空白分隔的完整單字，例如 cancer treatment；可在整段外加雙引號，不支援混合標點或多組片語。")
    return [token.term for token in tokens]


def phrase_locations(document: Document, postings: dict, terms: list[str]) -> dict[str, list[tuple[int, int]]]:
    """Join original offsets, requiring only whitespace between adjacent words.

    Each next word must start exactly after the preceding word's whitespace.
    This disallows intervening words, punctuation, and crossing text blocks.
    """
    blocks = {block.id: block.text for block in document.blocks}
    by_term = {
        term: {(bid, start): end for bid, start, end in
               postings.get(term, {}).get(document.pmcid, {}).get("locations", [])}
        for term in set(terms)
    }
    matches: dict[str, list[tuple[int, int]]] = {}
    if not terms:
        return matches
    for (bid, start), end in by_term[terms[0]].items():
        text = blocks[bid]
        for term in terms[1:]:
            next_start = end
            while next_start < len(text) and text[next_start].isspace():
                next_start += 1
            next_end = by_term[term].get((bid, next_start))
            if next_start == end or next_end is None:
                break
            end = next_end
        else:
            matches.setdefault(bid, []).append((start, end))
    return matches


def search(index: dict, query: str, mode: str = "AND", *, stemming: bool = False,
           documents: dict[str, Document] | None = None, ranking: str = "document_id") -> SearchResponse:
    start = perf_counter()
    if mode not in {"RELEVANCE", "AND", "OR", "PHRASE"}:
        raise ValueError("搜尋模式必須是 RELEVANCE、AND、OR 或 PHRASE（精準片語）")
    if ranking not in {"document_id", "tfidf"}:
        raise ValueError("排序必須是 document_id（文章編號）或 tfidf（相關性）")
    if len(query) > 2000:
        raise ValueError("查詢最多 2,000 個字元")
    warning = ""
    query_message = ""
    relevance = mode == "RELEVANCE"
    if relevance:
        ranking = "tfidf"
        terms, query_message = relevance_query(query, stemming=stemming)
        if re.search(r'\b(?:AND|OR|NOT)\b|[\"“”()]', query):
            warning = "目前依關鍵字相關性搜尋；引號、括號及布林運算式不會啟用特殊搜尋語法。"
    elif mode == "PHRASE":
        if documents is None:
            raise ValueError("精準片語搜尋需要與索引相同版本的文章快照。")
        terms = phrase_terms(query)
        if stemming:
            warning = "精準片語使用原詞比對，本次不套用 Porter 詞幹還原。"
        stemming = False
    else:
        terms = query_terms(query, stemming=stemming)
        if re.search(r'\b(?:AND|OR|NOT)\b|[\"“”()]', query):
            warning = "AND／OR 不解析布林運算式、引號片語或括號。要找連續詞組，請選「精準片語」；本次仍按一般單詞處理。"
    postings = get_postings(index, stemming=stemming, relevance=relevance)
    unique_terms = list(dict.fromkeys(terms))
    missing = [t for t in unique_terms if t not in postings]
    candidates = [set(postings.get(term, {})) for term in unique_terms]
    result: set[str] = set()
    if candidates:
        if mode in {"AND", "PHRASE"}:
            candidates.sort(key=len)
            result = candidates[0].copy()
            for ids in candidates[1:]:
                result.intersection_update(ids)
                if not result:
                    break
        else:
            for ids in candidates:
                result.update(ids)
    phrases = {}
    if mode == "PHRASE":
        for doc_id in result:
            locations = phrase_locations(documents[doc_id], postings, terms)
            if locations:
                phrases[doc_id] = locations
        result = set(phrases)
    scores = {}
    if ranking == "tfidf":
        scores = cosine_scores(postings, get_tfidf(index, stemming=stemming, relevance=relevance), unique_terms, result)
        if relevance:
            scores = {doc_id: score for doc_id, score in scores.items() if score > 0}
            result = set(scores)
        document_ids = sorted(result, key=lambda doc_id: (-scores[doc_id], doc_sort_key(doc_id)))
    else:
        document_ids = sorted(result, key=doc_sort_key)
    return SearchResponse(document_ids, terms, missing, (perf_counter() - start) * 1000,
                          warning, stemming, phrases, ranking, scores, relevance, query_message)
