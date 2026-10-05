"""Log-TF, smoothed IDF and cosine ranking over Boolean candidates."""
from math import log, sqrt

TFIDF_VERSION = "log-tf-smooth-idf-cosine-v1"


def build_tfidf(postings: dict, document_ids) -> dict:
    """Precompute IDF and full-document norms, including empty documents in N."""
    squared_norms = dict.fromkeys(document_ids, 0.0)
    count = len(squared_norms)
    idf = {}
    for term, hits in postings.items():
        idf[term] = log((count + 1) / (len(hits) + 1)) + 1
        for doc_id, posting in hits.items():
            weight = (1 + log(posting["tf"])) * idf[term]
            squared_norms[doc_id] += weight * weight
    return {"idf": idf, "norms": {doc_id: sqrt(value) for doc_id, value in squared_norms.items()}}


def cosine_scores(postings: dict, statistics: dict, terms: list[str], candidates: set[str]) -> dict[str, float]:
    """Use distinct in-vocabulary query terms (query TF=1), keeping all candidates."""
    idf, norms = statistics["idf"], statistics["norms"]
    query_weights = {term: idf[term] for term in terms if term in idf}
    query_norm = sqrt(sum(weight * weight for weight in query_weights.values()))
    scores = dict.fromkeys(candidates, 0.0)
    if not query_norm or not candidates:
        return scores
    for term, query_weight in query_weights.items():
        for doc_id, posting in postings[term].items():
            if doc_id in candidates:
                scores[doc_id] += query_weight * (1 + log(posting["tf"])) * idf[term]
    for doc_id, dot in scores.items():
        denominator = query_norm * norms[doc_id]
        # Clamp floating-point roundoff at 1; zero vectors have no similarity.
        scores[doc_id] = min(1.0, dot / denominator) if denominator else 0.0
    return scores
