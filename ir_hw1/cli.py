import argparse
import json
from collections import Counter
from pathlib import Path
from time import perf_counter

from filelock import FileLock, Timeout

from .corpus import download_corpus, import_folder
from .index import build_index, load_snapshot, save_index
from .search import search
from .storage import DEFAULT_DATA, load_documents
from .sync import sync_raw_folder


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="IR-HW1 生醫文章搜尋工具")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA)
    commands = parser.add_subparsers(dest="command", required=True)
    download = commands.add_parser("download", help="透過 PMC 官方 OAI-PMH 下載")
    download.add_argument("--count", type=int, default=15)
    download.add_argument("--pmcids", nargs="*")
    download.add_argument("--from-date", default="2025-01-01")
    download.add_argument("--until-date", default="2025-01-02")
    download.add_argument("--refresh", action="store_true")
    download.add_argument("--set", dest="set_spec", default="pmc-open", help="OAI 集合，如 pmc-open 或已確認的期刊 setSpec")
    importer = commands.add_parser("import", help="匯入本機 XML 資料夾或單一檔案")
    importer.add_argument("path", type=Path)
    commands.add_parser("build", help="從已匯入文章建立本機倒排索引")
    query = commands.add_parser("search")
    query.add_argument("query")
    query.add_argument("--mode", choices=["RELEVANCE", "AND", "OR", "PHRASE"], default="RELEVANCE",
                       help="預設相關性搜尋；相容模式：AND 全部詞、OR 任一詞、PHRASE 連續完整片語")
    query.add_argument("--stemming", action="store_true", help="使用 Porter 詞幹比對（預設原詞比對）")
    commands.add_parser("stats")
    args = parser.parse_args(argv)
    try:
        if args.command == "download":
            # CLI only: use the OS certificate store, retaining TLS validation.
            import truststore
            truststore.inject_into_ssl()
            records = download_corpus(args.data_dir, args.count, args.pmcids, args.from_date, args.until_date, args.refresh, args.set_spec)
            print(json.dumps(Counter(r["status"] for r in records), ensure_ascii=False))
            return int(any(r["status"] in {"failed", "download_failed"} for r in records))
        if args.command == "import":
            records = import_folder(args.path, args.data_dir)
            print(json.dumps(Counter(r["status"] for r in records), ensure_ascii=False))
            return int(any(r["status"] == "failed" for r in records))
        if args.command == "build":
            sync_raw_folder(args.data_dir)
            args.data_dir.mkdir(parents=True, exist_ok=True)
            with FileLock(str(args.data_dir / ".writer.lock"), timeout=0):
                documents = load_documents(args.data_dir)
                if not documents:
                    raise ValueError("沒有文章，請先下載或匯入。")
                start = perf_counter()
                index = build_index(documents)
                save_index(args.data_dir, index)
            print(json.dumps({"documents": len(documents), "terms": len(index["postings"]),
                              "porter_terms": len(index["porter_postings"]),
                              "build_seconds": perf_counter() - start}, ensure_ascii=False))
        else:
            sync_raw_folder(args.data_dir)
            documents = load_documents(args.data_dir)
            documents, index = load_snapshot(args.data_dir) if documents else ({}, build_index({}))
            if args.command == "search":
                response = search(index, args.query, args.mode, stemming=args.stemming,
                                  documents=documents, ranking="tfidf")
                print(json.dumps(vars(response), ensure_ascii=False, indent=2))
                for doc_id in response.document_ids:
                    print(f"{doc_id}: {documents[doc_id].title}")
            else:
                print(json.dumps({"documents": len(documents), "terms": len(index["postings"]),
                                  "words": sum(d.statistics["words"] for d in documents.values()),
                                  "sentences": sum(d.statistics["sentences"] for d in documents.values())}, indent=2))
        return 0
    except (ValueError, OSError, Timeout) as exc:
        print(f"操作失敗：{exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
