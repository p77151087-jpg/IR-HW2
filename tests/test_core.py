import json

import pytest

from ir_hw1.index import load_snapshot
from ir_hw1.models import Document, TextBlock
from ir_hw1.preprocessing import query_terms, tokenize
from ir_hw1.search import search
from ir_hw1.sentence_splitter import split_sentences
from ir_hw1.snippets import highlight, make_snippets
from ir_hw1.statistics import compute_statistics
from ir_hw1.storage import StorageError, save_documents


@pytest.mark.parametrize("query,mode,expected", [
    ("cancer", "AND", ["PMC1", "PMC2"]),
    ("cancer treatment", "AND", ["PMC2"]),
    ("cancer treatment", "OR", ["PMC1", "PMC2", "PMC3"]),
    ("CANCER cancer", "AND", ["PMC1", "PMC2"]),
    ("cancer nonexistent", "AND", []),
    ("cancer nonexistent", "OR", ["PMC1", "PMC2"]),
    (" ", "AND", []), ("...!?", "OR", []), ("nonexistent", "OR", []),
])
def test_boolean_hand_calculated(synthetic, query, mode, expected):
    assert search(synthetic[1], query, mode).document_ids == expected


def test_query_syntax_explicit(synthetic):
    assert search(synthetic[1], '"cancer treatment"').warning
    assert search(synthetic[1], "cancer OR treatment").warning
    with pytest.raises(ValueError):
        search(synthetic[1], "x", "INVALID")
    with pytest.raises(ValueError):
        search(synthetic[1], "x" * 2001)


def test_tokens():
    text = "IL-6 COVID-19 patient's 3.5 β-catenin Café CAFÉ patient’s"
    terms = [t.term for t in tokenize(text)]
    assert terms == ["il-6", "covid-19", "patient's", "3.5", "β-catenin", "café", "café", "patient's"]
    assert query_terms("IL-6 il-6") == ["il-6"]
    for token in tokenize(text):
        assert text[token.start:token.end] == token.text


@pytest.mark.parametrize("text,expected", [
    ("Cancer is common. Treatment helps!", ["Cancer is common.", "Treatment helps!"]),
    ("Dr. Smith measured 3.5 mg. Results improved.", ["Dr. Smith measured 3.5 mg.", "Results improved."]),
    ("See Fig. 2 for details. Survival improved.", ["See Fig. 2 for details.", "Survival improved."]),
    ("E. coli was detected. Treatment started.", ["E. coli was detected.", "Treatment started."]),
    ("No adverse events were observed", ["No adverse events were observed"]),
    ('He said, "It worked!" Then left.', ['He said, "It worked!"', "Then left."]),
    ("It improved (p < 0.05). Next trial?", ["It improved (p < 0.05).", "Next trial?"]),
    ("Smith et al. reported a benefit. We agree.", ["Smith et al. reported a benefit.", "We agree."]),
    ("As described by Smith et al. Results improved.", ["As described by Smith et al.", "Results improved."]),
    ("Visit https://example.org/a.b. More details.", ["Visit https://example.org/a.b.", "More details."]),
    ("DOI 10.1234/a.b supports it. Yes!", ["DOI 10.1234/a.b supports it.", "Yes!"]),
    ("A. B. Smith agreed. We concur.", ["A. B. Smith agreed.", "We concur."]),
    ("Really?! Yes... Done.", ["Really?!", "Yes...", "Done."]),
    ("", []), (" ... !? ", []),
])
def test_sentence_rules(text, expected):
    sentences = split_sentences(text)
    assert [s.text for s in sentences] == expected
    assert all(text[s.start:s.end] == s.text for s in sentences)


def test_hand_count_statistics():
    doc = Document("PMC1", "IL-6", [TextBlock("b0", "title", "Title", "IL-6", False),
                                      TextBlock("b1", "body", "Body", "Dose 3.5 mg.")])
    # "IL-6\nDose 3.5 mg." = 17 code points, 14 non-whitespace, 4 tokens, 1 sentence.
    stats = compute_statistics(doc)
    assert {k: stats[k] for k in ("characters", "characters_no_whitespace", "words", "sentences")} == {
        "characters": 17, "characters_no_whitespace": 14, "words": 4, "sentences": 1}


def test_highlight_safe_and_offsets(synthetic):
    assert highlight('<script>& Cancer', [(10, 16)]) == '&lt;script&gt;&amp; <mark>Cancer</mark>'
    assert highlight("abcdef", [(1, 3), (2, 5)]) == "a<mark>bcde</mark>f"
    docs, index = synthetic
    snippets = make_snippets(docs["PMC2"], index, ["cancer", "treatment"])
    assert snippets[0]["kind"] == "body"
    assert snippets[0]["html"] == "<mark>Cancer</mark> <mark>treatment</mark>."


def test_persistence_and_stale_index(stored, synthetic):
    docs, index = load_snapshot(stored)
    assert search(index, "cancer treatment").document_ids == ["PMC2"]
    docs["PMC2"].blocks[-1].text += " changed"
    save_documents(stored, docs)
    with pytest.raises(StorageError, match="不一致"):
        load_snapshot(stored)


def test_corrupt_and_missing_snapshots(tmp_path, stored):
    with pytest.raises(StorageError, match="尚無文章"):
        load_snapshot(tmp_path / "empty")
    (stored / "index.json").write_text("{broken", encoding="utf-8")
    with pytest.raises(StorageError, match="損壞"):
        load_snapshot(stored)


def test_preprocessing_version_mismatch(stored):
    path = stored / "index.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["preprocessing"]["stemming"] = True
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(StorageError, match="不一致"):
        load_snapshot(stored)
