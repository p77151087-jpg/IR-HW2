"""Run the formal local artifacts in a fresh, network-blocked process."""
import hashlib
import json
from pathlib import Path
import socket
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def blocked(*args, **kwargs):
    raise AssertionError("Formal verification must not access the network")


def main():
    socket.socket.connect = blocked
    socket.socket.connect_ex = blocked
    from ir_hw1.index import load_snapshot
    from ir_hw1.relevance import relevance_tokens
    from ir_hw1.search import search
    from ir_hw1.snippets import hit_locations
    from ir_hw1.sync import sync_raw_folder
    from ir_hw2.cli import DEFAULT_MODEL, DEFAULT_SNAPSHOT, snapshot_hash
    from ir_hw2.corpus import load_corpus
    from ir_hw2.embeddings import load_word2vec, neighbors
    from ir_hw2.spelling import build_vocabulary, suggest_query
    docs = load_corpus(DEFAULT_SNAPSHOT)
    digest = snapshot_hash(DEFAULT_SNAPSHOT)
    model, metadata = load_word2vec(DEFAULT_MODEL, digest)
    examples = [neighbors(model, term, 10) for term in (
        "semaglutide", "insulin", "obesity", "glp-1", "liraglutide", "GLP-1", "zzzznotincorpus", "GLP-1 receptor")]
    (DEFAULT_MODEL / "neighbors.json").write_text(json.dumps(examples, ensure_ascii=False, indent=2), encoding="utf-8")
    assert examples[-2]["status"] == "oov"
    assert examples[-1]["status"] == "invalid_query"
    assert examples[3]["status"] == examples[5]["status"] == "ok"
    assert examples[3]["neighbors"] == examples[5]["neighbors"]
    sync_raw_folder(ROOT / "data")
    library, index = load_snapshot(ROOT / "data")
    searchable = {
        key: {token.term for block in document.blocks for token in relevance_tokens(block.text, stemming=True, include_components=True)}
        for key, document in library.items()}
    queries = []
    for query in ("semaglutide", "insulin", "obesity treatment", "GLP-1", "zzzznotincorpus"):
        start = perf_counter()
        result = search(index, query, "RELEVANCE", stemming=True, documents=library)
        seconds = perf_counter() - start
        expected = {key for key, terms in searchable.items() if terms.intersection(result.terms)}
        assert set(result.document_ids) == expected, query
        assert all(0 < score <= 1 for score in result.scores.values())
        sample_hits = []
        if result.document_ids:
            doc_id = result.document_ids[0]
            document = library[doc_id]
            locations = hit_locations(index, doc_id, result.terms, stemming=True, relevance=True)
            for block in document.blocks:
                for left, right in locations.get(block.id, []):
                    assert 0 <= left < right <= len(block.text)
                    sample_hits.append(block.text[left:right])
        queries.append({"query": query, "hits": len(expected), "seconds": seconds,
                        "top5": result.document_ids[:5], "sample_highlight_text": sample_hits[:8]})
    vocabulary = build_vocabulary(docs, abstracts_only=True)
    spelling = [suggest_query(query, vocabulary) for query in (
        "semaglutide", "semaglutid", "insulinn", "zzzznotincorpus", "GLP-1 BRCA1 IL6 HbA1c", "Semaglutide treatment")]
    assert not spelling[0]["changes"]
    assert spelling[1]["suggested_query"] == "semaglutide"
    assert spelling[2]["suggested_query"] == "insulin"
    assert not spelling[3]["changes"] and not spelling[4]["changes"]
    result = {"network_blocked": True, "corpus_documents": len(docs), "corpus_sha256": digest,
              "library_documents": len(library), "word2vec_vectors_sha256": metadata["vectors_sha256"],
              "word2vec_reload": "passed", "queries": queries, "spelling": spelling,
              "limitations": "Search scan oracle shares preprocessing; no relevance judgments or semantic accuracy evaluation."}
    path = ROOT / "reports/hw2/formal-verification.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"verified": True, "documents": len(docs), "queries": len(queries), "output": str(path)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
