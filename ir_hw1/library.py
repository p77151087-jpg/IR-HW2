"""User-triggered XML uploads, PMID retrieval, and recoverable article removal."""
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Callable
from urllib.parse import urlencode
from xml.etree.ElementTree import tostring

import requests
from filelock import FileLock

from .corpus import OAI_URL, PMCClient, import_bytes, reusable_license, utc_now
from .index import build_index, load_snapshot, save_index
from .models import Document
from .storage import (StorageError, append_manifest, atomic_write, load_deleted,
                      load_documents, save_documents, write_json)
from .xml_parser import MAX_XML_BYTES, ParseError, articles_in_xml, parse_article

ID_CONVERTER_URL = "https://pmc.ncbi.nlm.nih.gov/tools/idconv/api/v1/articles/"
PUBMED_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
MAX_PMIDS_PER_BATCH = 100
PMIDS_PER_REQUEST = 20


def ensure_online_download() -> None:
    if os.environ.get("IR_HW1_OFFLINE_DEMO") == "1":
        raise ValueError("目前以離線展示模式啟動，已停用下載。請關閉離線展示程序，再以 scripts/start_demo.ps1 啟動一般模式。")


def download_failure(data_dir: Path, pmid: str, pmcid: str, source_url: str, exc: Exception) -> dict:
    reason = str(exc)
    if isinstance(exc, requests.exceptions.SSLError):
        reason = "NCBI HTTPS 憑證驗證失敗，請檢查系統時間及系統信任憑證。"
    elif isinstance(exc, requests.exceptions.ProxyError):
        reason = "無法透過代理伺服器連線至 NCBI，請檢查代理設定。"
    elif isinstance(exc, requests.Timeout):
        reason = "NCBI 連線逾時，本次下載已停止，請檢查網路或稍後重試。"
    elif isinstance(exc, requests.RequestException):
        reason = "無法連線到 NCBI 服務，請檢查網路或稍後重試。" + f"（{type(exc).__name__}）"
    record = {"status": "download_failed", "pmid": pmid, "pmcid": pmcid,
              "source_url": source_url, "acquired_at": utc_now(), "reason": reason}
    append_manifest(data_dir, record)
    return record


def refresh_index(data_dir: Path) -> None:
    """Called with the writer lock; both original and Porter postings are published."""
    try:
        load_snapshot(data_dir)
    except StorageError:
        save_index(data_dir, build_index(load_documents(data_dir)))


def upload_xml(data_dir: Path, filename: str, raw: bytes) -> list[dict]:
    """Save under a content-derived name, never a browser-supplied filesystem path."""
    name = filename.replace("\\", "/").rsplit("/", 1)[-1]
    if not name.lower().endswith(".xml"):
        raise ValueError("請選擇副檔名為 .xml 的 PMC 或 PubMed 檔案。")
    if not raw or len(raw) > MAX_XML_BYTES:
        raise ValueError("XML 不可為空，且每個檔案不可超過 25 MiB。")
    data_dir.mkdir(parents=True, exist_ok=True)
    with FileLock(str(data_dir / ".writer.lock"), timeout=0):
        load_documents(data_dir)  # Refuse writes while a permanent removal needs recovery.
        has_valid_article = False
        try:
            for element in articles_in_xml(raw):
                try:
                    parse_article(element)
                    has_valid_article = True
                except ParseError:
                    pass
        except ParseError:
            pass
        sha = hashlib.sha256(raw).hexdigest()
        relative = f"{'raw' if has_valid_article else 'rejected'}/upload-{sha}.xml"
        if not (data_dir / relative).exists():
            atomic_write(data_dir / relative, raw)
        records = import_bytes(raw, data_dir, "upload:" + name, relative, restore_deleted=True,
                               content_scope="full")
        refresh_index(data_dir)
        return records


def normalize_pmid(value: str) -> str:
    match = re.fullmatch(r"(?:PMID\s*:?\s*)?([1-9][0-9]{0,9})", value.strip(), re.IGNORECASE)
    if not match:
        raise ValueError("請輸入一個有效 PMID（例如 23193287）或 PMCID（例如 PMC3531190）。")
    return match.group(1)


