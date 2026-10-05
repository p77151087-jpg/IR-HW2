"""Portable JSON persistence. Atomic replacements; no executable pickle files."""
import hashlib
import json
import os
import tempfile
from pathlib import Path

from .models import Document

DEFAULT_DATA = Path(__file__).resolve().parents[1] / "data"


class StorageError(ValueError):
    pass


def atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def write_json(path: Path, value: object) -> None:
    atomic_write(path, json_bytes(value))


def doc_sort_key(pmcid: str) -> tuple:
    digits = pmcid[4:] if pmcid.startswith("PMID") else pmcid[3:] if pmcid.startswith("PMC") else ""
    return (int(digits), pmcid) if digits.isdigit() else (0, pmcid)


def corpus_bytes(documents: dict[str, Document]) -> bytes:
    return b"".join(json_bytes(documents[k].to_dict()) + b"\n" for k in sorted(documents, key=doc_sort_key))


def corpus_fingerprint(documents: dict[str, Document]) -> str:
    return hashlib.sha256(corpus_bytes(documents)).hexdigest()


def save_documents(data_dir: Path, documents: dict[str, Document]) -> None:
    atomic_write(data_dir / "processed" / "articles.jsonl", corpus_bytes(documents))


def load_documents(data_dir: Path = DEFAULT_DATA) -> dict[str, Document]:
    if (data_dir / "purge_pending.json").exists():
        raise StorageError("永久刪除尚未完成，請重新整理網站以繼續清理；暫不使用未同步的文章資料。")
    path = data_dir / "processed" / "articles.jsonl"
    if not path.exists():
        return {}
    try:
        values = [Document.from_dict(json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if len({d.pmcid for d in values}) != len(values):
            raise ValueError("processed 內有重複 PMCID")
        deleted = load_deleted(data_dir)
        return {d.pmcid: d for d in values if d.pmcid not in deleted}
    except (ValueError, TypeError, KeyError) as exc:
        raise StorageError("文章快照損壞，請備份後從 data/raw 重新匯入。") from exc


def load_deleted(data_dir: Path) -> dict:
    """Persistent tombstones plus recoverable document backups; fail closed."""
    path = data_dir / "deleted_articles.json"
    if not path.exists():
        return {}
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(entries, dict):
            raise ValueError("invalid trash")
        for pmcid, entry in entries.items():
            if Document.from_dict(entry["document"]).pmcid != pmcid:
                raise ValueError("invalid document identity")
        return entries
    except (ValueError, TypeError, KeyError) as exc:
        raise StorageError("回收筒紀錄損壞，請先還原 deleted_articles.json 的備份。") from exc


def append_manifest(data_dir: Path, record: dict) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    with (data_dir / "manifest.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json_bytes(record).decode("utf-8") + "\n")
        stream.flush()


def read_manifest(data_dir: Path = DEFAULT_DATA) -> list[dict]:
    path = data_dir / "manifest.jsonl"
    if not path.exists():
        return []
    try:
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except ValueError as exc:
        raise StorageError("manifest 格式損壞，請檢查最後一筆紀錄。") from exc
