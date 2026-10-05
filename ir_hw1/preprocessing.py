"""Tokenizer shared by full-text word statistics, indexing, queries and evaluation."""
import unicodedata
from functools import lru_cache
from importlib.metadata import version

import regex
from nltk.stem import PorterStemmer

from .models import Token

TOKENIZER_VERSION = "unicode-word-v1"
PREPROCESSING = {"tokenizer": TOKENIZER_VERSION, "casefold": True,
                 "stemming": False, "remove_stopwords": False}
TOKEN_RE = regex.compile(r"\p{N}+(?:\.\p{N}+)+|[\p{L}\p{N}][\p{L}\p{M}\p{N}]*(?:[-‐‑'’][\p{L}\p{N}][\p{L}\p{M}\p{N}]*)*")
PORTER_PREPROCESSING = {**PREPROCESSING, "stemming": "porter",
                        "implementation": "nltk", "implementation_version": version("nltk"),
                        "mode": PorterStemmer.MARTIN_EXTENSIONS, "scope": "ascii-alpha-v1"}
_PORTER = PorterStemmer(mode=PorterStemmer.MARTIN_EXTENSIONS)


def normalize(term: str) -> str:
    return unicodedata.normalize("NFC", term).casefold().replace("’", "'").replace("‐", "-").replace("‑", "-")


def tokenize(text: str) -> list[Token]:
    return [Token(m.group(), normalize(m.group()), m.start(), m.end())
            for m in TOKEN_RE.finditer(text)]


@lru_cache(maxsize=32768)
def stem_term(term: str) -> str:
    """Stem a normalized English word, preserving numbers and compound terms."""
    if term.isascii() and term.isalpha():
        return _PORTER.stem(term, to_lowercase=False)
    return term


def query_terms(query: str, *, stemming: bool = False) -> list[str]:
    terms = (stem_term(t.term) if stemming else t.term for t in tokenize(query))
    return list(dict.fromkeys(terms))