def resolve_pmid(client: PMCClient, pmid: str) -> tuple[str, str]:
    params = {"ids": pmid, "idtype": "pmid", "format": "json", "tool": "IR-HW1"}
    if email := os.environ.get("NCBI_EMAIL", "").strip():
        params["email"] = email
    raw, url = client.get(params, endpoint=ID_CONVERTER_URL)
    try:
        payload = json.loads(raw)
        records = payload.get("records", [])
        if payload.get("status") != "ok" or not isinstance(records, list):
            raise ValueError()
        record = next((r for r in records if isinstance(r, dict)
                       and str(r.get("requested-id", r.get("pmid", ""))) == pmid), None)
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValueError("PMID 轉換服務回傳格式異常，請稍後重試。") from exc
    if not record or record.get("status") == "error" or not re.fullmatch(r"PMC[1-9][0-9]*", str(record.get("pmcid", ""))):
        raise ValueError(f"PMID {pmid} 找不到對應的 PMC 全文；可能尚未收錄或只有 PubMed 摘要。")
    if str(record.get("pmid", pmid)) != pmid:
        raise ValueError("轉換服務回傳的 PMID 與查詢不一致，已停止下載。")
    if str(record.get("live", "true")).lower() == "false":
        raise ValueError(f"文章全文尚未公開（預計公開日期：{record.get('release-date', '未提供')}）。")
    return record["pmcid"], url


def reuse_article(data_dir: Path, previous: Document, content_scope: str, *,
                  publish_index: bool = True) -> list[dict] | None:
    if previous.content_scope == content_scope:
        if publish_index:
            refresh_index(data_dir)
        return [{"pmcid": previous.pmcid, "pmid": previous.pmid, "status": "duplicate",
                 "content_scope": content_scope, "reason": "文章已在本機，可直接搜尋。"}]
    source = data_dir / previous.raw_path
    if not source.is_file():
        return None
    raw = source.read_bytes()
    parsed = next((parse_article(a, content_scope=content_scope) for a in articles_in_xml(raw)
                   if parse_article(a).pmcid == previous.pmcid), None)
    if parsed is None or parsed.content_scope != content_scope:
        return None  # A PubMed abstract cannot supply PMC full text.
    records = import_bytes(raw, data_dir, previous.source_url, previous.raw_path,
                           previous.acquired_at, expected_pmcid=previous.pmcid,
                           content_scope=content_scope, restore_deleted=True)
    if publish_index:
        refresh_index(data_dir)
    return records


def download_pmid(data_dir: Path, value: str) -> list[dict]:
    """PMID reads PubMed abstracts; PMC-prefixed IDs read PMC full text."""
    ensure_online_download()
    data_dir.mkdir(parents=True, exist_ok=True)
    with FileLock(str(Path.home() / ".ir-hw1-pmc-download.lock"), timeout=0), \
            FileLock(str(data_dir / ".writer.lock"), timeout=0):
        return _download_article(data_dir, value)


