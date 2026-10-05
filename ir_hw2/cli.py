"""Explicit, reproducible HW2 commands; no download/training at import time."""
import argparse
import json
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SNAPSHOT = ROOT / "data/hw2/glp1-1000-20260929"
DEFAULT_OUTPUT = ROOT / "reports/hw2/experiment"
DEFAULT_MODEL = ROOT / "reports/hw2/model"


def snapshot_hash(path: Path) -> str:
    value = json.loads((path / "snapshot.json").read_text(encoding="utf-8"))
    return value["sha256"]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="HW2：固定 PubMed 摘要、Zipf、Word2Vec 與拼字建議")
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    sub = parser.add_subparsers(dest="command", required=True)
    fetch = sub.add_parser("fetch", help="明確下載／續傳；完成快照只驗證、不重抓")
    fetch.add_argument("--count", type=int, default=1000)
    fetch.add_argument("--query")
    analyze = sub.add_parser("analyze", help="依作業比較 A 基本切詞、B 標點、C 停用詞、D Porter，產生統計與 Zipf 圖表")
    analyze.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    train = sub.add_parser("train", help="明確訓練並保存 Skip-gram 模型")
    train.add_argument("--output", type=Path, default=DEFAULT_MODEL)
    train.add_argument("--vector-size", type=int, default=100)
    train.add_argument("--window", type=int, default=5)
    train.add_argument("--min-count", type=int, default=2)
    train.add_argument("--epochs", type=int, default=30)
    train.add_argument("--seed", type=int, default=42)
    near = sub.add_parser("neighbors", help="重載模型並查詢近鄰／OOV")
    near.add_argument("query")
    near.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    near.add_argument("--topn", type=int, default=10)
    spell = sub.add_parser("spell", help="顯示原查詢與建議，不更動搜尋")
    spell.add_argument("query")
    publish = sub.add_parser("publish-search", help="把快照的搜尋副本加入既有文章庫，快照保持固定")
    publish.add_argument("--data-dir", type=Path, default=ROOT / "data")
    sub.add_parser("verify", help="驗證快照 hash、PMID、英文及非空摘要")
    args = parser.parse_args(argv)
    try:
        from .corpus import DEFAULT_QUERY, fetch_corpus, load_corpus
        if args.command == "fetch":
            import truststore
            truststore.inject_into_ssl()
            result = fetch_corpus(args.snapshot, args.count, args.query or DEFAULT_QUERY, progress=print)
        else:
            documents = load_corpus(args.snapshot)
            digest = snapshot_hash(args.snapshot)
            if args.command == "analyze":
                from .analysis import run_experiment
                summary = run_experiment(documents, args.output, digest)
                result = {"output": str(args.output), "conditions": {
                    name: {key: data[key] for key in ("documents", "tokens", "unique_terms", "average_tokens_per_document", "regression")}
                    for name, data in summary["conditions"].items()}}
            elif args.command == "train":
                from .embeddings import TrainingConfig, train_word2vec
                config = TrainingConfig(vector_size=args.vector_size, window=args.window,
                                        min_count=args.min_count, epochs=args.epochs, seed=args.seed)
                result = train_word2vec(documents, args.output, digest, config)
            elif args.command == "neighbors":
                from .embeddings import load_word2vec, neighbors
                model, _ = load_word2vec(args.model, digest)
                result = neighbors(model, args.query, args.topn)
            elif args.command == "spell":
                from .spelling import build_vocabulary, suggest_query
                result = suggest_query(args.query, build_vocabulary(documents))
            elif args.command == "publish-search":
                from .integration import publish_search_copy
                result = publish_search_copy(args.snapshot, args.data_dir)
            else:
                result = {"verified": True, "documents": len(documents), "sha256": digest,
                          "snapshot": str(args.snapshot)}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, KeyError, RuntimeError, requests.RequestException) as exc:
        print(f"HW2 操作失敗：{exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
