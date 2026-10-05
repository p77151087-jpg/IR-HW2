import html

from .index import get_postings
from .models import Document
from .sentence_splitter import split_sentences


def highlight(text: str, ranges: list[tuple[int, int]], offset: int = 0) -> str:
    merged: list[list[int]] = []
    for start, end in sorted(ranges):
        start, end = max(0, start - offset), min(len(text), end - offset)
        if start >= end:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(end, merged[-1][1])
        else:
            merged.append([start, end])
    pieces = []
    cursor = 0
    for start, end in merged:
        pieces.extend([html.escape(text[cursor:start]), "<mark>", html.escape(text[start:end]), "</mark>"])
        cursor = end
    pieces.append(html.escape(text[cursor:]))
    return "".join(pieces)


def hit_locations(index: dict, doc_id: str, terms: list[str], *, stemming: bool = False,
                  relevance: bool = False, query: str | None = None,
                  document: Document | None = None) -> dict[str, list[tuple[int, int]]]:
    locations: dict = {}
    postings = get_postings(index, stemming=stemming, relevance=relevance)
    # Full terms and components already carry their own original-text spans.
    # query/document remain accepted for compatibility with existing callers.
    for term in terms:
        posting = postings.get(term, {}).get(doc_id, {})
        for block_id, start, end in posting.get("locations", []):
            locations.setdefault(block_id, []).append((start, end))
    return locations


def make_snippets(document: Document, index: dict, terms: list[str], limit: int = 2, *, stemming: bool = False,
                  locations: dict[str, list[tuple[int, int]]] | None = None, relevance: bool = False,
                  query: str | None = None) -> list[dict]:
    hits = locations if locations is not None else hit_locations(
        index, document.pmcid, terms, stemming=stemming, relevance=relevance, query=query, document=document)
    blocks = {block.id: block for block in document.blocks}
    ordered = sorted(hits, key=lambda bid: (blocks[bid].kind in {"title", "heading"}, -len(hits[bid]), int(bid[1:])))
    snippets = []
    for block_id in ordered[:limit]:
        block = blocks[block_id]
        anchor, anchor_end = sorted(hits[block_id])[0]
        sentence = next((s for s in split_sentences(block.text) if s.start <= anchor < s.end), None)
        left, right = (sentence.start, sentence.end) if sentence else (0, len(block.text))
        if right - left > 360:
            left, right = max(left, anchor - 100), min(right, anchor + 260)
            # Keep clipping readable, without moving the anchor or its offsets.
            while left > 0 and not block.text[left - 1].isspace() and anchor - left < 130:
                left -= 1
            while right < len(block.text) and not block.text[right].isspace() and right - anchor < 290:
                right += 1
        # A long phrase must be shown completely, even beyond the usual window.
        right = max(right, anchor_end)
        if locations is not None:
            # Do not leave another (possibly overlapping) phrase half-highlighted.
            for hit_start, hit_end in sorted(hits[block_id]):
                if hit_start < right < hit_end:
                    right = hit_end
        clipped = highlight(block.text[left:right], hits[block_id], left)
        snippets.append({"block_id": block_id, "section": block.section, "kind": block.kind,
                         "start": left, "end": right,
                         "html": ("…" if left else "") + clipped + ("…" if right < len(block.text) else "")})
    return snippets
