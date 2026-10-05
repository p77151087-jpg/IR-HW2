"""Publish a traceable search copy without changing the frozen experiment."""
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from xml.etree.ElementTree import Element, tostring

from filelock import FileLock

from ir_hw1.corpus import utc_now
from ir_hw1.index import build_index, save_index
from ir_hw1.storage import (append_manifest, atomic_write, load_deleted,
                            load_documents, save_documents, write_json)
from ir_hw1.xml_parser import MAX_XML_BYTES, articles_in_xml, pubmed_identifiers
from .corpus import load_corpus


def publish_search_copy(snapshot_dir: Path, data_dir: Path) -> dict:
    snapshot_dir, data_dir = Path(snapshot_dir), Path(data_dir)
    documents = load_corpus(snapshot_dir)
    if len({doc.pmcid for doc in documents.values()}) != len(documents):
        raise ValueError("不同 PMID 共用搜尋文章 ID，請先人工確認，不自動合併。")
    wanted = {doc.pmid for doc in documents.values()}
    elements = {}
    for relative in sorted({doc.raw_path for doc in documents.values()}):
        for element in articles_in_xml((snapshot_dir / relative).read_bytes()):
            pmid, _, _ = pubmed_identifiers(element)
            if pmid in wanted:
                if pmid in elements:
                    raise ValueError(f"來源包含重複 PMID：{pmid}")
                elements[pmid] = element
    if elements.keys() != wanted:
        raise ValueError("原始 XML 與摘要快照的 PMID 不一致。")
    # Keep each generated file well below the existing 25 MiB parser ceiling.
    groups = [sorted(wanted)[i:i + 100] for i in range(0, len(wanted), 100)]
    publication = []
    for group in groups:
        root = Element("PubmedArticleSet")
        for pmid in group:
            root.append(deepcopy(elements[pmid]))
        raw = tostring(root, encoding="utf-8", xml_declaration=True)
        if len(raw) > MAX_XML_BYTES:
            raise ValueError("搜尋副本超過 XML 大小上限。")
        digest = sha256(raw).hexdigest()
        relative = f"raw/hw2-glp1-{digest[:20]}.xml"
        publication.append((group, raw, digest, relative))
    data_dir.mkdir(parents=True, exist_ok=True)
    with FileLock(str(data_dir / ".writer.lock"), timeout=0):
        current = load_documents(data_dir)
        deleted = load_deleted(data_dir)
        for group, raw, digest, relative in publication:
            if not (data_dir / relative).exists() or sha256((data_dir / relative).read_bytes()).hexdigest() != digest:
                atomic_write(data_dir / relative, raw)
            for pmid in group:
                source = documents[pmid]
                copy = replace(source, raw_path=relative, sha256=digest)
                old = current.get(copy.pmcid)
                current[copy.pmcid] = copy
                deleted.pop(copy.pmcid, None)
                if old != copy:
                    append_manifest(data_dir, {"pmcid": copy.pmcid, "pmid": pmid,
                        "status": "updated" if old else "imported", "reason": "HW2 固定摘要快照之搜尋副本",
                        "raw_path": relative, "sha256": digest, "source_url": copy.source_url,
                        "acquired_at": copy.acquired_at, "imported_at": utc_now(),
                        "language": copy.language, "content_scope": "abstract",
                        "license": copy.license, "license_url": copy.license_url,
                        "snapshot_path": str(snapshot_dir.resolve()), "snapshot_raw_sha256": source.sha256})
        save_documents(data_dir, current)
        if deleted or (data_dir / "deleted_articles.json").exists():
            write_json(data_dir / "deleted_articles.json", deleted)
        save_index(data_dir, build_index(current))
    return {"published": len(documents), "library_documents": len(current),
            "source_snapshot": str(snapshot_dir), "data_dir": str(data_dir)}
