"""Independent oracles for pruning, bounded DP and shared spelling caches."""
import itertools
import random

import pytest

from ir_hw2.spelling import SpellingIndex, edit_distance, suggest_query


def reference_distance(source, target):
    # Deliberately plain full matrix: no trimming, banding or early exit.
    matrix = [[0] * (len(target) + 1) for _ in range(len(source) + 1)]
    for i in range(len(source) + 1):
        matrix[i][0] = i
    for j in range(len(target) + 1):
        matrix[0][j] = j
    for i, left in enumerate(source, 1):
        for j, right in enumerate(target, 1):
            matrix[i][j] = min(matrix[i - 1][j] + 1, matrix[i][j - 1] + 1,
                               matrix[i - 1][j - 1] + (left != right))
    return matrix[-1][-1]


def test_trimmed_banded_dp_matches_independent_matrix():
    randomizer = random.Random(42)
    pairs = [("".join(randomizer.choices("abéc心", k=randomizer.randrange(20))),
              "".join(randomizer.choices("abéc心", k=randomizer.randrange(20))))
             for _ in range(300)]
    pairs += [("prefix" + a + "suffix", "prefix" + b + "suffix") for a, b in pairs[:100]]
    for left, right in pairs:
        expected = reference_distance(left, right)
        assert edit_distance(left, right) == expected
        for bound in range(4):
            assert edit_distance(left, right, bound) == min(expected, bound + 1)


def test_pruned_candidates_equal_exhaustive_ranked_candidates():
    words = ["".join(chars) for length in range(3, 7)
             for chars in itertools.product("ab", repeat=length)]
    words += ["glucose", "insulin", "insulins", "inulin", "glaucose", "cancer", "cancel"]
    vocabulary = {word: (i * 7) % 13 + 1 for i, word in enumerate(words)}
    index = SpellingIndex(vocabulary)
    for query in words + ["insulinn", "glucsoe", "cancerr", "zzzzzz", "abac", "abcdef"]:
        for bound in (1, 2):
            expected = sorted(
                ((word, reference_distance(query, word), cf) for word, cf in vocabulary.items()),
                key=lambda row: (row[1], -row[2], row[0]),
            )
            expected = tuple(row for row in expected if row[1] <= bound)[:3]
            assert index.candidates(query, bound) == expected


def test_candidate_cache_reused_between_queries_but_output_is_independent():
    index = SpellingIndex({"insulin": 10, "insulins": 2, "treatment": 5})
    first = suggest_query("insulinn", index)
    first["changes"][0]["candidates"][0]["term"] = "tampered"
    second = suggest_query("insulinn treatment", index)
    assert second["suggested_query"] == "insulin treatment"
    assert second["changes"][0]["candidates"][0]["term"] == "insulin"
    assert index.candidates.cache_info().misses == 1
    assert index.candidates.cache_info().hits == 1
    assert index.candidates.cache_info().maxsize == 2048


def test_changed_vocabulary_has_separate_cache_and_immutable_snapshot():
    vocabulary = {"insulin": 10, "insulins": 2}
    old_index = SpellingIndex(vocabulary)
    assert suggest_query("insulinn", old_index)["suggested_query"] == "insulin"
    vocabulary["insulins"] = 100
    new_index = SpellingIndex(vocabulary)
    assert suggest_query("insulinn", new_index)["suggested_query"] == "insulins"
    assert suggest_query("insulinn", old_index)["suggested_query"] == "insulin"
    with pytest.raises(TypeError):
        old_index.counts["insulins"] = 100


def test_prepared_index_matches_mapping_api_with_protected_terms():
    vocabulary = {"insulin": 10, "GLP-1": 5, "Straße": 2, "cancer": 20}
    query = "GLP-1  Insulinn, strase cancerr; β-cells"
    assert suggest_query(query, SpellingIndex(vocabulary)) == suggest_query(query, vocabulary)
