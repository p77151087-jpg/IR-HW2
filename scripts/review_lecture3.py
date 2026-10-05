"""Read-only lecture-3 diagnostics; never rebuild the index or formal experiment."""
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ir_hw1.index import get_postings, get_tfidf
from ir_hw1.search import search, doc_sort_key


def main():
    path = ROOT / "data/index.json"
    original = path.read_bytes()
    index = json.loads(original)
    postings = get_postings(index, stemming=True, relevance=True)
    existing = get_tfidf(index, stemming=True, relevance=True)
    n = len(existing["norms"])
    definitions = {
        "legacy": (math.log, lambda df: math.log((n + 1) / (df + 1)) + 1),
        "unsmoothed_ln": (math.log, lambda df: math.log(n / df)),
        "idf_base_only": (math.log, lambda df: math.log10(n / df)),
        "lecture_log10": (math.log10, lambda df: math.log10(n / df)),
    }
    profiles = {}
    for label, (tf_log, idf_fn) in definitions.items():
        idf = {term: idf_fn(len(hits)) for term, hits in postings.items()}
        sq = dict.fromkeys(existing["norms"], 0.0)
        for term, hits in postings.items():
            for doc_id, hit in hits.items():
                sq[doc_id] += ((1 + tf_log(hit["tf"])) * idf[term]) ** 2
        profiles[label] = (idf, {k: math.sqrt(v) for k, v in sq.items()})
    queries = []
    for query in ("semaglutide", "insulin", "obesity treatment", "GLP-1",
                  "semaglutide kidney disease", "tirzepatide cardiovascular risk"):
        current = search(index, query, "RELEVANCE", stemming=True)
        terms = list(dict.fromkeys(t for t in current.terms if t in postings))
        computed = {}
        ranked = {}
        for label, (idf, norms) in profiles.items():
            tf_log = definitions[label][0]
            qnorm = math.sqrt(sum(idf[t] ** 2 for t in terms))
            dots = dict.fromkeys(current.document_ids, 0.0)
            for term in terms:
                for doc_id, hit in postings[term].items():
                    dots[doc_id] += idf[term] ** 2 * (1 + tf_log(hit["tf"]))
            scores = {d: min(1.0, v / (qnorm * norms[d])) if qnorm * norms[d] else 0.0
                      for d, v in dots.items()}
            computed[label] = scores
            ranked[label] = sorted(scores, key=lambda d: (-scores[d], doc_sort_key(d)))[:10]
        legacy_error = max(abs(computed["legacy"][d] - current.scores[d]) for d in current.document_ids)
        idf_base_error = max(abs(computed["unsmoothed_ln"][d] - computed["idf_base_only"][d])
                             for d in current.document_ids)
        assert legacy_error < 1e-12 and idf_base_error < 1e-12
        assert ranked["legacy"] == current.document_ids[:10]
        top_doc = current.document_ids[0]
        idf, norms = profiles["legacy"]
        qnorm = math.sqrt(sum(idf[t] ** 2 for t in terms))
        contributions = []
        for term in terms:
            tf = postings[term].get(top_doc, {}).get("tf", 0)
            contribution = ((1 + math.log(tf)) * idf[term] ** 2 / (qnorm * norms[top_doc])) if tf else 0
            contributions.append({"term": term, "tf": tf, "df": len(postings[term]),
                                  "idf": idf[term], "cosine_contribution": contribution})
        assert abs(sum(r["cosine_contribution"] for r in contributions) - current.scores[top_doc]) < 1e-12
        queries.append({"query": query, "terms": terms, "matched_documents": len(current.document_ids),
                        "top10": ranked, "legacy_recalculation_max_error": legacy_error,
                        "pure_idf_base_change_max_error": idf_base_error,
                        "legacy_vs_lecture_top10_shared": len(set(ranked["legacy"]) & set(ranked["lecture_log10"])),
                        "top_document": top_doc, "legacy_score": current.scores[top_doc],
                        "query_norm": qnorm, "document_norm": norms[top_doc], "contributions": contributions})
    assert path.read_bytes() == original
    wf = 1 + math.log10(2)
    docnorm = math.sqrt(1 + 1 + wf ** 2)
    qnorm = math.sqrt(math.log10(20) ** 2 + 2 ** 2 + 3 ** 2)
    slide59 = {"N": 1000000, "insurance_document_weight": wf, "document_norm": docnorm,
               "unnormalized_query_score": (2 + 3 * wf) / docnorm,
               "cosine_after_query_normalization": (2 + 3 * wf) / (docnorm * qnorm)}
    out = ROOT / "reports/hw2/lecture3_diagnostics.json"
    result = {"recorded_at_utc": datetime.now(timezone.utc).isoformat(), "documents": n,
              "index_sha256": hashlib.sha256(original).hexdigest(),
              "index_unchanged": True, "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "scope": "Same existing Porter relevance postings and binary query TF for every profile; only weights differ. This is ranking sensitivity, NOT relevance quality.",
              "profiles": {"legacy": "(1+ln(tf)) * (ln((N+1)/(DF+1))+1)",
                           "unsmoothed_ln": "(1+ln(tf)) * ln(N/DF)",
                           "idf_base_only": "(1+ln(tf)) * log10(N/DF)",
                           "lecture_log10": "(1+log10(tf)) * log10(N/DF)"},
              "query_weighting": "Distinct in-vocabulary terms; query TF=1; IDF weighting and full L2 normalization",
              "queries": queries, "slide59_recalculation": slide59}
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"documents": n, "index_unchanged": True,
                      "queries": [{"query": r["query"], "shared_top10": r["legacy_vs_lecture_top10_shared"],
                                   "idf_base_error": r["pure_idf_base_change_max_error"]} for r in queries],
                      "slide59": slide59}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
