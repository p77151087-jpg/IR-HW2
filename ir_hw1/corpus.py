"""Local imports and serial PMC OAI-PMH retrieval under current official policy."""
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlencode, urlparse

import requests
from filelock import FileLock

from .models import Document
from .storage import append_manifest, atomic_write, load_deleted, load_documents, read_manifest, save_documents, write_json
from .xml_parser import MAX_XML_BYTES, ParseError, articles_in_xml, descendants, first, parse_article, parse_xml_root, readable

OAI_URL = "https://pmc.ncbi.nlm.nih.gov/api/oai/v1/mh/"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def import_bytes(raw: bytes, data_dir: Path, source_url: str, raw_path: str,
                 acquired_at: str | None = None, require_reuse: bool = False,
                 expected_pmcid: str | None = None, restore_deleted: bool = False,
                 content_scope: str | None = None) -> list[dict]:
    """Import independently per article; one bad article never discards successes."""
    timestamp = acquired_at or utc_now()
    base = {"source_url": source_url, "raw_path": raw_path, "acquired_at": timestamp,
            "imported_at": utc_now(), "sha256": hashlib.sha256(raw).hexdigest(),
            "pmcid": expected_pmcid or "", "license": "", "license_url": "", "language": ""}
    results = []
    documents = load_documents(data_dir)
    deleted = load_deleted(data_dir)
    restored = False
    try:
        articles = articles_in_xml(raw)
    except ParseError as exc:
        record = {**base, "status": "failed", "reason": str(exc)}
        append_manifest(data_dir, record)
        return [record]
    for article in articles:
        record = dict(base)
        try:
            document = parse_article(article, content_scope=content_scope or "full")
            previous = documents.get(document.pmcid)
            if content_scope is None:
                saved_scope = (previous.content_scope if previous else
                               deleted.get(document.pmcid, {}).get("document", {}).get("content_scope", "full"))
                if saved_scope != document.content_scope:
                    document = parse_article(article, content_scope=saved_scope)
            record.update({"pmcid": document.pmcid, "pmid": document.pmid, "license": document.license,
                           "license_url": document.license_url, "language": document.language,
                           "content_scope": document.content_scope})
            if expected_pmcid and document.pmcid != expected_pmcid:
                raise ParseError("回傳 PMCID 與請求不一致")
            if require_reuse:
                if document.language.lower() not in {"en", "eng", "en-us", "en-gb"}:
                    raise ParseError("主要 demo 語料限定英文")
                if not reusable_license(document):
                    raise ParseError("主要 demo 語料需有可辨識的 Creative Commons 授權 URL")
            if document.pmcid in deleted and not restore_deleted:
                record.update(status="skipped_deleted", reason="文章已在回收筒，自動匯入略過。")
                results.append(record)
                continue
            for key in ("source_url", "raw_path", "acquired_at", "sha256"):
                setattr(document, key, base[key])
            previous = documents.get(document.pmcid)
            if (previous and previous.sha256 == document.sha256
                    and previous.content_scope == document.content_scope
                    and previous.blocks == document.blocks and previous.back_blocks == document.back_blocks
                    and previous.statistics == document.statistics):
                status = "duplicate"
            else:
                status = "updated" if previous else "imported"
                documents[document.pmcid] = document
            record.update(status=status, reason="" if document.license else "本機匯入：未提供授權，使用者須確認使用權利")
            if document.pmcid in deleted:
                del deleted[document.pmcid]
                restored = True
                record["restored"] = True
        except (ParseError, ValueError) as exc:
            record.update(status="failed", reason=str(exc))
        results.append(record)
    if any(record["status"] in {"imported", "updated"} for record in results):
        save_documents(data_dir, documents)
    if restored:
        write_json(data_dir / "deleted_articles.json", deleted)
    for record in results:
        append_manifest(data_dir, record)
    return results


def reusable_license(document: Document) -> bool:
    url = urlparse(document.license_url)
    return url.hostname in {"creativecommons.org", "www.creativecommons.org"} and bool(
        re.fullmatch(r"/(?:licenses/(?:by|by-sa|by-nc|by-nc-sa|by-nd|by-nc-nd)/[1-4]\.0(?:/[a-z_]+)?|publicdomain/zero/1\.0)/?", url.path))


