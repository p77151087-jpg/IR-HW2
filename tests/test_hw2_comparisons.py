import copy
import csv
import json
import math
from collections import Counter
from pathlib import Path

import pytest

from ir_hw2 import comparisons


@pytest.fixture(scope="module")
def summary():
    return json.loads((Path(__file__).resolve().parents[1] / "reports/hw2/experiment/summary.json").read_text(encoding="utf-8"))


def test_cf_df_hover_values_use_document_coverage_not_token_share(summary):
    rows = {row['term']: row for row in comparisons.selected_term_rows(summary)}
    term = rows['semaglutide']
    assert term['cf'] == 649 and term['df'] == 228
    assert term['coverage'] == pytest.approx(0.228)
    assert term['occurrences_per_document'] == pytest.approx(649 / 228)
    assert rows['il6']['cf'] == rows['pathway-specific']['cf']
    assert rows['il6']['idf'] > rows['pathway-specific']['idf']


def test_all_four_segments_are_compared_without_changing_the_saved_results(summary):
    original = copy.deepcopy(summary)
    rows = comparisons.segment_rows(summary)
    assert len(rows) == 12
    assert {row['condition'] for row in rows} == set('ABCD')
    assert all(row['best'] == ['middle'] for row in comparisons.best_segments(summary))
    assert summary == original


def test_best_segment_requires_both_criteria_and_handles_undefined_fits():
    sample = {'conditions': {'A': {'segments': {
        'head': {'r_squared': .99, 'rmse': .3},
        'middle': {'r_squared': .9, 'rmse': .1},
        'tail': {'r_squared': None, 'rmse': 0},
    }}}}
    assert comparisons.best_segments(sample) == [{'condition': 'A', 'best': [], 'status': 'mixed'}]
    sample['conditions']['A']['segments'] = {'tail': {'r_squared': None, 'rmse': 0}}
    assert comparisons.best_segments(sample)[0]['status'] == 'insufficient'


def test_representative_terms_remain_real_and_work_for_a_small_corpus():
    sample = {'conditions': {'B': {'documents': 2}}, 'selected_terms': [
        {'condition': 'B', 'term': 'example', 'cf': 3, 'df': 2, 'idf': 0},
    ]}
    assert [row['term'] for row in comparisons.representative_terms(sample)] == ['example']
    assert comparisons.selected_term_rows(sample)[0]['coverage'] == 1


def test_interactive_charts_produce_valid_specs_with_bounded_data(summary):
    figures = [comparisons.count_chart(summary, key) for key in comparisons.METRICS]
    figures += [comparisons.top_terms_chart(summary, c, 10, shared_scale=True) for c in 'ABCD']
    figures += [comparisons.top_terms_chart(summary, 'B'), comparisons.segment_chart(summary, 'r_squared'),
                comparisons.segment_chart(summary, 'rmse'), comparisons.idf_terms_chart(summary)]
    for chart in figures:
        spec = chart.to_dict(validate=True)
        assert spec['$schema']
        assert sum(len(rows) for rows in spec.get('datasets', {}).values()) <= 200


def test_all_terms_match_original_export_and_bubbles_conserve_vocabulary(summary):
    original = copy.deepcopy(summary)
    rows = comparisons.all_term_rows(summary)
    path = Path(__file__).resolve().parents[1] / 'reports/hw2/experiment/terms_B.csv'
    with path.open(encoding='utf-8-sig', newline='') as stream:
        saved = list(csv.DictReader(stream))
    assert len(rows) == len(saved) == len(summary['conditions']['B']['cf'])
    for actual, expected in zip(rows, saved):
        assert actual['term'] == expected['term']
        assert all(actual[field] == int(expected[field]) for field in ('rank', 'cf', 'df'))
        assert actual['idf'] == float(expected['idf'])
    for selected in (False, True):
        source = comparisons.selected_term_rows(summary) if selected else rows
        if selected:
            assert [row['term'] for row in source] == [row['term'] for row in summary['selected_terms']]
        for coordinates in (('cf', 'df'), ('df',)):
            bubbles = comparisons.frequency_bubbles(source, coordinates)
            expected = Counter(tuple(row[field] for field in coordinates) for row in source)
            assert {tuple(row[field] for field in coordinates): row['term_count'] for row in bubbles} == expected
            assert sum(row['term_count'] for row in bubbles) == len(source)
            for bubble in bubbles:
                examples = bubble['examples'].split('、')
                assert len(examples) == min(5, bubble['term_count'])
                matching = {row['term'] for row in source if all(row[field] == bubble[field] for field in coordinates)}
                assert set(examples) <= matching
    assert summary == original


@pytest.mark.parametrize('chart_function,coordinates', [
    (comparisons.cf_df_chart, ('cf', 'df')),
    (comparisons.idf_curve_chart, ('df',)),
])
def test_bubble_specs_include_every_coordinate_even_above_altair_row_limit(chart_function, coordinates):
    # More distinct coordinates than Altair's default 5,000-row DataFrame cap.
    n = 6001
    summary = {'conditions': {'B': {'documents': n, 'cf': {}, 'df': {}}}}
    for i in range(1, n + 1):
        summary['conditions']['B']['cf'][f'term{i}'] = i + 1
        summary['conditions']['B']['df'][f'term{i}'] = i
    spec = chart_function(summary).to_dict(validate=True)
    points = spec['layer'][1]
    data = points['data']['values']
    assert len(data) == n
    assert sum(row['term_count'] for row in data) == n
    assert max(row['df'] for row in data) == n
    assert points['encoding']['x']['scale']['base'] == 10
    assert points['encoding']['size']['field'] == 'term_count'
    assert points['encoding']['size']['legend']['values'] == [1]
    assert len(points['encoding']['tooltip']) == 4
    if coordinates == ('cf', 'df'):
        assert points['encoding']['y']['scale']['base'] == 10
        assert spec['layer'][0]['mark']['strokeDash'] == [5, 5]
    else:
        assert all(row['idf'] == pytest.approx(math.log10(n / row['df'])) for row in data)
