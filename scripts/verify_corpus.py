"""Reproducible scan oracle for mixed abstract/full-text corpora."""
import hashlib
import json
import platform
import statistics
import subprocess
import sys
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ir_hw1.corpus import reusable_license
from ir_hw1.index import build_index, load_snapshot
from ir_hw1.preprocessing import query_terms, tokenize
from ir_hw1.search import search
from ir_hw1.storage import DEFAULT_DATA, corpus_fingerprint, json_bytes, write_json
from ir_hw1.xml_parser import articles_in_xml, first, parse_article, readable

QUERIES = ["cancer", "treatment", "cancer treatment", "hiv", "antiretroviral therapy",
           "patients", "infection", "clinical", "immune", "cells", "virus", "health",
           "study", "risk", "covid-19", "3.5", "mitochondria", "dna", "age", "mortality",
           "nonexistentxyz", "cancer nonexistentxyz", "CANCER cancer", "...", ""]


def main():
    start = perf_counter()
    documents, index = load_snapshot()
    initial_load_ms = (perf_counter() - start) * 1000
    assert documents
    raw_sizes = {}
    body_terms = {}
    for doc in documents.values():
        raw = (DEFAULT_DATA / doc.raw_path).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == doc.sha256
        article = next(a for a in articles_in_xml(raw) if parse_article(a).pmcid == doc.pmcid)
        parsed = parse_article(article, content_scope=doc.content_scope)
        assert parsed.blocks == doc.blocks and parsed.statistics == doc.statistics
        if doc.content_scope == "abstract":
            assert all(b.section.startswith("摘要") for b in doc.blocks) and not doc.back_blocks
        body_terms[doc.pmcid] = {t.term for t in tokenize(readable(first(article, "body")))}
        assert doc.acquired_at and doc.source_url
        raw_sizes[doc.raw_path] = len(raw)
    term_sets = {key: {t.term for b in doc.blocks for t in tokenize(b.text)} for key, doc in documents.items()}
    query_results, timings = [], []
    for query in QUERIES:
        terms = set(query_terms(query))
        for mode in ["AND", "OR"]:
            expected = {key for key, values in term_sets.items() if terms and
                        (terms <= values if mode == "AND" else bool(terms & values))}
            response = search(index, query, mode)
            assert set(response.document_ids) == expected, (query, mode)
            query_results.append({"query": query, "mode": mode, "matches": response.document_ids})
            for _ in range(20):
                timings.append(search(index, query, mode).elapsed_ms)
    excluded_evidence = []
    all_abstract = set().union(*term_sets.values())
    for key, terms in body_terms.items():
        if documents[key].content_scope != "abstract":
            continue
        eligible = sorted(t for t in terms - all_abstract if t.isalpha() and len(t) >= 9)
        if eligible:
            term = eligible[0]
            assert search(index, term).document_ids == []
            excluded_evidence.append({"pmcid": key, "body_only_term": term, "matches": []})
    start = perf_counter()
    rebuilt = build_index(documents)
    build_seconds = perf_counter() - start
    assert rebuilt["postings"] == index["postings"]
    # Cold Python process startup, parse and integrity checking, not disk-cache eviction.
    fresh_loads = []
    for _ in range(3):
        result = subprocess.run([sys.executable, "-c", "from time import perf_counter; t=perf_counter(); from ir_hw1.index import load_snapshot; d,i=load_snapshot(); print((perf_counter()-t)*1000)"],
                                cwd=ROOT, check=True, capture_output=True, text=True)
        fresh_loads.append(float(result.stdout.strip()))
    result = {"kind": "real_source_scoped_corpus", "environment": {"python": sys.version, "platform": platform.platform(), "processor": platform.processor()},
              "content_scopes": {key: doc.content_scope for key, doc in documents.items()},
              "documents": len(documents), "corpus_sha256": corpus_fingerprint(documents), "raw_bytes": sum(raw_sizes.values()),
              "index_bytes": (DEFAULT_DATA / "index.json").stat().st_size, "terms": len(index["postings"]),
              "total_words": sum(d.statistics["words"] for d in documents.values()),
              "total_sentences": sum(d.statistics["sentences"] for d in documents.values()),
              "build_seconds": build_seconds, "initial_load_ms": initial_load_ms,
              "fresh_process_load_ms": fresh_loads, "fresh_process_note": "Includes imports; filesystem cache not flushed.",
              "warm_query_median_ms": statistics.median(timings), "warm_query_p95_ms": sorted(timings)[int(len(timings) * .95) - 1],
              "warm_query_samples": len(timings), "oracle_checks": len(query_results),
              "excluded_body_terms": excluded_evidence, "queries": query_results}
    write_json(ROOT / "reports/verification-source-scope.json", result)
    write_json(ROOT / "reports/corpus-inventory-source-scope.json", [{"pmcid": d.pmcid, "title": d.title, "content_scope": d.content_scope, "license": d.license,
        "license_url": d.license_url, "source_url": d.source_url, "acquired_at": d.acquired_at,
        "raw_path": d.raw_path, "sha256": d.sha256, "statistics": {k:v for k,v in d.statistics.items() if k != "blocks"}} for d in documents.values()])
    print(json.dumps({k: v for k, v in result.items() if k not in {"queries", "excluded_body_terms"}}, indent=2))
    print("EXCLUDED_BODY_TERMS:", json.dumps(excluded_evidence, ensure_ascii=False))


if __name__ == "__main__":
    main()
