"""Shared, offset-preserving vocabulary for relevance retrieval only.

Raw tokenization remains available for statistics and legacy exact matching.
The vocabulary is project-authored and versioned alongside its source note.
"""
import hashlib
import json
from pathlib import Path

import regex

from .models import Token
from .preprocessing import TOKENIZER_VERSION, normalize, stem_term, tokenize

_RESOURCE = (Path(__file__).resolve().parents[1] / "resources/search_vocabulary.json").read_bytes()
_VOCABULARY = json.loads(_RESOURCE)
STOPWORDS = frozenset(_VOCABULARY["stopwords"])
RELEVANCE_PREPROCESSING = {
    "version": "relevance-v2", "tokenizer": TOKENIZER_VERSION,
    "vocabulary_version": _VOCABULARY["version"],
    "vocabulary_sha256": hashlib.sha256(_RESOURCE).hexdigest(),
    "single_letters": "contextual-ascii-v1",
    "compounds": "hyphen-letter-number-v1",
}
_BOUNDARY = regex.compile(r"[-‐‑]|(?<=[\p{L}\p{M}])(?=\p{N})|(?<=\p{N})(?=\p{L})")


def isolated_letter(term: str) -> bool:
    return len(term) == 1 and term.isascii() and term.isalpha()


def compound_parts(token: Token) -> list[Token]:
    """Split source text before normalization so every part keeps exact offsets."""
    parts = []
    cursor = 0
    for boundary in _BOUNDARY.finditer(token.text):
        if cursor < boundary.start():
            text = token.text[cursor:boundary.start()]
            parts.append(Token(text, normalize(text), token.start + cursor, token.start + boundary.start()))
        cursor = boundary.end()
    if cursor < len(token.text):
        text = token.text[cursor:]
        parts.append(Token(text, normalize(text), token.start + cursor, token.end))
    return parts


def relevance_tokens(text: str, *, stemming: bool = False, include_components: bool = False) -> list[Token]:
    """Share normalization; documents also expose components, queries retain full terms.

    A compound is one query condition, never an OR between its letter/number parts.
    Full terms and components are separate vector features, with source offsets.
    """
    tokens = tokenize(text)
    protected = set()
    for i, (left, right) in enumerate(zip(tokens, tokens[1:])):
        if not text[left.end:right.start].isspace():
            continue
        if right.term in _VOCABULARY["letter_contexts"].get(left.term, []):
            protected.add(i + 1)
        if left.term in _VOCABULARY["cell_letters"] and right.term in {"cell", "cells"}:
            protected.add(i)
    result = []
    for i, token in enumerate(tokens):
        parts = compound_parts(token)
        effective = [p for p in parts if p.term not in STOPWORDS and not isolated_letter(p.term)]
        if i not in protected and not effective:
            continue
        term = "-".join(p.term for p in parts)
        candidates = [Token(token.text, term, token.start, token.end)]
        if include_components and len(parts) > 1:
            candidates.extend(effective)
        seen = set()
        for candidate in candidates:
            term = stem_term(candidate.term) if stemming else candidate.term
            key = (term, candidate.start, candidate.end)
            if key not in seen:
                seen.add(key)
                result.append(Token(candidate.text, term, candidate.start, candidate.end))
    return result


def relevance_query(query: str, *, stemming: bool = False) -> tuple[list[str], str]:
    terms = list(dict.fromkeys(t.term for t in relevance_tokens(query, stemming=stemming)))
    if terms:
        return terms, ""
    remaining = [t.term for t in tokenize(query) if t.term not in STOPWORDS]
    if remaining and all(isolated_letter(t) for t in remaining):
        return [], "關鍵字過於簡短，請補充完整詞彙，例如 vitamin C 或 hepatitis B。"
    return [], "請輸入至少一個具有主題意義的有效關鍵字；空白、標點或只有停用詞不會搜尋全部文章。"