def download_pmids(data_dir: Path, values: list[str], *,
                   progress: Callable[[int, int, str], None] | None = None) -> list[dict]:
    """Fetch groups of PMIDs, persist per article, and publish the index once."""
    ensure_online_download()
    pmids = list(dict.fromkeys(normalize_pmid(value) for value in values))
    if not pmids or len(pmids) > MAX_PMIDS_PER_BATCH:
        raise ValueError(f"每次請提供 1–{MAX_PMIDS_PER_BATCH} 個不同的 PMID。")
    data_dir.mkdir(parents=True, exist_ok=True)
    with FileLock(str(Path.home() / ".ir-hw1-pmc-download.lock"), timeout=0), \
            FileLock(str(data_dir / ".writer.lock"), timeout=0):
        documents = load_documents(data_dir)  # Refuse interrupted storage.
        by_pmid = {doc.pmid: doc for doc in documents.values() if doc.pmid}
        results, pending = {}, []
        client = None
        def report(pmid: str) -> None:
            if progress:
                progress(len(results), len(pmids), pmid)
        try:
            for pmid in pmids:
                reused = reuse_article(data_dir, by_pmid[pmid], "abstract", publish_index=False) if pmid in by_pmid else None
                if reused is not None:
                    results[pmid] = reused
                    report(pmid)
                else:
                    pending.append(pmid)
            if pending:
                client = PMCClient()
            for start in range(0, len(pending), PMIDS_PER_REQUEST):
                group = pending[start:start + PMIDS_PER_REQUEST]
                report(", ".join(group))
                params = {"db": "pubmed", "id": ",".join(group), "retmode": "xml", "tool": "IR-HW1"}
                if email := os.environ.get("NCBI_EMAIL", "").strip():
                    params["email"] = email
                source_url = PUBMED_URL + "?" + urlencode(params)
                try:
                    raw, source_url = client.get(params, endpoint=PUBMED_URL)
                    articles = articles_in_xml(raw)
                except (requests.RequestException, ValueError) as exc:
                    # A service/transport failure affects the remaining batch too.
                    # Do not multiply three HTTP retries by every article.
                    for pmid in pending[start:]:
                        results[pmid] = [download_failure(data_dir, pmid, "", source_url, exc)]
                        report(pmid)
                    break
                returned = {}
                for article in articles:
                    try:
                        document = parse_article(article, content_scope="abstract")
                    except ParseError:
                        continue  # Missing/invalid records are reported by requested PMID below.
                    if document.pmid in group:
                        returned.setdefault(document.pmid, []).append(article)
                for pmid in group:
                    matches = returned.get(pmid, [])
                    if len(matches) != 1:
                        exc = ValueError("NCBI 未回傳此 PMID 的唯一有效文章，請確認編號或稍後重試。")
                        results[pmid] = [download_failure(data_dir, pmid, "", source_url, exc)]
                    else:
                        article_raw = tostring(matches[0], encoding="utf-8", xml_declaration=True)
                        results[pmid] = _download_article(data_dir, pmid, client=client,
                            fetched=(article_raw, source_url), publish_index=False)
                    report(pmid)
        finally:
            if client is not None:
                client.session.close()
            if any(r["status"] in {"imported", "updated", "duplicate"} for records in results.values() for r in records):
                refresh_index(data_dir)
        return [r for pmid in pmids for r in results[pmid]]


def _download_article(data_dir: Path, value: str, *, client: PMCClient | None = None,
                      fetched: tuple[bytes, str] | None = None, publish_index: bool = True) -> list[dict]:
    """Caller owns download/writer locks; each completed article persists its index."""
    match = re.fullmatch(r"PMC[1-9][0-9]*", value.strip(), re.IGNORECASE)
    pmcid = match.group().upper() if match else ""
    pmid = "" if pmcid else normalize_pmid(value)
    scope = "full" if pmcid else "abstract"
    documents = load_documents(data_dir)
    previous = documents.get(pmcid) if pmcid else next((d for d in documents.values() if d.pmid == pmid), None)
    if previous:
        reused = reuse_article(data_dir, previous, scope, publish_index=publish_index)
        if reused is not None:
            return reused
    owns_client = client is None
    if client is None:
        client = PMCClient()
    source_url = OAI_URL if pmcid else PUBMED_URL
    try:
        if fetched is not None:
            raw, source_url = fetched
        elif pmcid:
            params = {"verb": "GetRecord", "metadataPrefix": "pmc", "identifier": "oai:pubmedcentral.nih.gov:" + pmcid[3:]}
            source_url = OAI_URL + "?" + urlencode(params)
            raw, source_url = client.get(params)
        else:
            params = {"db": "pubmed", "id": pmid, "retmode": "xml", "tool": "IR-HW1"}
            if email := os.environ.get("NCBI_EMAIL", "").strip():
                params["email"] = email
            raw, source_url = client.get(params, endpoint=PUBMED_URL)
        parsed = [parse_article(article, content_scope=scope) for article in articles_in_xml(raw)]
        if (len(parsed) != 1 or (pmcid and parsed[0].pmcid != pmcid) or (pmid and parsed[0].pmid != pmid)
                or parsed[0].content_scope != scope):
            raise ValueError("下載文章的 PMID／PMCID 與查詢不一致，已停止匯入。")
        if scope == "full" and not reusable_license(parsed[0]):
            raise ValueError("文章未提供本系統可辨識的 Creative Commons 授權，無法自動匯入；可自行確認權利後上傳 XML。")
        if parsed[0].language.lower() not in {"en", "eng", "en-us", "en-gb"}:
            raise ValueError("目前自動下載限定英文文章。")
        identifier = pmcid or "PMID" + pmid
        relative = f"raw/{identifier}-{hashlib.sha256(raw).hexdigest()[:20]}.xml"
        atomic_write(data_dir / relative, raw)
        records = import_bytes(raw, data_dir, source_url, relative, require_reuse=scope == "full",
                               expected_pmcid=parsed[0].pmcid, restore_deleted=True, content_scope=scope)
        if publish_index:
            refresh_index(data_dir)
        return records
    except StorageError:
        raise
    except (requests.RequestException, ValueError) as exc:
        return [download_failure(data_dir, pmid, pmcid, source_url, exc)]
    finally:
        if owns_client:
            client.session.close()


