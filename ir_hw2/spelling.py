"""Conservative, opt-in spelling suggestions using handwritten Levenshtein DP.

Vocabulary counts are B-condition corpus CF, never search-index expansions.
The returned suggested_query is separate from the original query; callers must
ask the user to adopt it. An unknown biomedical term is not proof of a typo.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from functools import lru_cache
from types import MappingProxyType

import regex

from ir_hw1.models import Document
from ir_hw1.preprocessing import normalize
from ir_hw2.analysis import tokenize

SPELLING_VERSION = "hw2-levenshtein-hw1-cf-v2"
MAX_WORD_LENGTH = 64
SHORT_WORD_LENGTH = 3
ONE_EDIT_MAX_LENGTH = 5
MAX_SUGGESTIONS = 3
# Cache/index layout only; the spelling rules and ranked output stay at v2.
SPELLING_INDEX_VERSION = "prepared-letter-mask-v1"
# Keep internal punctuation inside a query term so GLP-1, IL-6, numeric
# expressions and biomedical compounds cannot be silently corrected in parts.
_QUERY_TOKEN_RE = regex.compile(r"[\p{L}\p{M}\p{N}]+(?:[-‐‑‒–—_'’./][\p{L}\p{M}\p{N}]+)*")


def edit_distance(source: str, target: str, max_distance: int | None = None) -> int:
    """Unit-cost insertion/deletion/substitution DP, with two rows of memory.

    Adjacent transposition costs two operations (ordinary Levenshtein, not
    Damerau-Levenshtein). When bounded, return max_distance + 1 for any distance
    above the threshold; distances within the threshold remain exact.
    """
    if max_distance is not None and max_distance < 0:
        raise ValueError("max_distance must be non-negative")
    if source == target:
        return 0
    if len(source) < len(target):
        source, target = target, source
    if max_distance is not None and len(source) - len(target) > max_distance:
        return max_distance + 1
    # Equal ends need no edits. Trimming is exact for unit-cost Levenshtein.
    prefix = 0
    while prefix < len(target) and source[prefix] == target[prefix]:
        prefix += 1
    source, target = source[prefix:], target[prefix:]
    suffix = 0
    while suffix < len(target) and source[-suffix - 1] == target[-suffix - 1]:
        suffix += 1
    if suffix:
        source, target = source[:-suffix], target[:-suffix]
    if not target:
        return min(len(source), max_distance + 1) if max_distance is not None else len(source)
    if max_distance is not None:
        # Any path within k edits stays inside a diagonal band of width 2k+1.
        # Cells outside the band are unreachable within the requested bound.
        limit = max_distance + 1
        previous = list(range(len(target) + 1))
        for i, source_char in enumerate(source, 1):
            current = [limit] * (len(target) + 1)
            current[0] = min(i, limit)
            row_minimum = limit
            for j in range(max(1, i - max_distance), min(len(target), i + max_distance) + 1):
                current[j] = min(current[j - 1] + 1, previous[j] + 1,
                                 previous[j - 1] + (source_char != target[j - 1]))
                row_minimum = min(row_minimum, current[j])
            if row_minimum > max_distance:
                return limit
            previous = current
        return min(previous[-1], limit)
    previous = list(range(len(target) + 1))
    for i, source_char in enumerate(source, 1):
        current = [i]
        for j, target_char in enumerate(target, 1):
            current.append(min(current[j - 1] + 1, previous[j] + 1,
                               previous[j - 1] + (source_char != target_char)))
        previous = current
    return previous[-1]


def build_vocabulary(
    documents: Mapping[str, Document] | Iterable[Document], *, abstracts_only: bool = False,
) -> dict[str, int]:
    """Count B tokens in stored text blocks, or explicitly in abstracts only.

    Search-library mode includes all main blocks, matching available searchable
    content. Formal abstract snapshots already contain only abstract blocks;
    callers may also use abstracts_only=True to exclude title/body explicitly.
    Section labels and back matter are never added. B directly uses the original
    HW1 tokenizer, preserving supported internal hyphens and decimals. No
    stopword removal, stemming, or expansion is applied.
    """
    values = documents.values() if isinstance(documents, Mapping) else documents
    counts: Counter[str] = Counter()
    for document in values:
        for block in document.blocks:
            if not abstracts_only or block.kind == "abstract":
                counts.update(tokenize(block.text, "B"))
    return dict(counts)


def _normalize_vocabulary(vocabulary: Mapping[str, int]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for term, count in vocabulary.items():
        if not isinstance(term, str) or not isinstance(count, int) or isinstance(count, bool) or count <= 0:
            raise ValueError("Vocabulary must map strings to positive integer CF values")
        counts[normalize(term)] += count
    return dict(counts)


def _protection_reason(term: str, vocabulary: Mapping[str, int]) -> str | None:
    if normalize(term) in vocabulary:
        return "known_word"
    if any(char.isdigit() for char in term):
        return "contains_digits"
    if not term.isascii():
        return "non_ascii"
    if len(term) <= SHORT_WORD_LENGTH:
        return "short_word"
    if len(term) > MAX_WORD_LENGTH:
        return "long_word"
    if not term.isalpha():
        return "compound_term"
    if term.isupper():
        return "uppercase_abbreviation"
    if not (term.islower() or term.istitle()):
        return "mixed_case"
    return None


def _letter_mask(term: str) -> int:
    """26-bit set of letters for an already normalized ASCII alphabetic word."""
    mask = 0
    for char in term:
        mask |= 1 << (ord(char) - ord("a"))
    return mask


class SpellingIndex:
    """Prepare one corpus once and share immutable candidates across queries.

    The per-word LRU is bounded and thread-safe; its tuple results cannot be
    mutated by callers. Each index owns its cache, so corpus updates never
    reuse another vocabulary's word frequencies or candidates.
    """

    def __init__(self, vocabulary: Mapping[str, int]):
        self.counts = MappingProxyType(_normalize_vocabulary(vocabulary))
        buckets: dict[int, list[tuple[str, int, int]]] = {}
        for term, cf in self.counts.items():
            if term.isascii() and term.isalpha() and len(term) <= MAX_WORD_LENGTH:
                buckets.setdefault(len(term), []).append((term, cf, _letter_mask(term)))
        self.buckets = MappingProxyType({length: tuple(rows) for length, rows in buckets.items()})
        self.candidates = lru_cache(maxsize=2048)(self._candidates)

    def _candidates(self, term: str, maximum: int) -> tuple[tuple[str, int, int], ...]:
        mask = _letter_mask(term)
        matches = []
        for length in range(max(1, len(term) - maximum), len(term) + maximum + 1):
            for candidate, cf, candidate_mask in self.buckets.get(length, ()):
                # Each distinct missing letter needs at least one edit. This
                # necessary condition prunes impossible words without losing
                # valid insertions, deletions or substitutions.
                if ((mask & ~candidate_mask).bit_count() > maximum
                        or (candidate_mask & ~mask).bit_count() > maximum):
                    continue
                distance = edit_distance(term, candidate, maximum)
                if distance <= maximum:
                    matches.append((candidate, distance, cf))
        return tuple(sorted(matches, key=lambda row: (row[1], -row[2], row[0]))[:MAX_SUGGESTIONS])


def suggest_query(query: str, vocabulary: Mapping[str, int] | SpellingIndex) -> dict:
    """Return deterministic suggestions, original text and exact span offsets.

    Words of 4–5 letters permit one edit; 6–64 letters permit two. Candidate
    ordering is edit distance ascending, corpus CF descending, then lexical.
    Correct terms use HW1 NFC/casefold and apostrophe/hyphen normalization.
    Digits, non-ASCII, uppercase/mixed-case biomedical names, short words and
    punctuated compounds remain untouched; checks use the original spelling.
    """
    index = vocabulary if isinstance(vocabulary, SpellingIndex) else SpellingIndex(vocabulary)
    normalized = index.counts
    changes = []
    protected = []
    unresolved = []
    candidate_cache: dict[str, list[dict]] = {}
    pieces: list[str] = []
    cursor = 0
    for match in _QUERY_TOKEN_RE.finditer(query):
        original = match.group()
        start, end = match.span()
        reason = _protection_reason(original, normalized)
        if reason:
            protected.append({"term": original, "start": start, "end": end, "reason": reason})
            continue
        lowered = normalize(original)
        maximum = 1 if len(lowered) <= ONE_EDIT_MAX_LENGTH else 2
        if lowered not in candidate_cache:
            candidate_cache[lowered] = [
                {"term": term, "distance": distance, "cf": cf}
                for term, distance, cf in index.candidates(lowered, maximum)
            ]
        candidates = candidate_cache[lowered]
        if not candidates:
            unresolved.append({"term": original, "start": start, "end": end})
            continue
        suggestion = candidates[0]["term"]
        if original.istitle():
            suggestion = suggestion.capitalize()
        changes.append({"original": original, "suggestion": suggestion, "start": start,
                        "end": end, "candidates": candidates})
        pieces.extend((query[cursor:start], suggestion))
        cursor = end
    pieces.append(query[cursor:])
    message = (
        "已產生拼字建議；原查詢保持不變，請自行決定是否採用。未知生醫詞不一定是錯字。"
        if changes else "沒有可提供的拼字建議；原查詢保持不變。"
    )
    if unresolved:
        message += " 部分未知詞在允許編輯距離內沒有語料候選，已保留原詞。"
    return {"original_query": query, "suggested_query": "".join(pieces), "changes": changes,
            "protected_terms": protected, "unresolved_terms": unresolved, "message": message,
            "settings": {"version": SPELLING_VERSION, "distance": "Levenshtein DP",
                         "one_edit_max_length": ONE_EDIT_MAX_LENGTH, "max_distance": 2,
                         "top_k": MAX_SUGGESTIONS, "vocabulary": "condition B corpus CF (original HW1 tokenizer; stopwords retained)",
                         "normalization": "ir_hw1.preprocessing.normalize: NFC, casefold, apostrophe/hyphen mapping"}}
