import importlib.util
from pathlib import Path

p = Path(__file__).resolve().parents[1] / 'scripts' / 'evaluate-pilot.py'
spec = importlib.util.spec_from_file_location('evaluate_pilot', p)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def case(answerability='answerable'):
    return {'id': 'q1', 'answerability': answerability,
            'expected_material_ids': ['m1', 'm2'],
            'expected_chunks': [{'chunk_id': 'c1'}, {'chunk_id': 'c2'}]}


def test_source_and_exact_chunk_hits_are_separate_and_multisource_coverage_is_visible():
    scored = module.score_ranking(case(), [
        {'material_id': 'other', 'chunk_id': 'other'},
        {'material_id': 'm2', 'chunk_id': 'a-different-chunk'},
        {'material_id': 'm2', 'chunk_id': 'c2'},
    ])
    assert scored['known_source_hit_at_1'] == 0
    assert scored['known_source_hit_at_5'] == 1
    assert scored['known_chunk_hit_at_5'] == 1
    assert scored['all_expected_sources_at_5'] == 0
    assert scored['reciprocal_rank'] == 0.5


def test_unsupported_queries_are_not_scored_as_missing_retrieval_answers():
    assert module.score_ranking(case('unsupported'), [{'material_id': 'm1', 'chunk_id': 'c1'}]) is None


def test_empty_positive_results_are_failures_and_zero_denominator_is_not_success():
    scored = module.score_ranking(case(), [])
    assert scored['known_source_hit_at_5'] == 0
    assert scored['reciprocal_rank'] == 0
    assert module.aggregate_scores([])['known_source_hit_at_5'] is None
    assert module.aggregate_scores([scored])['known_source_hit_at_5'] == 0


def test_unknown_answerability_cannot_silently_shrink_the_denominator():
    import pytest
    with pytest.raises(ValueError, match='answerability'):
        module.score_ranking(case('answeable'), [])


def test_partial_benchmark_cannot_be_reported_as_complete():
    import pytest
    with pytest.raises(ValueError, match='24 answerable and 6 unsupported'):
        module.validate_cases([case()])


def test_saved_rankings_exclude_raw_source_body_and_vectors():
    items = module.metadata_items([{'chunk_id': 'c1', 'material_id': 'm1',
                                   'text': 'private-source-sentinel',
                                   'embedding': [1.0], 'rank': 0.1}])
    assert items == [{'chunk_id': 'c1', 'material_id': 'm1', 'rank': 0.1}]
    assert 'private-source-sentinel' not in repr(items)
