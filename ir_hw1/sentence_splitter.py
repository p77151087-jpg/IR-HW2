"""Position-preserving English sentence boundaries. No NLP sentence library."""
import re

from .models import SentenceSpan

SENTENCE_VERSION = "english-rules-v1"
PREFIXES = {"dr", "mr", "mrs", "ms", "prof", "fig", "figs", "eq", "eqs", "ref", "refs", "no", "nos", "vol", "vs", "e.g", "i.e"}
CONTEXTUAL = {"al", "etc", "approx", "inc", "ltd", "mg", "ml", "min", "max", "a.m", "p.m"}
STARTERS = {"The", "This", "These", "Those", "It", "They", "We", "Our", "However", "Results", "Treatment", "In", "A", "An", "Patients", "Further"}
PROTECTED = re.compile(r"https?://[^\s<>]+|www\.[^\s<>]+|\b10\.\d{4,9}/[^\s<>]+|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
CANDIDATE = re.compile(r"[.!?]+[\"'”’\)\]\}]*")


def split_sentences(text: str) -> list[SentenceSpan]:
    protected = []
    for match in PROTECTED.finditer(text):
        # Leave prose punctuation outside URL/DOI protection.
        protected.append((match.start(), match.start() + len(match.group().rstrip('.!?\"\'”’)]}'))))
    spans = []
    start = 0

    def emit(end: int, rule: str) -> None:
        nonlocal start
        left = start
        while left < end and text[left].isspace():
            left += 1
        right = end
        while right > left and text[right - 1].isspace():
            right -= 1
        if any(c.isalnum() for c in text[left:right]):
            spans.append(SentenceSpan(left, right, text[left:right], rule))
        start = end

    for candidate in CANDIDATE.finditer(text):
        pos, end = candidate.span()
        if any(a <= pos < b for a, b in protected):
            continue
        punctuation = candidate.group()
        if punctuation.startswith(".") and pos and pos + 1 < len(text) and text[pos - 1].isdigit() and text[pos + 1].isdigit():
            continue
        if end < len(text) and not text[end].isspace():
            continue
        rest = text[end:].lstrip()
        next_word = re.match(r"[\"'“‘(\[]*([A-Za-z]+|\d+)", rest)
        following = next_word.group(1) if next_word else ""
        rule = "terminal_punctuation"
        if punctuation.startswith(".") and rest:
            prior = re.search(r"([A-Za-z]+(?:\.[A-Za-z]+)*)$", text[:pos])
            word = prior.group(1) if prior else ""
            lower = word.lower()
            if lower in PREFIXES:
                # Figure/number references introduce a following item.
                continue
            if lower in CONTEXTUAL or ("." in word and all(len(p) == 1 for p in word.split("."))):
                if following and (following[0].isupper() or following in STARTERS):
                    rule = "abbreviation_context_boundary"
                else:
                    continue
            elif len(word) == 1 and word.isupper():
                # Initials and bacterial genera (J. Smith, E. coli).
                if following not in STARTERS:
                    continue
        emit(end, rule)
    emit(len(text), "paragraph_end")
    return spans
