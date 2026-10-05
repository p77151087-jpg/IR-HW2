"""Permanent removal with an idempotent, local crash-recovery journal."""
import base64
import hashlib
import json
from pathlib import Path
from xml.etree import ElementTree as ET

from filelock import FileLock

from .corpus import utc_now
from .index import build_index, save_index
from .models import Document
from .storage import (StorageError, append_manifest, atomic_write, load_deleted,
                      load_documents, read_manifest, save_documents, write_json)
from .xml_parser import MAX_XML_BYTES, ParseError, descendants, first, local_name, parse_xml_root, pubmed_identifiers, readable

JOURNAL = "purge_pending.json"


def managed_path(data_dir: Path, relative: str) -> Path:
    """Only immediate XML children of our own raw/rejected directories are mutable."""
    path = data_dir / relative
    if (Path(relative).is_absolute() or path.suffix.lower() != ".xml"
            or path.parent not in {data_dir / "raw", data_dir / "rejected"}
            or path.is_symlink() or path.resolve().parent not in {
                data_dir.resolve() / "raw", data_dir.resolve() / "rejected"}):
        raise StorageError(f"拒絕刪除資料目錄以外的檔案：{relative}")
    return path


def article_id(article: ET.Element) -> str:
    if local_name(article) == "PubmedArticle":
        pmid, pmcid, _ = pubmed_identifiers(article)
        return pmcid or ("PMID" + pmid if pmid else "")
    front = next((n for n in article if local_name(n) == "front"), None)
    meta = first(front, "article-meta") if front is not None else None
    if meta is None:
        return ""
    identifiers = {n.get("pub-id-type"): readable(n).upper() for n in descendants(meta, "article-id")}
    value = identifiers.get("pmcid", identifiers.get("pmc", ""))
    return "PMC" + value if value.isdigit() else value


def resume_pending_purge(data_dir: Path) -> bool:
    """Caller holds writer lock. Replay only the already-approved removal plan."""
    journal = data_dir / JOURNAL
    if not journal.exists():
        return False
    try:
        plan = json.loads(journal.read_text(encoding="utf-8"))
        documents = {k: Document.from_dict(v) for k, v in plan["documents"].items()}
        if not isinstance(plan["deleted"], dict) or not isinstance(plan["records"], list):
            raise ValueError("invalid purge plan")
        for relative, change in plan["files"].items():
            managed_path(data_dir, relative)
            if change["content"] is not None:
                replacement = base64.b64decode(change["content"], validate=True)
                if hashlib.sha256(replacement).hexdigest() != change["after"]:
                    raise ValueError("invalid replacement hash")
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise StorageError("永久刪除恢復紀錄損壞，請保留 purge_pending.json 並檢查，暫停清理以免誤刪。") from exc
    for relative, change in plan["files"].items():
        path = managed_path(data_dir, relative)
        replacement = base64.b64decode(change["content"]) if change["content"] is not None else None
        if path.exists():
            with path.open("rb") as stream:
                digest = hashlib.sha256(stream.read(MAX_XML_BYTES + 1)).hexdigest()
            if digest not in {change["before"], change["after"]}:
                raise StorageError(f"永久刪除尚未完成：{relative} 在處理期間被其他程式修改，請先保留現場並檢查。")
        elif replacement is None:
            continue
        if replacement is None:
            path.unlink()
        else:
            atomic_write(path, replacement)
    save_documents(data_dir, documents)
    write_json(data_dir / "deleted_articles.json", plan["deleted"])
    save_index(data_dir, build_index(documents))
    completed = {r.get("purge_event") for r in read_manifest(data_dir)}
    for record in plan["records"]:
        if record["purge_event"] not in completed:
            append_manifest(data_dir, record)
    # Manifest records bootstrap the pruned versions without replaying old content.
    (data_dir / "raw_sync_state.json").unlink(missing_ok=True)
    journal.unlink()
    return True