def delete_articles(data_dir: Path, pmcids: list[str]) -> int:
    """Tombstones are written first so restart cannot resurrect partially deleted data."""
    with FileLock(str(data_dir / ".writer.lock"), timeout=0):
        documents = load_documents(data_dir)
        deleted = load_deleted(data_dir)
        selected = set(pmcids) & documents.keys()
        if not selected:
            return 0
        for pmcid in sorted(selected):
            doc = documents.pop(pmcid)
            deleted[pmcid] = {"document": doc.to_dict(), "deleted_at": utc_now()}
        write_json(data_dir / "deleted_articles.json", deleted)
        save_documents(data_dir, documents)
        save_index(data_dir, build_index(documents))
        for pmcid in sorted(selected):
            append_manifest(data_dir, {"pmcid": pmcid, "status": "user_deleted", "acquired_at": utc_now(),
                                       "reason": "使用者移至回收筒，已移除搜尋索引。"})
        return len(selected)


def restore_articles(data_dir: Path, pmcids: list[str]) -> int:
    with FileLock(str(data_dir / ".writer.lock"), timeout=0):
        deleted = load_deleted(data_dir)
        documents = load_documents(data_dir)
        selected = set(pmcids) & deleted.keys()
        if not selected:
            return 0
        # Parse each source only once, including renamed and shared XML files.
        candidates = {}
        for path in sorted((data_dir / "raw").glob("*")):
            if not path.is_file() or path.suffix.lower() != ".xml":
                continue
            with path.open("rb") as stream:
                raw = stream.read(MAX_XML_BYTES + 1)
            try:
                elements = articles_in_xml(raw)
            except ParseError:
                continue
            for element in elements:
                try:
                    fresh = parse_article(element)
                    if fresh.pmcid in selected:
                        scope = deleted[fresh.pmcid]["document"].get("content_scope", "full")
                        if scope != fresh.content_scope:
                            fresh = parse_article(element, content_scope=scope)
                except ParseError:
                    continue
                if fresh.pmcid in selected:
                    fresh.raw_path = path.relative_to(data_dir).as_posix()
                    fresh.sha256 = hashlib.sha256(raw).hexdigest()
                    candidates.setdefault(fresh.pmcid, []).append(fresh)
        missing = selected - candidates.keys()
        if missing:
            raise StorageError("找不到有效原始 XML：" + "、".join(sorted(missing)) + "。請放回 data/raw 或重新上傳；此次尚未還原任何文章。")
        for pmcid in selected:
            doc = Document.from_dict(deleted.pop(pmcid)["document"])
            fresh = next((d for d in candidates[pmcid] if d.raw_path == doc.raw_path), candidates[pmcid][-1])
            fresh.source_url, fresh.acquired_at = doc.source_url, doc.acquired_at
            documents[pmcid] = fresh
        save_documents(data_dir, documents)
        write_json(data_dir / "deleted_articles.json", deleted)
        save_index(data_dir, build_index(documents))
        for pmcid in sorted(selected):
            append_manifest(data_dir, {"pmcid": pmcid, "status": "restored", "acquired_at": utc_now(), "reason": "從回收筒還原。"})
        return len(selected)
