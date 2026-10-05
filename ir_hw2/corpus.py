"""Immutable, resumable PubMed abstract snapshots for HW2 experiments.

This intentionally does not touch the mutable HW1 search library. A PMID is a
document ID; only Abstract/AbstractText body text enters analysis.
"""
from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
import math
import os
from pathlib import Path
import time
from typing import Callable
from urllib.parse import urlencode

import requests

from ir_hw1.models import Document
from ir_hw1.xml_parser import parse_xml_root, parse_pubmed_article, ParseError

DEFAULT_QUERY = (
    '("GLP-1"[Title/Abstract] OR "glucagon-like peptide-1"[Title/Abstract]) '
    'AND english[Language] AND hasabstract '
    'AND ("1900/01/01"[Date - Publication] : "2026/09/29"[Date - Publication])'
)
DEFAULT_SNAPSHOT = Path(__file__).resolve().parents[1] / "data/hw2/glp1-1000-20260929"
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
BATCH_SIZE = 100
MAX_RESPONSE_BYTES = 25 * 1024 * 1024
SCHEMA_VERSION = 1


class CorpusError(RuntimeError):
    """An acquisition, integrity or immutable-snapshot error."""


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _json(path: Path, value: dict | list) -> None:
    _atomic(path, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


@contextmanager
def _download_lock(path: Path):
    """OS releases this local lock even after a process crash; no home files."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise CorpusError("另一個 HW2 下載工作正在執行；請稍後重試。") from error
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_UN)


class NCBIClient:
    """Serial 1 request/s; 3 total attempts for 429, 5xx and connection errors."""

    def __init__(self, session=None, sleeper=time.sleep, clock=time.monotonic):
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": "IR-HW2/1.0 (educational PubMed abstract analysis)"})
        self.sleeper, self.clock = sleeper, clock
        self.last_request = float("-inf")
        self.request_count = 0

    def get(self, endpoint: str, params: dict) -> bytes:
        for attempt in range(3):
            self.sleeper(max(0.0, 1.0 - (self.clock() - self.last_request)))
            self.last_request = self.clock()
            self.request_count += 1
            try:
                with self.session.get(endpoint, params=params, timeout=(15, 60), stream=True) as response:
                    if response.status_code == 429 or 500 <= response.status_code <= 599:
                        if attempt == 2:
                            response.raise_for_status()
                        delay = response.headers.get("Retry-After", "0")
                        try:
                            delay = float(delay)
                        except (ValueError, TypeError):
                            try:
                                delay = (parsedate_to_datetime(delay) - datetime.now(timezone.utc)).total_seconds()
                            except (ValueError, TypeError, OverflowError):
                                delay = 0
                        if delay > 60:
                            raise CorpusError(f"NCBI 要求等待 {delay:.0f} 秒；進度已快取，請稍後續傳。")
                        self.sleeper(max(2 ** (attempt + 1), delay))
                        continue
                    response.raise_for_status()
                    parts, size = [], 0
                    for chunk in response.iter_content(64 * 1024):
                        size += len(chunk)
                        if size > MAX_RESPONSE_BYTES:
                            raise CorpusError("NCBI 回應超過 25 MiB 上限。")
                        parts.append(chunk)
                    return b"".join(parts)
            except (requests.Timeout, requests.ConnectionError):
                if attempt == 2:
                    raise
                self.sleeper(2 ** (attempt + 1))
        raise CorpusError("NCBI 重試次數已用盡。")

    def close(self) -> None:
        self.session.close()


def _cached_response(root: Path, name: str, endpoint: str, params: dict, client: NCBIClient) -> tuple[bytes, dict]:
    path = root / "raw-batches" / name
    meta_path = path.with_suffix(path.suffix + ".json")
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta["endpoint"] != endpoint or meta["params"] != params:
            raise CorpusError(f"快取請求參數不一致：{path.name}；請另建快照目錄。")
        if not path.exists() or _sha(path.read_bytes()) != meta["sha256"]:
            raise CorpusError(f"快取雜湊驗證失敗：{path.name}；不會默默覆寫損壞快取。")
        return path.read_bytes(), meta
    raw = client.get(endpoint, params)
    meta = {"file": path.relative_to(root).as_posix(), "endpoint": endpoint, "params": params,
            "url": endpoint + "?" + urlencode(params), "retrieved_at_utc": _utc(),
            "sha256": _sha(raw), "bytes": len(raw)}
    # Saving bytes before metadata is crash-safe: an uncommitted response is refetched.
    _atomic(path, raw)
    _json(meta_path, meta)
    return raw, meta


def _manifest(root: Path) -> dict:
    path = root / "snapshot.json"
    if not path.exists():
        raise CorpusError(f"尚無完成的語料快照：{path}")
    result = json.loads(path.read_text(encoding="utf-8"))
    if result.get("status") != "complete" or result.get("schema_version") != SCHEMA_VERSION:
        raise CorpusError("語料快照尚未完成或版本不相容。")
    return result


def load_corpus(snapshot_dir: str | Path = DEFAULT_SNAPSHOT) -> dict[str, Document]:
    """Verify the sealed snapshot and raw bytes, then load documents keyed by PMID."""
    root = Path(snapshot_dir)
    manifest = _manifest(root)
    path = root / "abstracts.jsonl"
    if not path.exists() or _sha(path.read_bytes()) != manifest["sha256"]:
        raise CorpusError("abstracts.jsonl 雜湊驗證失敗。")
    selection = root / "selection.json"
    if not selection.exists() or _sha(selection.read_bytes()) != manifest["selection_sha256"]:
        raise CorpusError("selection.json 雜湊驗證失敗。")
    for raw in manifest["raw_files"]:
        file = root / raw["file"]
        if not file.exists() or _sha(file.read_bytes()) != raw["sha256"]:
            raise CorpusError(f"原始 API 快取雜湊驗證失敗：{raw['file']}")
    documents = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        doc = Document.from_dict(json.loads(line))
        if not doc.pmid or doc.pmid in documents:
            raise CorpusError("快照含空白或重複 PMID。")
        if doc.language != "eng" or not any(b.kind == "abstract" and b.text.strip() for b in doc.blocks):
            raise CorpusError(f"PMID {doc.pmid} 不是已驗證的英文非空摘要。")
        documents[doc.pmid] = doc
    if list(documents) != manifest["selected_pmids"] or len(documents) != manifest["counts"]["selected"]:
        raise CorpusError("PMID 順序或語料數量與快照清單不一致。")
    return documents


def _article_pmid(article) -> str:
    node = article.find("./MedlineCitation/PMID") if article.tag == "PubmedArticle" else article.find("./BookDocument/PMID")
    return "" if node is None else (node.text or "").strip()


def fetch_corpus(snapshot_dir: str | Path = DEFAULT_SNAPSHOT, count: int = 1000,
                 query: str = DEFAULT_QUERY, progress: Callable[[str], None] | None = None) -> dict:
    """Create a fixed corpus, or resume cached acquisition; never replace a seal.

    A matching completed snapshot is validated and returned without network I/O.
    Use a new directory to intentionally collect a different corpus. PubMed ESearch
    exposes at most 10,000 IDs, a deliberate upper bound for this classroom tool.
    """
    if not isinstance(count, int) or isinstance(count, bool) or not 1 <= count <= 10000:
        raise ValueError("count 必須介於 1 與 10,000。")
    if not query.strip():
        raise ValueError("查詢式不可為空。")
    root = Path(snapshot_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    emit = progress or (lambda message: None)
    with _download_lock(root.parent / ".hw2-ncbi-download.lock"):
        if (root / "snapshot.json").exists():
            manifest = _manifest(root)
            if manifest["query"] != query or manifest["requested_count"] != count:
                raise CorpusError("完成的快照不可變更查詢或篇數；請指定新快照目錄。")
            load_corpus(root)
            emit(f"已驗證固定快照：{count} 篇，未重新下載。")
            return manifest
        if os.environ.get("IR_HW1_OFFLINE_DEMO", "").strip().lower() in {"1", "true", "yes", "on"}:
            raise CorpusError("離線模式不可建立或續傳語料；可以讀取已完成的固定快照。")
        configuration = {"schema_version": SCHEMA_VERSION, "query": query, "requested_count": count,
                         "sort": "pub date", "batch_size": BATCH_SIZE,
                         "candidate_page_size": min(10000, max(1200, math.ceil(count * 1.2))),
                         "tool": "ir_hw2", "email": os.environ.get("NCBI_EMAIL", "").strip()}
        state_path = root / "acquisition.json"
        if state_path.exists():
            state = json.loads(state_path.read_text(encoding="utf-8"))
            # Contact metadata is fixed at acquisition start for byte-cache consistency.
            configuration["email"] = state["configuration"]["email"]
            if state["configuration"] != configuration:
                raise CorpusError("未完成快照的參數不一致；請使用原參數續傳或指定新目錄。")
        else:
            state = {"configuration": configuration, "started_at_utc": _utc(), "status": "in_progress"}
            _json(state_path, state)
        client = NCBIClient()
        common = {"db": "pubmed", "tool": configuration["tool"]}
        if configuration["email"]:
            common["email"] = configuration["email"]
        documents, candidates, outcomes, raw_files = {}, [], {}, []
        candidate_duplicates = 0
        fetched = set()
        retstart = 0
        matched = None
        query_translation = ""
        try:
            while len(documents) < count:
                params = {**common, "term": query, "retmode": "json", "sort": "pub date",
                          "retstart": retstart, "retmax": configuration["candidate_page_size"]}
                raw, meta = _cached_response(root, f"esearch-{retstart:05d}.json", EUTILS + "esearch.fcgi", params, client)
                raw_files.append(meta)
                search = json.loads(raw)["esearchresult"]
                if search.get("errorlist") or search.get("ERROR"):
                    raise CorpusError(f"PubMed 不接受查詢：{search}")
                page = search.get("idlist", [])
                if matched is None:
                    matched = int(search["count"])
                    query_translation = search.get("querytranslation", "")
                old = set(candidates)
                new_page = []
                for pmid in page:
                    if pmid in old:
                        candidate_duplicates += 1
                    else:
                        old.add(pmid)
                        candidates.append(pmid)
                        new_page.append(pmid)
                emit(f"查詢符合 {matched:,} 篇；本次候選累計 {len(candidates):,} 篇。")
                for offset in range(0, len(new_page), BATCH_SIZE):
                    batch = new_page[offset:offset + BATCH_SIZE]
                    batch_number = len(fetched) // BATCH_SIZE
                    params = {**common, "id": ",".join(batch), "rettype": "abstract", "retmode": "xml"}
                    name = f"efetch-{batch_number:04d}-{_sha(','.join(batch).encode())[:12]}.xml"
                    raw, meta = _cached_response(root, name, EUTILS + "efetch.fcgi", params, client)
                    raw_files.append(meta)
                    by_pmid = {}
                    duplicate_records = Counter()
                    xml_root = parse_xml_root(raw)
                    if xml_root.tag != "PubmedArticleSet":
                        raise CorpusError("EFetch 未回傳 PubmedArticleSet；原始回應已保存供檢查。")
                    for article in xml_root:
                        if article.tag not in {"PubmedArticle", "PubmedBookArticle"}:
                            raise CorpusError(f"EFetch 回傳不支援的元素 {article.tag!r}；原始回應已保存。")
                        pmid = _article_pmid(article)
                        if pmid not in batch:
                            raise CorpusError(f"EFetch 回傳非請求 PMID {pmid!r}；請檢查原始 XML。")
                        if pmid in by_pmid:
                            duplicate_records[pmid] += 1
                        else:
                            by_pmid[pmid] = article
                    for pmid in batch:
                        fetched.add(pmid)
                        record = {"pmid": pmid, "raw_file": meta["file"], "duplicate_records": duplicate_records[pmid]}
                        article = by_pmid.get(pmid)
                        if article is None:
                            record.update(status="excluded", reason="missing_from_efetch")
                        elif duplicate_records[pmid]:
                            record.update(status="excluded", reason="ambiguous_duplicate_record")
                        elif article.tag == "PubmedBookArticle":
                            record.update(status="excluded", reason="unsupported_book_record")
                        else:
                            languages = [(node.text or "").strip().lower() for node in article.findall("./MedlineCitation/Article/Language")]
                            record["languages"] = languages
                            if "eng" not in languages:
                                record.update(status="excluded", reason="language_not_confirmed_english")
                            else:
                                try:
                                    doc = parse_pubmed_article(article)
                                except ParseError as error:
                                    record.update(status="excluded", reason="parse_error", detail=str(error))
                                else:
                                    if not any(b.kind == "abstract" and b.text.strip() for b in doc.blocks):
                                        record.update(status="excluded", reason="empty_abstract")
                                    elif len(documents) >= count:
                                        record.update(status="not_needed", reason="eligible_after_target_reached")
                                    else:
                                        doc.language = "eng"
                                        doc.source_url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
                                        doc.acquired_at = meta["retrieved_at_utc"]
                                        doc.raw_path = meta["file"]
                                        doc.sha256 = meta["sha256"]
                                        documents[pmid] = doc
                                        record.update(status="selected", reason="english_nonempty_abstract")
                        outcomes[pmid] = record
                    state.update(status="in_progress", selected_so_far=len(documents), fetched_so_far=len(fetched), updated_at_utc=_utc())
                    _json(state_path, state)
                    emit(f"已下載 {len(fetched):,} 篇；已納入 {len(documents):,}/{count:,} 篇英文非空摘要。")
                    if len(documents) >= count:
                        break
                retstart += len(page)
                if len(documents) < count and (not page or retstart >= min(matched, 10000)):
                    raise CorpusError(f"候選已用盡：只能納入 {len(documents)} 篇，低於目標 {count}；快取已保存。")
            for pmid in candidates:
                outcomes.setdefault(pmid, {"pmid": pmid, "status": "not_needed", "reason": "not_fetched_after_target_reached"})
            encoded = ("\n".join(json.dumps(doc.to_dict(), ensure_ascii=False, separators=(",", ":")) for doc in documents.values()) + "\n").encode("utf-8")
            _atomic(root / "abstracts.jsonl", encoded)
            _json(root / "selection.json", [outcomes[pmid] for pmid in candidates])
            statuses = Counter(row["status"] for row in outcomes.values())
            counts = {"matched": matched, "candidates": len(candidates), "fetched": len(fetched),
                      "selected": len(documents), "excluded": statuses["excluded"], "not_needed": statuses["not_needed"],
                      "not_fetched": len(candidates) - len(fetched),
                      "eligible_not_selected": sum(row.get("reason") == "eligible_after_target_reached" for row in outcomes.values()),
                      "duplicate_candidate_ids": candidate_duplicates,
                      "duplicate_returned_records": sum(row.get("duplicate_records", 0) for row in outcomes.values())}
            manifest = {"schema_version": SCHEMA_VERSION, "status": "complete", "query": query,
                        "query_translation": query_translation, "requested_count": count, "configuration": configuration,
                        "started_at_utc": state["started_at_utc"], "completed_at_utc": _utc(),
                        "counts": counts, "selected_pmids": list(documents), "sha256": _sha(encoded),
                        "selection_sha256": _sha((root / "selection.json").read_bytes()), "raw_files": raw_files,
                        "exclusion_reasons": dict(Counter(row["reason"] for row in outcomes.values() if row["status"] == "excluded")),
                        "content": "Only PubMed Article/Abstract/AbstractText body; labels, titles and full text are excluded from analysis.",
                        "sampling": "First eligible records in PubMed pub date order; not a random or representative PubMed sample. Order and IDs are frozen.",
                        "rate_policy": {"requests_per_second": 1, "batch_size": BATCH_SIZE, "max_attempts": 3, "api_key_used": False,
                                        "timeout_connect_seconds": 15, "timeout_read_seconds": 60, "official_no_key_limit": 3},
                        "sources": ["https://www.ncbi.nlm.nih.gov/books/NBK25497/", "https://www.ncbi.nlm.nih.gov/books/NBK25499/"],
                        "copyright_notice": "PubMed abstracts may be protected by copyright. Retained locally for course analysis; no blanket open-license claim."}
            _json(root / "snapshot.json", manifest)  # Commit marker is written last.
            state.update(status="complete", completed_at_utc=manifest["completed_at_utc"])
            state.pop("last_error", None)
            _json(state_path, state)
            load_corpus(root)
            return manifest
        except Exception as error:
            state.update(status="incomplete", last_error={"type": type(error).__name__, "message": str(error), "at_utc": _utc()})
            _json(state_path, state)
            raise
        finally:
            close = getattr(client, "close", None)
            if close:
                close()