def import_folder(folder: Path, data_dir: Path) -> list[dict]:
    paths = [folder] if folder.is_file() else sorted(folder.glob("*.xml"))
    if not paths:
        raise ValueError(f"資料夾沒有 XML：{folder}")
    results = []
    data_dir.mkdir(parents=True, exist_ok=True)
    with FileLock(str(data_dir / ".writer.lock"), timeout=0):
        known = {r.get("raw_path"): r for r in read_manifest(data_dir) if r.get("status") in {"imported", "updated", "duplicate"}}
        for path in paths:
            try:
                if path.stat().st_size > MAX_XML_BYTES:
                    raise ValueError("XML 超過 25 MiB 上限")
                raw = path.read_bytes()
                sha = hashlib.sha256(raw).hexdigest()
                try:
                    relative = path.resolve().relative_to(data_dir.resolve()).as_posix()
                except ValueError:
                    relative = f"raw/local-{sha[:20]}.xml"
                    atomic_write(data_dir / relative, raw)
                origin = known.get(relative, {})
                if origin.get("sha256") != sha:
                    origin = {}
                results.extend(import_bytes(raw, data_dir, origin.get("source_url", path.resolve().as_uri()),
                                            relative, origin.get("acquired_at")))
            except (OSError, ValueError) as exc:
                record = {"pmcid": "", "source_url": path.resolve().as_uri(), "acquired_at": utc_now(),
                          "status": "failed", "reason": str(exc), "raw_path": str(path)}
                append_manifest(data_dir, record)
                results.append(record)
    return results


class PMCClient:
    """One request at a time, at most 1/s, <=100 actual attempts per invocation.

    The deliberately small batch cap avoids PMC's >100-request peak-hour rule.
    A per-user lock in download_corpus also prevents concurrent app downloaders.
    """
    def __init__(self, session=None, sleeper=time.sleep, clock=time.monotonic, max_requests: int = 100):
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": "IR-HW1/1.0 (educational PMC full-text retrieval)",
                                     "Accept-Encoding": "gzip, deflate"})
        self.sleeper, self.clock = sleeper, clock
        self.last_request = float("-inf")
        self.request_count = 0
        self.max_requests = min(max_requests, 100)

    def get(self, params: dict, *, endpoint: str = OAI_URL) -> tuple[bytes, str]:
        url = endpoint + "?" + urlencode(params)
        for attempt in range(3):
            if self.request_count >= self.max_requests:
                raise ValueError("已達每次執行 100 次請求上限，已保存進度；大量批次請依官方離峰規範安排。")
            self.sleeper(max(0, 1.0 - (self.clock() - self.last_request)))
            self.last_request = self.clock()
            self.request_count += 1
            try:
                with self.session.get(endpoint, params=params, timeout=(15, 45), stream=True) as response:
                    if response.status_code == 429 or 500 <= response.status_code <= 599:
                        if attempt == 2:
                            response.raise_for_status()
                        retry_after = response.headers.get("Retry-After", "")
                        try:
                            delay = float(retry_after)
                        except ValueError:
                            try:
                                delay = (parsedate_to_datetime(retry_after) - datetime.now(timezone.utc)).total_seconds()
                            except (TypeError, ValueError):
                                delay = 0
                        if delay > 60:
                            raise ValueError(f"伺服器要求等待 {delay:.0f} 秒；停止並保存進度，請稍後重試。")
                        self.sleeper(max(2 ** (attempt + 1), delay))
                        continue
                    response.raise_for_status()
                    chunks, size = [], 0
                    for chunk in response.iter_content(64 * 1024):
                        size += len(chunk)
                        if size > MAX_XML_BYTES:
                            raise ValueError("PMC 回應超過 25 MiB 上限")
                        chunks.append(chunk)
                    return b"".join(chunks), url
            except (requests.Timeout, requests.ConnectionError):
                if attempt == 2:
                    raise
                self.sleeper(2 ** (attempt + 1))
        raise RuntimeError("重試用盡")