def purge_articles(data_dir: Path, pmcids: list[str]) -> int:
    """Remove selected trash entries and all identifiable raw copies, never live IDs."""
    data_dir = data_dir.resolve()
    with FileLock(str(data_dir / ".writer.lock"), timeout=0):
        resume_pending_purge(data_dir)
        documents, deleted = load_documents(data_dir), load_deleted(data_dir)
        selected = set(pmcids) & deleted.keys()
        if not selected:
            return 0
        timestamp = utc_now()
        manifest = read_manifest(data_dir)
        known_paths = {r.get("raw_path") for r in manifest if r.get("pmcid") in selected}
        known_paths.update(deleted[k]["document"]["raw_path"] for k in selected)
        paths = set()
        for folder in (data_dir / "raw", data_dir / "rejected"):
            if folder.exists():
                paths.update(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == ".xml")
        # Validate all changes before writing an irreversible plan.
        files, records = {}, []
        for path in sorted(paths):
            relative = path.relative_to(data_dir).as_posix()
            with path.open("rb") as stream:
                raw = stream.read(MAX_XML_BYTES + 1)
            try:
                root = parse_xml_root(raw)
            except ParseError:
                if relative in known_paths:
                    raise StorageError(f"{relative} 已損壞或過大，無法安全判斷是否含其他文章；此次尚未刪除，請先修復或移走該檔。")
                continue
            nodes = descendants(root, "article") + descendants(root, "PubmedArticle")
            targets = {node for node in nodes if article_id(node) in selected}
            if not targets:
                continue
            managed_path(data_dir, relative)
            for parent in root.iter():
                for child in list(parent):
                    if child in targets:
                        parent.remove(child)
            survivors = [] if root in targets else descendants(root, "article") + descendants(root, "PubmedArticle")
            replacement = ET.tostring(root, encoding="utf-8", xml_declaration=True) if survivors else None
            if replacement is not None and len(replacement) > MAX_XML_BYTES:
                raise StorageError(f"{relative} 清理後超過 XML 大小上限；此次尚未刪除，請先拆分檔案。")
            after = hashlib.sha256(replacement).hexdigest() if replacement is not None else None
            files[relative] = {"before": hashlib.sha256(raw).hexdigest(), "after": after,
                               "content": base64.b64encode(replacement).decode("ascii") if replacement is not None else None}
            if replacement is not None:
                # Only metadata changes for other documents; retain their latest content.
                for doc in documents.values():
                    if doc.raw_path == relative:
                        doc.sha256 = after
                for pmcid, entry in deleted.items():
                    if pmcid not in selected and entry["document"]["raw_path"] == relative:
                        entry["document"]["sha256"] = after
                for node in survivors:
                    pmcid = article_id(node)
                    if pmcid in documents or pmcid in deleted:
                        origin = next((r for r in reversed(manifest)
                                       if r.get("pmcid") == pmcid and r.get("raw_path") == relative
                                       and r.get("status") in {"imported", "updated", "duplicate"}), {})
                        records.append({"pmcid": pmcid, "raw_path": relative, "sha256": after,
                                        "status": "duplicate", "acquired_at": origin.get("acquired_at", timestamp),
                                        "source_url": origin.get("source_url", path.as_uri()),
                                        "modified_at": timestamp,
                                        "reason": "共用 XML 已移除永久刪除文章；本篇既有內容保留。"})
        for pmcid in sorted(selected):
            del deleted[pmcid]
            records.append({"pmcid": pmcid, "status": "purged", "acquired_at": timestamp,
                            "reason": "已永久刪除文章備份、原始全文與索引；僅保留操作紀錄。"})
        for number, record in enumerate(records):
            record["purge_event"] = f"{timestamp}:{number}"
        plan = {"files": files, "documents": {k: d.to_dict() for k, d in documents.items()},
                "deleted": deleted, "records": records}
        write_json(data_dir / JOURNAL, plan)
        resume_pending_purge(data_dir)
        return len(selected)
