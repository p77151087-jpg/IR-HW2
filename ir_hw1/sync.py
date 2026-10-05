"""Synchronize local raw XML on app startup/rerun; never fetch from the network."""
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from filelock import FileLock

from .corpus import import_bytes, utc_now
from .index import build_index, load_snapshot, save_index
from .models import Document
from .preprocessing import PREPROCESSING
from .purge import resume_pending_purge
from .sentence_splitter import SENTENCE_VERSION
from .storage import StorageError, append_manifest, load_deleted, load_documents, read_manifest, save_documents, write_json
from .xml_parser import MAX_XML_BYTES, PARSER_VERSION, ParseError, articles_in_xml, parse_article

SUCCESS = {"imported", "updated", "duplicate"}


@dataclass
class SyncResult:
    imported: int = 0
    updated: int = 0
    rebuilt: bool = False
    removed: int = 0
    restored: int = 0
    errors: list[str] = field(default_factory=list)


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (FileNotFoundError, ValueError):
        return {}


def sync_raw_folder(data_dir: Path) -> SyncResult:
    """Import changed files, retaining good documents and unchanged failure records.

    Active articles must have a valid source in raw. When several changed files have
    the same PMCID, the last filename in lexical order wins, as in import_folder.
    A shared writer lock covers import, index publication and sync-state write.
    """
    raw_dir = data_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    with FileLock(str(data_dir / ".writer.lock"), timeout=0):
        resume_pending_purge(data_dir)
        result = SyncResult()
        documents = load_documents(data_dir)
        initial_documents = documents.copy()
        deleted = load_deleted(data_dir)
        state_path = data_dir / "raw_sync_state.json"
        state = _read_json(state_path)
        old_index = _read_json(data_dir / "index.json")
        policy = {"parser": PARSER_VERSION, "sentence_rules": SENTENCE_VERSION,
                  "preprocessing": PREPROCESSING}
        previous_policy = state.get("policy") or {k: old_index.get(k) for k in policy}
        force_reparse = previous_policy != policy
        previous_files = state.get("files", {})
        if not isinstance(previous_files, dict):
            previous_files = {}
        manifest = read_manifest(data_dir)
        known: dict[str, list[dict]] = {}
        for record in manifest:
            known.setdefault(record.get("raw_path", ""), []).append(record)

        paths = sorted(p for p in raw_dir.iterdir() if p.is_file() and p.suffix.lower() == ".xml")
        files = {}
        sources = {}
        raw_contents = {}
        for path in paths:
            relative = path.relative_to(data_dir).as_posix()
            entry = previous_files.get(relative, {})
            if not isinstance(entry, dict):
                entry = {}
            try:
                # Bound the actual read, including a file that grows while copying.
                with path.open("rb") as stream:
                    raw = stream.read(MAX_XML_BYTES + 1)
                if len(raw) > MAX_XML_BYTES:
                    raise ValueError("XML 超過 25 MiB 上限")
                sha = hashlib.sha256(raw).hexdigest()
            except (OSError, ValueError) as exc:
                # A temporarily unreadable file is retried on the next rerun.
                if entry.get("read_error") != str(exc):
                    record = {"pmcid": "", "raw_path": relative, "source_url": path.resolve().as_uri(),
                              "acquired_at": utc_now(), "status": "failed", "reason": str(exc),
                              "license": "", "license_url": ""}
                    append_manifest(data_dir, record)
                    entry = {"read_error": str(exc), "records": [record]}
                files[relative] = entry
                result.errors.append(f"{path.name}：{exc}")
                continue

            records = entry.get("records", [])
            valid_records = isinstance(records, list) and bool(records) and all(
                isinstance(r, dict) and r.get("status") in SUCCESS | {"failed", "skipped_deleted"} for r in records)
            unchanged = (not force_reparse and entry.get("sha256") == sha and valid_records
                         and all(r.get("pmcid") in documents or r.get("pmcid") in deleted
                                 for r in records if r["status"] in SUCCESS))

            # Bootstrap an existing, versioned corpus without logging 15 duplicate
            # imports merely because the app gained automatic synchronization.
            if not unchanged and not force_reparse and relative not in previous_files:
                same = [r for r in known.get(relative, []) if r.get("sha256") == sha]
                latest = {r.get("pmcid", ""): r for r in same}
                # This exact raw version was already imported. A newer upload may
                # own the current document; replaying old files would undo it.
                if latest and all(pmcid in deleted or (r.get("status") in SUCCESS and pmcid in documents)
                                  for pmcid, r in latest.items()):
                    records = list(latest.values())
                    unchanged = True

            if not unchanged:
                origin = next((r for r in reversed(known.get(relative, []))
                               if r.get("sha256") == sha and r.get("status") in SUCCESS), {})
                records = import_bytes(raw, data_dir, origin.get("source_url", path.resolve().as_uri()),
                                       relative, origin.get("acquired_at"))
                result.imported += sum(r["status"] == "imported" for r in records)
                result.updated += sum(r["status"] == "updated" for r in records)
            files[relative] = {"sha256": sha, "records": records}
            raw_contents[relative] = raw
            for record in records:
                if record.get("status") in SUCCESS | {"skipped_deleted"} and record.get("pmcid"):
                    sources.setdefault(record["pmcid"], []).append(relative)
            result.errors.extend(f"{path.name}：{r['reason']}" for r in records if r["status"] == "failed")

        documents = load_documents(data_dir)
        changed = False
        auto_restored = []

        def source_document(pmcid, previous):
            candidates = sources[pmcid]
            chosen = next((p for p in candidates if files[p]["sha256"] == previous.sha256), candidates[-1])
            for element in articles_in_xml(raw_contents[chosen]):
                try:
                    fresh = parse_article(element, content_scope=previous.content_scope)
                except ParseError:
                    continue
                if fresh.pmcid == pmcid:
                    fresh.raw_path = chosen
                    fresh.sha256 = files[chosen]["sha256"]
                    origin = next((r for r in reversed(known.get(chosen, []))
                                   if r.get("sha256") == fresh.sha256 and r.get("pmcid") == pmcid), {})
                    fresh.source_url = origin.get("source_url") or previous.source_url or (data_dir / chosen).resolve().as_uri()
                    fresh.acquired_at = origin.get("acquired_at") or previous.acquired_at or utc_now()
                    return fresh
            raise StorageError(f"{pmcid} 的 XML 在同步期間改變，請重新整理。")

        for pmcid, doc in list(documents.items()):
            if pmcid not in sources:
                deleted[pmcid] = {"document": doc.to_dict(), "deleted_at": utc_now(), "reason": "source_missing"}
                del documents[pmcid]
                result.removed += 1
                changed = True
                append_manifest(data_dir, {"pmcid": pmcid, "status": "source_removed", "acquired_at": utc_now(),
                                           "reason": "raw 內已無此篇有效 XML，移除搜尋並保留回收筒備份。"})
            elif doc.raw_path not in sources[pmcid] or (force_reparse and initial_documents.get(pmcid, doc).raw_path in sources[pmcid]):
                previous = initial_documents.get(pmcid, doc) if force_reparse else doc
                documents[pmcid] = source_document(pmcid, previous)
                changed = True

        for pmcid, entry in list(deleted.items()):
            if entry.get("reason") == "source_missing" and pmcid in sources:
                documents[pmcid] = source_document(pmcid, Document.from_dict(entry["document"]))
                auto_restored.append(pmcid)
                result.restored += 1
                changed = True
                append_manifest(data_dir, {"pmcid": pmcid, "status": "source_restored", "acquired_at": utc_now(),
                                           "reason": "raw 中重新出現有效 XML，恢復搜尋。"})
        if changed:
            # New removal markers precede document publication; restoration markers follow it.
            write_json(data_dir / "deleted_articles.json", deleted)
            save_documents(data_dir, documents)
            for pmcid in auto_restored:
                del deleted[pmcid]
            if auto_restored:
                write_json(data_dir / "deleted_articles.json", deleted)
        if documents:
            try:
                load_snapshot(data_dir)
            except StorageError:
                save_index(data_dir, build_index(documents))
                result.rebuilt = True
        elif old_index and old_index.get("document_count") != 0:
            save_index(data_dir, build_index({}))
            result.rebuilt = True
        new_state = {"policy": policy, "files": files}
        if new_state != state:
            write_json(state_path, new_state)
        return result


def raw_signature(data_dir: Path) -> tuple:
    """Small-corpus polling signal; hash content even when size/mtime are unchanged."""
    try:
        paths = sorted(p for p in (data_dir / "raw").iterdir() if p.is_file() and p.suffix.lower() == ".xml")
    except FileNotFoundError:
        return ()
    except OSError as exc:
        return (("raw", type(exc).__name__),)
    values = []
    for path in paths:
        try:
            with path.open("rb") as stream:
                digest = hashlib.sha256(stream.read(MAX_XML_BYTES + 1)).hexdigest()
            values.append((path.name, digest))
        except OSError as exc:
            values.append((path.name, type(exc).__name__))
    return tuple(values)
