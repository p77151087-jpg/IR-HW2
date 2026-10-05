"""Read a PubMed PMID text export without interpreting arbitrary file contents."""
from dataclasses import dataclass

from .library import MAX_PMIDS_PER_BATCH, normalize_pmid

MAX_LIST_BYTES = 1024 * 1024


@dataclass(frozen=True)
class PMIDList:
    pmids: list[str]
    duplicates: int


def parse_pmid_list(raw: bytes) -> PMIDList:
    if len(raw) > MAX_LIST_BYTES:
        raise ValueError("PMID 清單不可超過 1 MiB。")
    encoding = "utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
    try:
        text = raw.decode(encoding)
    except UnicodeError as exc:
        raise ValueError("無法讀取文字編碼，請將 PMID 清單另存為 UTF-8 TXT。") from exc
    pmids, seen, invalid = [], set(), []
    duplicates = 0
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            pmid = normalize_pmid(line)
        except ValueError:
            invalid.append(number)
            continue
        if pmid in seen:
            duplicates += 1
        else:
            seen.add(pmid)
            pmids.append(pmid)
    if invalid:
        lines = "、".join(map(str, invalid[:10])) + ("…" if len(invalid) > 10 else "")
        raise ValueError(f"第 {lines} 行不是有效 PMID。每行只放一個 PMID（例如 33126180），請修正後重新上傳。")
    if not pmids:
        raise ValueError("清單沒有 PMID，請每行放入一個 PMID。")
    if len(pmids) > MAX_PMIDS_PER_BATCH:
        raise ValueError(f"每次最多 {MAX_PMIDS_PER_BATCH} 個不同的 PMID，請將清單分成較小的檔案。")
    return PMIDList(pmids, duplicates)