def download_corpus(data_dir: Path, count: int = 15, pmcids: list[str] | None = None,
                    from_date: str = "2025-01-01", until_date: str = "2025-01-02",
                    refresh: bool = False, set_spec: str = "pmc-open") -> list[dict]:
    if not 1 <= count <= 50:
        raise ValueError("每批篇數須為 1–50；較大批次需另依 PMC 離峰規範安排。")
    for value in (from_date, until_date):
        datetime.strptime(value, "%Y-%m-%d")
    if from_date > until_date:
        raise ValueError("from 日期不可晚於 until 日期")
    pmcids = [p.upper() if p.upper().startswith("PMC") else "PMC" + p for p in pmcids or []]
    if any(not re.fullmatch(r"PMC[1-9]\d*", p) for p in pmcids):
        raise ValueError("PMCID 格式錯誤")
    data_dir.mkdir(parents=True, exist_ok=True)
    client = PMCClient()
    results = []
    # Same OS user cannot run another downloader even with a different data dir.
    with FileLock(str(Path.home() / ".ir-hw1-pmc-download.lock"), timeout=0), FileLock(str(data_dir / ".writer.lock"), timeout=0):
        state_path = data_dir / "download_state.json"
        signature = {"from": from_date, "until": until_date, "set": set_spec}
        state = {"signature": signature, "pending": [], "token": "", "started": False}
        if not pmcids and state_path.exists():
            existing = json.loads(state_path.read_text(encoding="utf-8"))
            if existing.get("signature") == signature:
                state = existing
        if pmcids:
            state["pending"] = list(dict.fromkeys(pmcids))
        processed = 0
        while processed < count:
            if not state["pending"]:
                if pmcids or (state["started"] and not state["token"]):
                    break
                params = {"verb": "ListIdentifiers", "resumptionToken": state["token"]} if state["token"] else {
                    "verb": "ListIdentifiers", "metadataPrefix": "pmc", "set": set_spec, "from": from_date, "until": until_date}
                try:
                    raw, url = client.get(params)
                    root = parse_xml_root(raw)
                    errors = descendants(root, "error")
                    if errors:
                        raise ValueError("; ".join(f"{e.get('code')}: {readable(e)}" for e in errors))
                    state["pending"] = []
                    for header in descendants(root, "header"):
                        if header.get("status") == "deleted":
                            append_manifest(data_dir, {"status": "deleted", "reason": "OAI 已刪除紀錄", "source_url": url,
                                                       "pmcid": readable(first(header, "identifier")), "acquired_at": utc_now()})
                            continue
                        identifier = readable(first(header, "identifier"))
                        number = identifier.rsplit(":", 1)[-1]
                        if number.isdigit():
                            state["pending"].append("PMC" + number)
                    state.update(token=readable(first(root, "resumptionToken")), started=True)
                    write_json(state_path, state)
                except (requests.RequestException, ValueError) as exc:
                    record = {"status": "download_failed", "pmcid": "", "source_url": OAI_URL,
                              "reason": str(exc), "acquired_at": utc_now()}
                    append_manifest(data_dir, record)
                    results.append(record)
                    break
                if not state["pending"]:
                    break
            pmcid = state["pending"][0]
            existing_docs = load_documents(data_dir)
            if not refresh and pmcid in existing_docs:
                state["pending"].pop(0)
                if not pmcids:
                    write_json(state_path, state)
                if pmcids:
                    processed += 1
                continue
            params = {"verb": "GetRecord", "metadataPrefix": "pmc", "identifier": "oai:pubmedcentral.nih.gov:" + pmcid[3:]}
            try:
                raw, url = client.get(params)
                relative = f"raw/{pmcid}.xml"
                # Validate identity before replacing an already successful raw file.
                parsed = [parse_article(article) for article in articles_in_xml(raw)]
                for document in parsed:
                    if document.pmcid != pmcid:
                        raise ParseError("回傳 PMCID 與請求不一致")
                if any(not reusable_license(d) or d.language.lower() not in {"en", "eng", "en-us", "en-gb"} for d in parsed):
                    relative = f"rejected/{pmcid}.xml"
                raw_sha = hashlib.sha256(raw).hexdigest()
                previous = existing_docs.get(pmcid)
                if previous and previous.sha256 != raw_sha:
                    relative = f"raw/{pmcid}-{raw_sha[:12]}.xml"
                atomic_write(data_dir / relative, raw)
                records = import_bytes(raw, data_dir, url, relative, require_reuse=True, expected_pmcid=pmcid)
                results.extend(records)
                if any(r["status"] in {"imported", "updated", "duplicate"} for r in records):
                    processed += 1
                print(f"{pmcid}: {records[0]['status']} {records[0]['reason']}", flush=True)
            except (requests.RequestException, ValueError, OSError) as exc:
                record = {"status": "download_failed", "pmcid": pmcid, "reason": str(exc),
                          "source_url": OAI_URL + "?" + urlencode(params), "acquired_at": utc_now()}
                append_manifest(data_dir, record)
                results.append(record)
                print(f"{pmcid}: download_failed {exc}", flush=True)
                # Keep transient failures pending for the next invocation.
                if not isinstance(exc, ParseError):
                    break
            state["pending"].pop(0)
            if not pmcids:
                write_json(state_path, state)
    client.session.close()
    return results
