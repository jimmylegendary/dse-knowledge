import copy
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import sys
import threading
import time
from urllib.error import HTTPError

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'scripts'
sys.path.insert(0, str(SCRIPTS))

import eval500_metrics as metrics

RUNNER_SPEC = importlib.util.spec_from_file_location(
    'evaluate_retrieval_confidence', SCRIPTS / 'evaluate-retrieval-confidence.py',
)
runner = importlib.util.module_from_spec(RUNNER_SPEC)
sys.modules[RUNNER_SPEC.name] = runner
RUNNER_SPEC.loader.exec_module(runner)

POLICY = 'retrieval-policy/v2.2'
CATEGORIES = (
    'compiler_kernel', 'dse_optimization', 'hardware_architecture',
    'llm_model_workload', 'memory_interconnect', 'power_thermal_packaging',
    'provenance_experiment', 'serving_scheduling', 'simulation_measurement',
)
TIERS = ('d1_clear', 'd2_semantic', 'd3_implicit', 'd4_multiconstraint')
NEGATIVE_TYPES = (
    'ood', 'wrong_revision', 'unseen_feature', 'missing_quantity',
    'unsupported_derivation', 'in_domain_missing', 'underspecified',
)


def cases_for(stage):
    tier_count = 15 if stage == 'calibration' else 75
    negative_counts = {
        'ood': 10 if stage == 'calibration' else 50,
        'wrong_revision': 6 if stage == 'calibration' else 30,
        'unseen_feature': 5 if stage == 'calibration' else 25,
        'missing_quantity': 4 if stage == 'calibration' else 20,
        'unsupported_derivation': 5 if stage == 'calibration' else 25,
        'in_domain_missing': 6 if stage == 'calibration' else 30,
        'underspecified': 4 if stage == 'calibration' else 20,
    }
    rows = []

    def add(answerability, difficulty, boundary_type, ordinal):
        index = len(rows)
        supported = answerability == 'supported'
        rows.append({
            'id': f'{stage}-{index:04d}',
            'split': stage,
            'language': 'ko' if index % 2 == 0 else 'en',
            'category': CATEGORIES[index % len(CATEGORIES)],
            'difficulty': difficulty,
            'intent_group': f'{stage}-intent-{index // 2:04d}',
            'query': f'synthetic {stage} case {index} {ordinal}',
            'answerability': answerability,
            'expected_action': 'answer' if supported else ('clarify' if answerability == 'ambiguous' else 'abstain'),
            'boundary_type': boundary_type,
            'evidence_groups': ([{
                'group_id': f'{stage}-group-{index}',
                'requirement': 'synthetic supported fact',
                'answer_fact': 'synthetic paraphrased fact',
                'alternatives': [{
                    'material_id': f'{stage}-material-{index}',
                    'revision_id': f'revision-{index}',
                    'chunk_id': f'chunk-{index}',
                    'source_url': 'https://example.invalid/source',
                    'text_sha256': 'a' * 64,
                }],
            }] if supported else []),
            'nearby_evidence': [],
            'gold_rationale': 'synthetic test fixture rationale',
            'missing_information': '' if supported else 'synthetic missing scope',
        })

    for tier in TIERS:
        for ordinal in range(tier_count):
            add('supported', tier, 'none', ordinal)
    for boundary, count in negative_counts.items():
        label = 'ambiguous' if boundary == 'underspecified' else 'insufficient'
        for ordinal in range(count):
            add(label, 'negative', boundary, ordinal)
    return rows


def response(score, *, items=None, source_results=None):
    def item(chunk, material, revision, rank_score, role='core_technical', kind='evidence'):
        return {
            'chunk_id': chunk, 'material_id': material, 'revision_id': revision,
            'role': role, 'result_kind': kind, 'rank': rank_score,
            'scores': {'dense': 1 / 61, 'lexical': 1 / 62},
            'trace': {
                'channel_ranks': {'dense': 1, 'lexical': 2},
                'rank_score': rank_score, 'role_weight': 1.0,
                'query_relevance': 2, 'graph_boost': 0.0,
                'graph_proof_count': 0, 'purpose_uncertain': False,
            },
            'text': 'must not appear in public output', 'title': 'private title',
            'url': 'https://example.invalid/private',
        }
    main_item = item('chunk-1', 'material-1', 'revision-1', score)
    return {
        'query': 'must not be copied from API response',
        'policy_version': POLICY,
        'retrieval_mode': 'baseline',
        'purpose': 'design',
        'purpose_trace': {'requested': 'auto', 'resolved': 'design', 'rule': 'test', 'uncertain': False, 'version': 'v1'},
        'items': [main_item] if items is None else items,
        'locators': [],
        'source_results': [main_item] if source_results is None else source_results,
        'reranker_trace': None,
        'dense_candidate_trace': {'method': 'exact_dense_scan', 'scope_count': 1000, 'scope_cap': 50000, 'candidate_limit': 40, 'policy_version': POLICY},
        'channels': {'dense': 1, 'lexical': 1, 'exact': 0, 'graph': 0},
        'graph_trace': {'candidate_limit': 30, 'fetch_limit': 31, 'fetched_unique_candidates': 0, 'returned_candidates': 0, 'truncated': False},
        'trace_id': 'safe-trace-id',
        'query_embedding_usage': {'input_tokens': 123},
    }


def evidence_advice(status='assessed', score=0.75, *, choice='direct_support_candidate', projection=None, metadata=None):
    if projection is None:
        projection = ({
            'total_evidence': 1, 'selected_evidence': 1, 'omitted_evidence': 0,
            'truncated_evidence': 0, 'state_bytes': 100, 'request_bytes': 200,
            'excerpt_only': True,
            'items': [{'chunk_id': 'chunk-1', 'revision_id': 'revision-1',
                       'source_text_bytes': 100, 'excerpt_text_bytes': 100, 'truncated': False}],
        } if status == 'assessed' else {})
    return {
        'schema_version': 'jev-evidence-advice/v1',
        'status': status,
        'advisory_only': True,
        'choice': choice,
        'support_score': score if status == 'assessed' else None,
        'score_kind': 'uncalibrated_direct_support_probability',
        'policy_version': 'jev-evidence-advice/v1',
        'evidence_ids': ['chunk-1'] if status == 'assessed' else [],
        'projection': projection,
        'metadata': metadata or {},
    }


def jev_search_response(score, *, status='assessed', choice='direct_support_candidate'):
    result = response(0.01)
    result['retrieval_mode'] = 'contextual_rerank'
    if status != 'assessed' and choice == 'direct_support_candidate':
        choice = None
    result['evidence_advice'] = evidence_advice(status, score, choice=choice)
    return result


def captured_canary_metadata_result(*, graph_rank=None):
    """Metadata-only fixture matching the captured v2.2 response shape."""
    item = {
        'chunk_id': 'chunk-canary',
        'material_id': 'material-canary',
        'revision_id': 'revision-canary',
        'start_offset': 0,
        'end_offset': 128,
        'scope': 'source',
        'role': 'core_technical',
        'role_metadata': {'applicability_limit': None},
        'role_policy': {
            'role': 'core_technical', 'purpose': 'design', 'weight': 1.0,
            'needs_review': False, 'is_locator': False,
            'evidence_authority': None, 'evidence_ceiling': None,
            'use_ceiling': 'bounded', 'auto_uncertain': False,
            'policy_version': POLICY,
        },
        'scores': {'dense': 0.016, 'lexical': 0.0, 'exact': 0.0},
        'trace': {
            'channel_ranks': {'dense': 1, 'lexical': 0},
            'dense_candidate_limit': 40, 'dense_candidate_method': 'exact_dense_scan',
            'dense_candidate_policy_version': 'dse-evidence-v2.2',
            'dense_scope_cap': 50000, 'dense_scope_count': 1000,
            'graph_boost': 0.0, 'graph_candidate_limit': 30,
            'graph_discarded_link_count': 0, 'graph_proof_count': 0,
            'graph_rank': graph_rank, 'graph_topic_idf': 0.0,
            'graph_truncated': False, 'purpose_rule': 'metadata-fixture',
            'purpose_uncertain': False, 'query_embedding_cache_hit': False,
            'query_embedding_task': 'retrieval_query', 'query_relevance': 2,
            'rank_score': 0.021898263027295285, 'role_weight': 1.0,
            'semantic_anchors': {},
        },
        'rank': 0.021898263027295285,
        'result_kind': 'evidence',
        'retrieval_policy': POLICY,
    }
    return {
        'policy_version': POLICY,
        'retrieval_mode': 'baseline',
        'purpose': 'design',
        'purpose_trace': {'requested': 'auto', 'resolved': 'design', 'rule': 'metadata-fixture', 'uncertain': False, 'version': 'v2.2'},
        'items': [item],
        'source_results': [item],
        'locators': [],
        'dense_candidate_trace': {'method': 'exact_dense_scan', 'scope_count': 1000, 'scope_cap': 50000, 'candidate_limit': 40, 'policy_version': 'dse-evidence-v2.2'},
        'channels': {'dense': 40, 'lexical': 40, 'exact': 20, 'graph': 0},
        'graph_trace': {'candidate_limit': 30, 'fetch_limit': 31, 'fetched_unique_candidates': 0, 'returned_candidates': 0, 'truncated': False},
        'reranker_trace': None,
    }


def test_case_contract_enforces_frozen_calibration_and_test_distribution():
    calibration = cases_for('calibration')
    test = cases_for('test')
    assert metrics.validate_cases(calibration, 'calibration')['counts']['supported'] == 60
    assert metrics.validate_cases(test, 'test')['counts']['insufficient'] == 180
    with pytest.raises(metrics.EvalContractError, match='distribution'):
        metrics.validate_cases(test[:-1], 'test')
    changed = list(test)
    changed[0] = {**changed[0], 'split': 'calibration'}
    with pytest.raises(metrics.EvalContractError, match='split'):
        metrics.validate_cases(changed, 'test')


@pytest.mark.parametrize('stage', ['calibration', 'test'])
def test_case_contract_enforces_each_positive_tier_language_quota(stage):
    cases = cases_for(stage)
    next_tier_index = 15 if stage == 'calibration' else 75
    cases[0] = {**cases[0], 'language': 'en'}
    cases[next_tier_index] = {**cases[next_tier_index], 'language': 'ko'}
    assert sum(case['language'] == 'ko' for case in cases) == (50 if stage == 'calibration' else 250)
    assert sum(case['language'] == 'en' for case in cases) == (50 if stage == 'calibration' else 250)
    with pytest.raises(metrics.EvalContractError, match='tier-language'):
        metrics.validate_cases(cases, stage)


@pytest.mark.parametrize('stage', ['calibration', 'test'])
def test_case_contract_reports_frozen_positive_tier_language_quotas(stage):
    result = metrics.validate_cases(cases_for(stage), stage)
    assert result['positive_tier_languages'] == metrics.POSITIVE_TIER_LANGUAGE_COUNTS[stage]


def test_missing_information_accepts_canonical_string_lists_without_mutation(tmp_path):
    cases = cases_for('calibration')
    supported = next(case for case in cases if case['answerability'] == 'supported')
    insufficient = next(case for case in cases if case['answerability'] == 'insufficient')
    supported['missing_information'] = []
    insufficient['missing_information'] = ['the requested release-specific measurement']
    original = copy.deepcopy(cases)

    summary = metrics.validate_cases(cases, 'calibration')
    assert summary['count'] == 100
    assert cases == original

    path = tmp_path / 'calibration-cases.jsonl'
    raw = b''.join(json.dumps(case, ensure_ascii=False).encode('utf-8') + b'\n' for case in cases)
    path.write_bytes(raw)
    parsed, digest, parsed_summary = runner._read_case_file(path, 'calibration')
    assert digest == hashlib.sha256(raw).hexdigest()
    assert parsed_summary == summary
    assert parsed == original
    assert isinstance(parsed[0]['missing_information'], list)
    assert path.read_bytes() == raw


def test_missing_information_rejects_non_string_list_members():
    cases = cases_for('calibration')
    cases[0]['missing_information'] = ['valid entry', 17]
    with pytest.raises(metrics.EvalContractError, match='missing_information'):
        metrics.validate_cases(cases, 'calibration')


def test_case_contract_rejects_cross_stage_intent_overlap():
    calibration = cases_for('calibration')
    test = cases_for('test')
    test[0] = {**test[0], 'intent_group': calibration[0]['intent_group']}
    with pytest.raises(metrics.EvalContractError, match='intent_group'):
        metrics.validate_split_isolation(calibration, test)


def test_case_contract_rejects_cross_stage_source_material_overlap():
    calibration = cases_for('calibration')
    test = cases_for('test')
    alt = test[0]['evidence_groups'][0]['alternatives'][0]
    test[0] = {**test[0], 'evidence_groups': [{**test[0]['evidence_groups'][0], 'alternatives': [{**alt, 'material_id': calibration[0]['evidence_groups'][0]['alternatives'][0]['material_id']}]}]}
    with pytest.raises(metrics.EvalContractError, match='source material'):
        metrics.validate_split_isolation(calibration, test)


def test_case_contract_rejects_cross_stage_case_id_overlap():
    calibration = cases_for('calibration')
    test = cases_for('test')
    test[0] = {**test[0], 'id': calibration[0]['id']}
    with pytest.raises(metrics.EvalContractError, match='case id'):
        metrics.validate_split_isolation(calibration, test)


def test_primary_score_uses_max_items_rank_score_not_response_order():
    result = response(0.1, items=[
        {'trace': {'rank_score': 0.1}},
        {'trace': {'rank_score': 0.7}},
        {'trace': {'rank_score': 0.4}},
    ])
    assert metrics.primary_score(result) == pytest.approx(0.7)
    assert metrics.primary_score(response(0.0, items=[])) == 0.0


def test_primary_score_selects_reranker_proxy_without_rrf_fallback():
    result = response(0.7, items=[
        {'trace': {'rank_score': 0.7, 'reranker_candidate_rank': 1, 'reranker_relevance_score': 0.2}},
        {'trace': {'rank_score': 0.4, 'reranker_candidate_rank': 2, 'reranker_relevance_score': 0.9}},
    ])
    assert metrics.primary_score(result, score_name='max_reranker_relevance_proxy') == pytest.approx(0.9)
    assert metrics.primary_score(response(0.0, items=[]), score_name='max_reranker_relevance_proxy') == 0.0
    with pytest.raises(metrics.EvalScoreError, match='no scored reranker candidates'):
        metrics.primary_score(response(0.7), score_name='max_reranker_relevance_proxy')
    for value in (-0.25, 1.01, float('nan'), float('inf'), True):
        with pytest.raises(metrics.EvalScoreError, match=r'\[0,1\]'):
            metrics.primary_score(
                response(0.7, items=[{'trace': {'rank_score': 0.7, 'reranker_candidate_rank': 1, 'reranker_relevance_score': value}}]),
                score_name='max_reranker_relevance_proxy',
            )


def test_reranker_proxy_uses_candidate_rank_marker_and_skips_unmarked_core_backfill():
    result = response(0.7, items=[
        {'role': 'core_technical', 'trace': {'rank_score': 0.9}},
        {'role': 'core_technical', 'trace': {'rank_score': 0.7, 'reranker_candidate_rank': 1, 'reranker_relevance_score': 0.63}},
        {'role': 'supporting_method', 'trace': {'rank_score': 0.6, 'reranker_candidate_rank': 2, 'reranker_relevance_score': 0.88}},
    ])
    assert metrics.primary_score(result, score_name='max_reranker_relevance_proxy') == pytest.approx(0.88)
    assert len(result['items']) == 3


def test_reranker_proxy_matches_actual_eleven_scored_and_one_unmarked_core_item():
    items = [
        {
            'role': 'core_technical',
            'trace': {
                'rank_score': 0.02 - index / 1000,
                'reranker_candidate_rank': index,
                'reranker_relevance_score': 0.91 - index / 100,
            },
        }
        for index in range(1, 12)
    ]
    items.append({'role': 'core_technical', 'trace': {'rank_score': 0.01}})
    result = response(0.02, items=items)
    assert metrics.primary_score(result, score_name='max_reranker_relevance_proxy') == pytest.approx(0.90)
    assert len(result['items']) == 12
    assert sum('reranker_candidate_rank' in item['trace'] for item in result['items']) == 11


def test_reranker_proxy_errors_when_nonempty_items_have_no_scored_candidate():
    result = response(0.7, items=[
        {'role': 'unclassified', 'trace': {'rank_score': 0.9}},
    ])
    with pytest.raises(metrics.EvalScoreError, match='no scored reranker candidates'):
        metrics.primary_score(result, score_name='max_reranker_relevance_proxy')


@pytest.mark.parametrize('items', [
    [{'role': 'core_technical', 'trace': {'rank_score': 0.7, 'reranker_candidate_rank': 3}}],
    [{'role': 'core_technical', 'trace': {'rank_score': 0.7, 'reranker_relevance_score': 0.6}}],
    [
        {'role': 'core_technical', 'trace': {'rank_score': 0.7, 'reranker_candidate_rank': 1, 'reranker_relevance_score': 0.6}},
        {'role': 'core_technical', 'trace': {'rank_score': 0.8, 'reranker_candidate_rank': 2}},
    ],
])
def test_reranker_proxy_errors_when_score_and_candidate_rank_are_incomplete(items):
    with pytest.raises(metrics.EvalScoreError, match='must be provided together'):
        metrics.primary_score(response(0.7, items=items), score_name='max_reranker_relevance_proxy')


@pytest.mark.parametrize('candidate_rank', [0, 41, 1.5, True])
def test_reranker_proxy_requires_candidate_rank_between_one_and_forty(candidate_rank):
    result = response(0.7, items=[{
        'role': 'core_technical',
        'trace': {'rank_score': 0.7, 'reranker_candidate_rank': candidate_rank, 'reranker_relevance_score': 0.6},
    }])
    with pytest.raises(metrics.EvalScoreError, match='integer in 1..40'):
        metrics.primary_score(result, score_name='max_reranker_relevance_proxy')


def test_jev_direct_support_proxy_uses_assessed_support_score_only():
    result = response(0.99)
    result['evidence_advice'] = evidence_advice(score=0.0)
    assert metrics.primary_score(result, score_name='jev_direct_support_proxy') == 0.0
    result['evidence_advice'] = evidence_advice(score=0.72)
    assert metrics.primary_score(result, score_name='jev_direct_support_proxy') == pytest.approx(0.72)


@pytest.mark.parametrize('status', ['disabled', 'unavailable', 'skipped_over_budget', 'skipped_prompt_budget'])
def test_jev_unassessed_cases_have_null_score_not_zero(status):
    result = response(0.99)
    result['evidence_advice'] = evidence_advice(status=status)
    assert metrics.primary_score(result, score_name='jev_direct_support_proxy') is None


def test_jev_unavailable_empty_advice_with_null_choice_is_a_valid_unassessed_result():
    raw = response(0.5)
    raw['evidence_advice'] = evidence_advice('unavailable', None)
    raw['evidence_advice']['choice'] = None

    projected = metrics.project_search_result(raw)

    assert projected['evidence_advice']['status'] == 'unavailable'
    assert projected['evidence_advice']['choice'] is None
    assert projected['evidence_advice']['support_score'] is None


def test_evidence_advice_unknown_error_code_is_replaced_before_public_projection():
    raw = response(0.5)
    advice = evidence_advice('unavailable', None, choice=None, metadata={
        'error_code': 'provider failed: api_key=private-sentinel',
    })
    raw['evidence_advice'] = advice

    projected = metrics.project_search_result(raw)['evidence_advice']

    assert projected['metadata']['error_code'] == 'advisor_error_unrecognized'
    assert 'api_key=private-sentinel' not in json.dumps(projected)

    for safe_code in ('timeout', 'advisor_error', 'evidence_advice_unavailable'):
        advice['metadata']['error_code'] = safe_code
        assert metrics.project_evidence_advice(advice)['metadata']['error_code'] == safe_code


def test_evidence_advice_normalized_usage_fields_are_preserved_as_numbers():
    raw = response(0.5)
    raw['evidence_advice'] = evidence_advice('assessed', 0.7, metadata={
        'usage': {'input_tokens': 23, 'cost_usd': 0.0042},
    })

    projected = metrics.project_search_result(raw)['evidence_advice']

    assert projected['metadata']['usage'] == {'input_tokens': 23, 'cost_usd': 0.0042}


@pytest.mark.parametrize('advice', [
    {**evidence_advice(), 'support_score': None},
    {**evidence_advice(), 'support_score': float('nan')},
    {**evidence_advice(), 'support_score': 1.01},
    {**evidence_advice('unavailable'), 'support_score': 0.0},
    {**evidence_advice(), 'schema_version': 'other'},
    {**evidence_advice(), 'choice': 'invented'},
])
def test_jev_direct_support_proxy_rejects_malformed_envelopes(advice):
    result = response(0.99)
    result['evidence_advice'] = advice
    with pytest.raises(metrics.EvalScoreError):
        metrics.primary_score(result, score_name='jev_direct_support_proxy')


def test_projection_keeps_rerank_provenance_but_strips_private_metadata():
    raw = response(0.7)
    raw['retrieval_mode'] = 'contextual_rerank'
    raw['reranker_trace'] = {
        'provider': 'deepinfra', 'model': 'Qwen/Qwen3-Reranker-4B', 'http_status': 200,
        'latency_seconds': 2.922, 'input_tokens': 36206,
        'inference_status': {
            'runtime_ms': 1802, 'tokens_input': 36206, 'cost': 0.0009051500000000001,
            'raw_response': 'must not appear', 'api_key': 'must not appear',
        },
        'cost_is_estimate': True,
        'score_semantics': 'relevance_not_answerability', 'candidate_count': 40,
        'api_key': 'must not appear', 'raw_request': 'must not appear',
    }
    raw['items'][0]['trace'].update({
        'original_rrf_score': 0.7, 'reranker_relevance_score': 0.93,
        'reranker_candidate_rank': 1,
        'channel_ranks': {'context_dense': 1, 'context_bm25': 2, 'graph': 3, 'secret_channel': 4},
    })
    raw['items'][0]['scores'].update({'context_dense': 0.02, 'context_bm25': 0.01, 'secret_score': 9.0})
    raw['channels'] = {'context_dense': 40, 'context_bm25': 40, 'exact': 20, 'graph': 0, 'secret_channel': 99}
    projected = metrics.project_search_result(raw)
    assert projected['retrieval_mode'] == 'contextual_rerank'
    assert projected['items'][0]['trace']['original_rrf_score'] == pytest.approx(0.7)
    assert projected['items'][0]['trace']['reranker_relevance_score'] == pytest.approx(0.93)
    assert projected['items'][0]['trace']['reranker_candidate_rank'] == 1
    assert projected['reranker_trace'] == {
        'provider': 'deepinfra', 'model': 'Qwen/Qwen3-Reranker-4B', 'http_status': 200,
        'latency_seconds': 2.922, 'input_tokens': 36206,
        'inference_status': {'runtime_ms': 1802, 'tokens_input': 36206, 'cost': 0.0009051500000000001},
        'cost_is_estimate': True,
        'score_semantics': 'relevance_not_answerability', 'candidate_count': 40,
    }
    assert projected['channels'] == {'context_dense': 40, 'context_bm25': 40, 'exact': 20, 'graph': 0}
    assert projected['items'][0]['scores'] == {'dense': 1 / 61, 'lexical': 1 / 62, 'context_dense': 0.02, 'context_bm25': 0.01}
    assert projected['items'][0]['trace']['channel_ranks'] == {'context_dense': 1, 'context_bm25': 2, 'graph': 3}
    serialized = json.dumps(projected)
    assert 'api_key' not in serialized and 'raw_request' not in serialized
    assert 'raw_response' not in serialized and 'secret_channel' not in serialized and 'secret_score' not in serialized
    assert 'must not appear' not in serialized


@pytest.mark.parametrize('status', [
    'ok',
    {'runtime_ms': -1, 'tokens_input': 4, 'cost': 0.1},
    {'runtime_ms': 1, 'tokens_input': -4, 'cost': 0.1},
    {'runtime_ms': 1, 'tokens_input': 4, 'cost': float('nan')},
    {'runtime_ms': 1, 'tokens_input': 4, 'cost': True},
    {'runtime_ms': True, 'tokens_input': 4, 'cost': 0.1},
    {'runtime_ms': 1, 'tokens_input': 4.5, 'cost': 0.1},
])
def test_projection_rejects_malformed_nested_reranker_inference_status(status):
    raw = response(0.7)
    raw['reranker_trace'] = {'inference_status': status}
    with pytest.raises(metrics.EvalScoreError, match='inference_status'):
        metrics.project_search_result(raw)


def test_jev_advice_projection_keeps_bounded_metadata_and_drops_private_payload():
    raw = response(0.99)
    raw['evidence_advice'] = evidence_advice(
        projection={
            'total_evidence': 2, 'selected_evidence': 1, 'omitted_evidence': 1,
            'truncated_evidence': 1, 'state_bytes': 1200, 'request_bytes': 1500,
            'excerpt_only': True,
            'items': [{
                'chunk_id': 'chunk-1', 'revision_id': 'revision-1',
                'source_text_bytes': 4000, 'excerpt_text_bytes': 600, 'truncated': True,
                'text': 'private source excerpt', 'quote': 'private quote',
            }],
            'raw_excerpt': 'private source excerpt',
        },
        metadata={
            'provider': 'decision_models', 'model_selected': 'typesafe/jev-1.13',
            'model_reported': 'typesafe/jev-1.13', 'request_id': 'request-safe-id',
            'latency_ms': 25.5, 'cache_hit': False, 'error_code': None,
            'request_state_sha256': 'a' * 64, 'request_sha256': 'b' * 64,
            'input_sha256': 'c' * 64, 'provider_calls': 1,
            'usage': {'input_tokens': 100, 'output_tokens': 12, 'total_tokens': 112,
                      'estimated_cost': 0.001, 'inputTokens': 554,
                      'costUsd': 0.000023268, 'raw_body': 'must not appear'},
            'prompt': 'must not appear', 'raw_response': 'must not appear',
        },
    )

    projected = metrics.project_search_result(raw)

    assert projected['evidence_advice'] == {
        'schema_version': 'jev-evidence-advice/v1',
        'status': 'assessed', 'advisory_only': True,
        'choice': 'direct_support_candidate', 'support_score': 0.75,
        'score_kind': 'uncalibrated_direct_support_probability',
        'policy_version': 'jev-evidence-advice/v1', 'evidence_ids': ['chunk-1'],
        'projection': {
            'total_evidence': 2, 'selected_evidence': 1, 'omitted_evidence': 1,
            'truncated_evidence': 1, 'state_bytes': 1200, 'request_bytes': 1500,
            'excerpt_only': True,
            'items': [{'chunk_id': 'chunk-1', 'revision_id': 'revision-1',
                       'source_text_bytes': 4000, 'excerpt_text_bytes': 600, 'truncated': True}],
        },
        'metadata': {
            'provider': 'decision_models', 'model_selected': 'typesafe/jev-1.13',
            'model_reported': 'typesafe/jev-1.13', 'request_id': 'request-safe-id',
            'latency_ms': 25.5, 'cache_hit': False, 'error_code': None,
            'request_state_sha256': 'a' * 64, 'request_sha256': 'b' * 64,
            'input_sha256': 'c' * 64, 'provider_calls': 1,
                'usage': {'input_tokens': 100, 'output_tokens': 12, 'total_tokens': 112,
                          'estimated_cost': 0.001, 'inputTokens': 554,
                          'costUsd': 0.000023268},
        },
    }
    serialized = json.dumps(projected)
    for forbidden in ('private source excerpt', 'private quote', 'raw_body', 'raw_response', 'must not appear', 'prompt'):
        assert forbidden not in serialized


def test_unassessed_jev_case_keeps_search_result_and_ranking_but_has_null_score():
    case = next(case for case in cases_for('calibration') if case['answerability'] == 'supported')
    record = runner._case_result_record(
        case, index=0, response_body=jev_search_response(None, status='unavailable'),
        error=None, latency=0.1, retrieval_mode='contextual_rerank',
        evidence_advice='jev', score_name='jev_direct_support_proxy',
    )

    assert record['status'] == 'error'
    assert record['error_type'] == 'advisor_unavailable'
    assert record['score'] is None
    assert record['result']['evidence_advice']['status'] == 'unavailable'
    assert record['ranking']['items']['source_any_hit_at_5'] == 0


def test_malformed_jev_advice_preserves_valid_search_projection_and_ranking():
    case = next(case for case in cases_for('calibration') if case['answerability'] == 'supported')
    case['evidence_groups'][0]['alternatives'] = [{
        'material_id': 'material-1', 'revision_id': 'revision-1', 'chunk_id': 'chunk-1',
    }]
    body = response(0.8)
    body['evidence_advice'] = evidence_advice(score=1.2)

    record = runner._case_result_record(
        case, index=0, response_body=body, error=None, latency=0.1,
        evidence_advice='jev', score_name='jev_direct_support_proxy',
    )

    assert record['status'] == 'error'
    assert record['error_type'] == 'advisor_invalid_advice'
    assert record['score'] is None
    assert [item['chunk_id'] for item in record['result']['items']] == ['chunk-1']
    assert 'evidence_advice' not in record['result']
    assert record['ranking']['items']['source_any_hit_at_1'] == 1
    assert record['ranking']['source_results']['source_any_hit_at_1'] == 1
    assert 'must not appear in public output' not in json.dumps(record)


def test_jev_summary_keeps_full_denominators_and_fails_quality_gate_on_any_unassessed_case():
    cases = cases_for('calibration')
    records = []
    unassessed_id = cases[0]['id']
    for index, case in enumerate(cases):
        if case['answerability'] == 'supported':
            score, choice = 0.9, 'direct_support_candidate'
        elif case['answerability'] == 'insufficient':
            score, choice = 0.1, 'no_support'
        else:
            score, choice = 0.5, 'uncertain'
        status = 'unavailable' if case['id'] == unassessed_id else 'assessed'
        record = runner._case_result_record(
            case, index=index, response_body=jev_search_response(score if status == 'assessed' else None,
                                                                  status=status, choice=choice),
            error=None, latency=0.01, retrieval_mode='contextual_rerank',
            evidence_advice='jev', score_name='jev_direct_support_proxy',
        )
        records.append(record)

    report = runner._summary_from_records(
        'calibration', cases, records, {'threshold': 0.5}, bootstrap_replicates=10,
        retrieval_mode='contextual_rerank', score_name='jev_direct_support_proxy',
        evidence_advice='jev',
    )

    assert report['case_count'] == report['recorded_case_count'] == 100
    assert report['error_count'] == 1 and report['execution_gate_passed'] is False
    assert report['evidence_advice']['assessed_count'] == 99
    assert report['evidence_advice']['unassessed_count'] == 1
    assert report['score_metrics']['binary_denominator'] == 96
    assert report['score_metrics']['valid_assessed_semantic_denominator'] == 95
    assert report['score_metrics']['ambiguous_excluded_from_binary'] == 4
    assert report['case_results'][0]['score'] is None
    assert report['case_results'][0]['result']['items']
    assert report['development_metrics']['quality_gates']['passed'] is False
    assert report['actual_action'] == 'not_evaluated'


def test_public_case_contract_is_preferred_and_private_legacy_is_fallback(tmp_path, monkeypatch):
    root = tmp_path / 'fixture-repo'
    script_dir = root / 'scripts'
    public_contract = root / 'research' / 'eval500' / 'case-contract-v1.json'
    legacy_contract = root / '.superpowers' / 'sdd' / 'eval500' / 'case-contract.json'
    script_dir.mkdir(parents=True)
    public_contract.parent.mkdir(parents=True)
    legacy_contract.parent.mkdir(parents=True)
    public_contract.write_bytes(b'{"contract":"public"}\n')
    legacy_contract.write_bytes(b'{"contract":"private-legacy"}\n')
    monkeypatch.setattr(runner, '__file__', str(script_dir / 'evaluate-retrieval-confidence.py'))
    assert runner._case_contract_sha256() == hashlib.sha256(public_contract.read_bytes()).hexdigest()
    public_contract.unlink()
    assert runner._case_contract_sha256() == hashlib.sha256(legacy_contract.read_bytes()).hexdigest()


def test_reranker_proxy_calibration_identity_includes_mode_and_score_name(tmp_path):
    cases = cases_for('calibration')
    cases_path = tmp_path / 'calibration.jsonl'
    write_cases(cases_path, cases)
    threshold_path = tmp_path / 'threshold.json'
    journal_path = tmp_path / 'journal.jsonl'
    score_by_query = {
        case['query']: (0.8 if case['answerability'] == 'supported' else 0.2)
        for case in cases
    }

    class RerankTransport:
        def __init__(self):
            self.requests = []

        def post_search(self, payload):
            self.requests.append(dict(payload))
            result = response(0.1)
            result['retrieval_mode'] = payload['retrieval_mode']
            result['items'][0]['trace']['reranker_relevance_score'] = score_by_query[payload['query']]
            result['items'][0]['trace']['reranker_candidate_rank'] = 1
            result['items'][0]['trace']['original_rrf_score'] = result['items'][0]['trace']['rank_score']
            result['reranker_trace'] = {
                'score_semantics': 'relevance_not_answerability', 'candidate_count': 1,
            }
            return result

    transport = RerankTransport()
    report = runner.run_stage(
        stage='calibration', cases_path=cases_path, journal_path=journal_path,
        corpus_manifest_sha256='a' * 64, threshold_path=threshold_path,
        transport=transport, retrieval_mode='contextual_rerank',
        score_name='max_reranker_relevance_proxy',
    )
    header = json.loads(journal_path.read_text().splitlines()[0])
    threshold = json.loads(threshold_path.read_text())
    assert report['retrieval_mode'] == header['retrieval_mode'] == threshold['retrieval_mode'] == 'contextual_rerank'
    assert report['score_name'] == header['score_name'] == threshold['score_name'] == 'max_reranker_relevance_proxy'
    assert transport.requests[0]['retrieval_mode'] == 'contextual_rerank'
    assert report['threshold']['threshold'] == pytest.approx(0.8)
    assert '[0,1]' in threshold['score_definition']
    assert 'items with neither candidate rank nor reranker score are skipped as unscored backfill' in threshold['score_definition']
    assert all(row['score'] in {0.2, 0.8} for row in report['case_results'])

    request_count = len(transport.requests)
    with pytest.raises(runner.EvaluationRunError, match='journal_identity_mismatch'):
        runner.run_stage(
            stage='calibration', cases_path=cases_path, journal_path=journal_path,
            corpus_manifest_sha256='a' * 64, threshold_path=threshold_path,
            transport=transport, retrieval_mode='rerank',
            score_name='max_reranker_relevance_proxy', resume=True,
        )
    assert len(transport.requests) == request_count

    with pytest.raises(runner.EvaluationRunError, match='threshold_identity_mismatch'):
        runner._threshold_policy(
            threshold_path, 'a' * 64, runner._case_contract_sha256(),
            retrieval_mode='rerank', score_name='max_reranker_relevance_proxy',
        )
    with pytest.raises(runner.EvaluationRunError, match='threshold_identity_mismatch'):
        runner._threshold_policy(
            threshold_path, 'a' * 64, runner._case_contract_sha256(),
            retrieval_mode='contextual_rerank', score_name='max_technical_rrf_proxy',
        )
    for invalid_threshold in (-0.01, 1.01):
        invalid_path = tmp_path / f'invalid-threshold-{invalid_threshold}.json'
        runner._write_private_json_no_overwrite(
            invalid_path, {**threshold, 'threshold': invalid_threshold},
        )
        with pytest.raises(runner.EvaluationRunError, match='threshold_identity_mismatch'):
            runner._threshold_policy(
                invalid_path, 'a' * 64, runner._case_contract_sha256(),
                retrieval_mode='contextual_rerank', score_name='max_reranker_relevance_proxy',
            )


def test_jev_calibration_binds_advice_mode_and_score_to_request_journal_and_threshold(tmp_path):
    cases = cases_for('calibration')
    cases_path = tmp_path / 'calibration.jsonl'
    write_cases(cases_path, cases)
    threshold_path = tmp_path / 'jev-threshold.json'
    journal_path = tmp_path / 'jev.journal.jsonl'
    score_by_query = {
        case['query']: (0.8 if case['answerability'] == 'supported' else 0.2)
        for case in cases
    }

    class JevTransport:
        def __init__(self):
            self.requests = []

        def post_search(self, payload):
            self.requests.append(dict(payload))
            score = score_by_query[payload['query']]
            choice = 'direct_support_candidate' if score == 0.8 else 'no_support'
            return jev_search_response(score, choice=choice)

    transport = JevTransport()
    report = runner.run_stage(
        stage='calibration', cases_path=cases_path, journal_path=journal_path,
        corpus_manifest_sha256='a' * 64, threshold_path=threshold_path,
        transport=transport, retrieval_mode='contextual_rerank',
        evidence_advice='jev', score_name='jev_direct_support_proxy',
    )
    header = json.loads(journal_path.read_text().splitlines()[0])
    threshold = json.loads(threshold_path.read_text())
    assert report['evidence_advice']['mode'] == 'jev'
    assert header['evidence_advice'] == threshold['evidence_advice'] == 'jev'
    assert header['score_name'] == threshold['score_name'] == 'jev_direct_support_proxy'
    assert transport.requests[0]['evidence_advice'] == 'jev'
    assert threshold['threshold'] == pytest.approx(0.8)
    assert report['actual_action'] == 'not_evaluated'

    with pytest.raises(runner.EvaluationRunError, match='threshold_identity_mismatch'):
        runner._threshold_policy(
            threshold_path, 'a' * 64, runner._case_contract_sha256(),
            retrieval_mode='contextual_rerank', score_name='jev_direct_support_proxy',
            evidence_advice='off',
        )

    request_count = len(transport.requests)
    with pytest.raises(runner.EvaluationRunError, match='journal_identity_mismatch'):
        runner.run_stage(
            stage='calibration', cases_path=cases_path, journal_path=journal_path,
            corpus_manifest_sha256='a' * 64, threshold_path=threshold_path,
            transport=transport, retrieval_mode='contextual_rerank',
            evidence_advice='off', score_name='max_technical_rrf_proxy', resume=True,
        )
    assert len(transport.requests) == request_count


def test_pre_jev_off_threshold_artifact_remains_readable(tmp_path):
    path = tmp_path / 'legacy-off-threshold.json'
    policy = {
        'schema_version': runner.THRESHOLD_SCHEMA_VERSION,
        'stage': 'calibration_frozen_threshold',
        'runner_version': runner.RUNNER_VERSION,
        'runtime_version_status': runner.RUNTIME_VERSION_STATUS,
        'retrieval_mode': 'baseline',
        'score_name': metrics.SCORE_NAME,
        'probability': False,
        'threshold': 0.5,
        'target_supported_tpr': 0.90,
        'comparison': '>=',
        'policy_version': POLICY,
        'request': {
            'category': '', 'limit': 12, 'purpose': 'auto',
            'retrieval_mode': 'baseline',
        },
        'corpus_manifest_sha256': 'a' * 64,
        'case_contract_sha256': runner._case_contract_sha256(),
        'calibration_case_manifest_sha256': 'b' * 64,
        'calibration_case_id_sha256': ['c' * 64],
        'calibration_intent_group_sha256': ['d' * 64],
        'calibration_source_material_sha256': ['e' * 64],
    }
    runner._write_private_json_no_overwrite(path, policy)

    loaded, digest = runner._threshold_policy(
        path, 'a' * 64, runner._case_contract_sha256(),
        retrieval_mode='baseline', score_name=metrics.SCORE_NAME,
        evidence_advice='off',
    )

    assert loaded == policy
    assert len(digest) == 64


def test_published_contextual_rerank_threshold_accepts_legacy_off_request_shape(tmp_path):
    public_summary = json.loads(
        (ROOT / 'research/eval500/results/contextual-rerank-8b-calibration-input-summary.json').read_text()
    )
    threshold = public_summary['threshold']
    assert threshold['retrieval_mode'] == 'contextual_rerank'
    assert threshold['score_name'] == 'max_reranker_relevance_proxy'
    assert 'evidence_advice' not in threshold
    assert 'evidence_advice' not in threshold['request']
    threshold_path = tmp_path / 'published-v1-threshold.json'
    runner._write_private_json_no_overwrite(threshold_path, threshold)

    loaded, digest = runner._threshold_policy(
        threshold_path, threshold['corpus_manifest_sha256'], threshold['case_contract_sha256'],
        retrieval_mode='contextual_rerank', score_name='max_reranker_relevance_proxy',
        evidence_advice='off',
    )

    assert loaded['request'] == threshold['request']
    assert len(digest) == 64


@pytest.mark.parametrize('items', [
    [{'trace': {}}],
    [{'trace': {'rank_score': float('nan')}}],
    [{'trace': {'rank_score': float('inf')}}],
    [{'trace': {'rank_score': True}}],
    [{'trace': {'rank_score': -0.1}}],
])
def test_primary_score_fails_on_missing_or_malformed_nonempty_items(items):
    with pytest.raises(metrics.EvalScoreError):
        metrics.primary_score(response(0.1, items=items))


def test_captured_canary_metadata_with_null_graph_rank_reaches_case_record_projection():
    case = next(case for case in cases_for('calibration') if case['answerability'] == 'supported')
    raw = json.dumps(captured_canary_metadata_result()).encode('utf-8')
    fake_response = FakeResponse(raw, headers={'Content-Length': str(len(raw))})
    transport = runner.HTTPTransport(
        'http://127.0.0.1:8080',
        urlopen=lambda _request, timeout: fake_response,
        sleep_fn=lambda _delay: None,
    )
    search_response = transport.post_search({
        'query': case['query'], 'category': '', 'limit': 12, 'purpose': 'auto',
    })
    response_body, http_status, attempts, response_bytes = runner._response_parts(search_response)
    record = runner._case_result_record(
        case, index=0, response_body=response_body, error=None, latency=0.01,
    )
    assert record['status'] == 'ok'
    assert record['error_type'] is None
    assert http_status == record['http_status'] == 200
    assert attempts == 1 and response_bytes == len(raw) == fake_response.read_bytes
    assert record['score'] == pytest.approx(0.021898263027295285)
    assert record['result']['channels'] == {'dense': 40, 'lexical': 40, 'exact': 20, 'graph': 0}
    assert record['result']['items'][0]['trace']['graph_rank'] is None
    serialized = json.dumps(record)
    for forbidden in ('source text', 'claim_contexts', 'neighbor_evidence', 'query_embedding_usage', 'retrieval_policy'):
        assert forbidden not in serialized


def test_captured_canary_metadata_still_rejects_malformed_non_null_graph_rank():
    with pytest.raises(metrics.EvalScoreError, match='trace.graph_rank'):
        metrics.project_search_result(captured_canary_metadata_result(graph_rank='not-a-number'))


def test_threshold_uses_largest_calibration_cutoff_meeting_tpr_with_ties_included():
    records = [
        {'score': 0.9, 'answerability': 'supported'},
        {'score': 0.8, 'answerability': 'supported'},
        {'score': 0.8, 'answerability': 'supported'},
        {'score': 0.6, 'answerability': 'supported'},
        {'score': 0.8, 'answerability': 'insufficient'},
        {'score': 0.2, 'answerability': 'insufficient'},
    ]
    selected = metrics.select_threshold(records, target_tpr=0.9)
    assert selected['threshold'] == pytest.approx(0.6)
    assert selected['supported_tpr'] == 1.0
    assert selected['comparison'] == '>='


def test_roc_auc_and_average_precision_handle_score_ties_as_groups():
    records = [
        {'score': 1.0, 'answerability': 'supported'},
        {'score': 0.0, 'answerability': 'supported'},
        {'score': 0.0, 'answerability': 'insufficient'},
        {'score': 0.0, 'answerability': 'insufficient'},
    ]
    assert metrics.roc_auc(records) == pytest.approx(0.75)
    tied = [
        {'score': 0.5, 'answerability': 'supported'},
        {'score': 0.5, 'answerability': 'insufficient'},
    ]
    assert metrics.average_precision(tied) == pytest.approx(0.5)


def test_intent_cluster_bootstrap_is_deterministic():
    records = []
    for group in range(8):
        records.extend([
            {'intent_group': f'g{group}', 'answerability': 'supported', 'score': 0.8},
            {'intent_group': f'g{group}', 'answerability': 'insufficient', 'score': 0.2},
        ])
    first = metrics.intent_cluster_bootstrap(records, replicates=50, seed=500, source_material_count=0)
    second = metrics.intent_cluster_bootstrap(records, replicates=50, seed=500, source_material_count=0)
    assert first == second
    assert first['intent_group_count'] == 8
    assert first['source_material_group_count'] == 0
    assert first['ci_grouping'] == 'intent_group_only'
    assert first['does_not_cover_source_correlations'] is True
    assert first['valid_replicates'] == 50
    assert first['intervals']['roc_auc'] == {'lower_95': 1.0, 'upper_95': 1.0}


def test_intent_bootstrap_reports_distinct_source_material_count_without_claiming_source_ci():
    records = [
        {'intent_group': 'intent-a', 'answerability': 'supported', 'score': 0.8},
        {'intent_group': 'intent-a', 'answerability': 'insufficient', 'score': 0.2},
        {'intent_group': 'intent-b', 'answerability': 'supported', 'score': 0.9},
        {'intent_group': 'intent-b', 'answerability': 'insufficient', 'score': 0.1},
    ]
    result = metrics.intent_cluster_bootstrap(records, replicates=20, seed=500, source_material_count=3)
    assert result['intent_group_count'] == 2
    assert result['source_material_group_count'] == 3
    assert result['ci_grouping'] == 'intent_group_only'
    assert result['does_not_cover_source_correlations'] is True


def test_ranking_metrics_apply_or_within_evidence_group_and_and_across_groups():
    case = cases_for('calibration')[0]
    case['evidence_groups'] = [
        {'group_id': 'g1', 'requirement': 'one', 'answer_fact': 'one', 'alternatives': [
            {'material_id': 'a', 'revision_id': 'ra', 'chunk_id': 'a1', 'source_url': 'https://x.invalid/a', 'text_sha256': 'a' * 64},
            {'material_id': 'a2', 'revision_id': 'ra2', 'chunk_id': 'a2', 'source_url': 'https://x.invalid/a2', 'text_sha256': 'b' * 64},
        ]},
        {'group_id': 'g2', 'requirement': 'two', 'answer_fact': 'two', 'alternatives': [
            {'material_id': 'b', 'revision_id': 'rb', 'chunk_id': 'b1', 'source_url': 'https://x.invalid/b', 'text_sha256': 'c' * 64},
        ]},
    ]
    wrong_revision = {'material_id': 'a', 'revision_id': 'old', 'chunk_id': 'old-a', 'role': 'core_technical'}
    first_alt = {'material_id': 'a2', 'revision_id': 'ra2', 'chunk_id': 'a2', 'role': 'core_technical'}
    second_group = {'material_id': 'b', 'revision_id': 'rb', 'chunk_id': 'b1', 'role': 'core_technical'}
    result = response(0.9, items=[wrong_revision, first_alt, second_group], source_results=[wrong_revision, first_alt, second_group])
    metrics_result = metrics.ranking_metrics(case, result, stream='items', limit=12)
    assert metrics_result['source_any_hit_at_1'] == 0
    assert metrics_result['source_any_hit_at_5'] == 1
    assert metrics_result['source_all_groups_hit_at_5'] == 1
    assert metrics_result['chunk_any_hit_at_5'] == 1
    assert metrics_result['chunk_all_groups_hit_at_5'] == 1
    assert metrics_result['source_mrr_at_5'] == pytest.approx(0.5)
    assert metrics_result['chunk_mrr_at_10'] == pytest.approx(0.5)


def test_result_projection_keeps_only_bounded_metadata_and_raw_slots():
    item = response(0.4)['items'][0]
    projected = metrics.project_search_result(response(0.4, items=[item]), limit=12)
    assert projected['items'][0]['slot'] == 1
    assert projected['items'][0]['chunk_id'] == 'chunk-1'
    assert projected['items'][0]['trace']['rank_score'] == pytest.approx(0.4)
    assert projected['actual_confidence'] == 'not_provided'
    assert projected['actual_action'] == 'not_evaluated'
    assert projected['actual_abstention'] == 'not_evaluated'
    assert projected['threshold_is_proxy_only'] is True
    serialized = json.dumps(projected)
    for forbidden in ('must not appear', 'private title', 'example.invalid/private', 'query_embedding_usage', 'expected_chunks', 'gold_rationale'):
        assert forbidden not in serialized
    assert projected['source_results'][0]['slot'] == 1
    assert projected['policy_version'] == POLICY
    assert projected['actual_confidence'] == 'not_provided'
    assert projected['actual_action'] == projected['actual_abstention'] == 'not_evaluated'


class FakeResponse:
    def __init__(self, body, status=200, headers=None):
        self.body = body
        self.status = status
        self.headers = headers or {}
        self.read_bytes = 0

    def read(self, size=-1):
        if size < 0:
            size = len(self.body)
        self.read_bytes += min(size, len(self.body))
        return self.body[:size]

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def test_http_transport_timeout_bounded_retry_and_clipped_retry_after():
    calls = []
    sleeps = []
    payload = json.dumps(response(0.5)).encode()
    response_body = FakeResponse(payload, headers={'Content-Length': str(len(payload))})

    def urlopen(request, timeout):
        calls.append((request, timeout))
        if len(calls) == 1:
            raise HTTPError(request.full_url, 429, 'busy', {'Retry-After': '120'}, None)
        return response_body

    transport = runner.HTTPTransport('http://127.0.0.1:8080', urlopen=urlopen, sleep_fn=sleeps.append)
    parsed = transport.post_search({'query': 'synthetic', 'category': '', 'limit': 12, 'purpose': 'auto'})
    assert parsed.payload['policy_version'] == POLICY
    assert len(calls) == 2
    assert all(timeout == 60 for _, timeout in calls)
    assert sleeps == [30.0]
    sent = json.loads(calls[0][0].data)
    assert set(sent) == {'query', 'category', 'limit', 'purpose'}
    assert runner.MAX_HTTP_ATTEMPTS == 3
    assert runner.MAX_RESPONSE_BYTES + 1 <= 3_000_000


def test_http_transport_sends_explicit_retrieval_mode_and_rejects_unknown_mode():
    calls = []
    payload_bytes = json.dumps(response(0.5)).encode()
    fake_response = FakeResponse(payload_bytes, headers={'Content-Length': str(len(payload_bytes))})
    transport = runner.HTTPTransport(
        'http://127.0.0.1:8080',
        urlopen=lambda request, timeout: calls.append((request, timeout)) or fake_response,
        sleep_fn=lambda _delay: None,
    )
    transport.post_search({
        'query': 'synthetic', 'category': '', 'limit': 12, 'purpose': 'auto',
        'retrieval_mode': 'contextual_rerank',
    })
    assert json.loads(calls[0][0].data)['retrieval_mode'] == 'contextual_rerank'
    assert calls[0][1] == runner.HTTP_TIMEOUT_SECONDS
    with pytest.raises(runner.SearchRequestError, match='invalid_request_retrieval_mode'):
        transport.post_search({
            'query': 'synthetic', 'category': '', 'limit': 12, 'purpose': 'auto',
            'retrieval_mode': 'unvalidated-mode',
        })


def test_http_transport_sends_evidence_advice_and_rejects_unknown_setting():
    calls = []
    payload_bytes = json.dumps(response(0.5)).encode()
    fake_response = FakeResponse(payload_bytes, headers={'Content-Length': str(len(payload_bytes))})
    transport = runner.HTTPTransport(
        'http://127.0.0.1:8080',
        urlopen=lambda request, timeout: calls.append((request, timeout)) or fake_response,
        sleep_fn=lambda _delay: None,
    )
    transport.post_search({
        'query': 'synthetic', 'category': '', 'limit': 12, 'purpose': 'auto',
        'retrieval_mode': 'contextual_rerank', 'evidence_advice': 'jev',
    })
    assert json.loads(calls[0][0].data)['evidence_advice'] == 'jev'
    assert calls[0][1] == 180
    with pytest.raises(runner.SearchRequestError, match='invalid_request_evidence_advice'):
        transport.post_search({
            'query': 'synthetic', 'category': '', 'limit': 12, 'purpose': 'auto',
            'retrieval_mode': 'contextual_rerank', 'evidence_advice': 'invented',
        })


def test_http_transport_does_not_retry_jev_requests_and_uses_advisor_timeout_window():
    calls = []
    sleeps = []

    def urlopen(request, timeout):
        calls.append((request, timeout))
        raise HTTPError(request.full_url, 429, 'busy', {'Retry-After': '1'}, None)

    transport = runner.HTTPTransport(
        'http://127.0.0.1:8080', urlopen=urlopen, sleep_fn=sleeps.append,
    )
    with pytest.raises(runner.SearchRequestError, match='http_429') as error:
        transport.post_search({
            'query': 'synthetic', 'category': '', 'limit': 12, 'purpose': 'auto',
            'retrieval_mode': 'contextual_rerank', 'evidence_advice': 'jev',
        })

    assert error.value.attempts == 1
    assert len(calls) == 1
    assert calls[0][1] >= 180
    assert sleeps == []


def test_http_transport_fails_without_reading_oversize_body_or_leaking_it():
    huge = FakeResponse(b'x' * (runner.MAX_RESPONSE_BYTES + 1), headers={})
    sleeps = []
    transport = runner.HTTPTransport(
        'http://127.0.0.1:8080', urlopen=lambda *_a, **_k: huge,
        sleep_fn=sleeps.append,
    )
    with pytest.raises(runner.SearchRequestError) as error:
        transport.post_search({'query': 'synthetic', 'category': '', 'limit': 12, 'purpose': 'auto'})
    assert error.value.code == 'response_too_large'
    assert huge.read_bytes <= runner.MAX_RESPONSE_BYTES + 1
    assert not hasattr(error.value, 'body')
    assert sleeps == []


class FakeTransport:
    def __init__(self, scores=None, errors=None, delay=0.0):
        self.scores = scores or {}
        self.errors = errors or {}
        self.delay = delay
        self.requests = []
        self.lock = threading.Lock()
        self.active = 0
        self.max_active = 0

    def post_search(self, payload):
        assert set(payload) == {'query', 'category', 'limit', 'purpose', 'retrieval_mode', 'evidence_advice'}
        assert payload['category'] == '' and payload['limit'] == 12 and payload['purpose'] == 'auto'
        assert payload['retrieval_mode'] in metrics.RETRIEVAL_MODES
        assert payload['evidence_advice'] in {'off', 'jev'}
        with self.lock:
            self.requests.append(dict(payload))
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            if self.delay:
                time.sleep(self.delay)
            query = payload['query']
            if query in self.errors:
                raise runner.SearchRequestError(self.errors[query], http_status=503)
            score = self.scores.get(query, 0.1)
            result = response(score)
            result['retrieval_mode'] = payload['retrieval_mode']
            return result
        finally:
            with self.lock:
                self.active -= 1


def write_cases(path, cases):
    path.write_text(''.join(json.dumps(case, ensure_ascii=False) + '\n' for case in cases))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_calibration_then_test_is_resumable_threshold_frozen_and_group_disjoint(tmp_path):
    calibration_cases = cases_for('calibration')
    calibration_path = tmp_path / 'calibration.jsonl'
    calibration_hash = write_cases(calibration_path, calibration_cases)
    corpus_hash = 'a' * 64
    scores = {
        case['query']: (0.9 if case['answerability'] == 'supported' else (0.2 if case['answerability'] == 'insufficient' else 0.5))
        for case in calibration_cases
    }
    calibration_transport = FakeTransport(scores, delay=0.001)
    calibration_journal = tmp_path / 'calibration.journal.jsonl'
    threshold_path = tmp_path / 'threshold.json'
    calibration = runner.run_stage(
        stage='calibration', cases_path=calibration_path, journal_path=calibration_journal,
        corpus_manifest_sha256=corpus_hash, base_url='http://127.0.0.1:8080',
        threshold_path=threshold_path, transport=calibration_transport,
    )
    assert calibration['status'] == 'complete'
    assert calibration['execution_gate_passed'] is True
    assert calibration_transport.max_active == 2
    assert calibration['threshold']['threshold'] == pytest.approx(0.9)
    assert calibration['threshold']['calibration_case_id_sha256'] == metrics.case_id_hashes(calibration_cases)
    assert set(calibration_transport.requests[0]) == {'query', 'category', 'limit', 'purpose', 'retrieval_mode', 'evidence_advice'}
    assert calibration_transport.requests[0]['evidence_advice'] == 'off'
    assert all((path.stat().st_mode & 0o777) == 0o600 for path in (calibration_journal, threshold_path))

    request_count = len(calibration_transport.requests)
    with calibration_journal.open('ab') as journal_file:
        journal_file.write(b'{"event":"partial')
    resumed = runner.run_stage(
        stage='calibration', cases_path=calibration_path, journal_path=calibration_journal,
        corpus_manifest_sha256=corpus_hash, base_url='http://127.0.0.1:8080',
        threshold_path=threshold_path, transport=calibration_transport, resume=True,
    )
    assert len(calibration_transport.requests) == request_count
    assert resumed['threshold']['threshold'] == calibration['threshold']['threshold']
    assert calibration_journal.read_bytes().endswith(b'\n')

    test_cases = cases_for('test')
    test_path = tmp_path / 'test.jsonl'
    write_cases(test_path, test_cases)
    test_scores = {
        case['query']: (0.95 if case['answerability'] == 'supported' else (0.1 if case['answerability'] == 'insufficient' else 0.5))
        for case in test_cases
    }
    test_transport = FakeTransport(test_scores)
    test_report = runner.run_stage(
        stage='test', cases_path=test_path, journal_path=tmp_path / 'test.journal.jsonl',
        corpus_manifest_sha256=corpus_hash, base_url='http://127.0.0.1:8080',
        threshold_path=threshold_path, transport=test_transport, bootstrap_replicates=25,
    )
    assert test_report['status'] == 'complete'
    assert test_report['threshold']['threshold'] == pytest.approx(0.9)
    assert test_report['test_metrics']['supported_tpr'] == 1.0
    assert test_report['test_metrics']['ood_fpr'] == 0.0
    assert test_report['test_metrics']['near_boundary_fpr'] == 0.0
    assert test_report['quality_gates']['passed'] is True
    assert len(test_transport.requests) == 500
    assert test_report['bootstrap']['intent_group_count'] > 0
    assert test_report['bootstrap']['seed'] == 500


def test_resume_rejects_manifest_stage_policy_and_threshold_identity_mismatch(tmp_path):
    cases = cases_for('calibration')
    cases_path = tmp_path / 'calibration.jsonl'
    write_cases(cases_path, cases)
    journal = tmp_path / 'calibration.journal.jsonl'
    threshold = tmp_path / 'threshold.json'
    fake = FakeTransport({c['query']: 0.5 for c in cases})
    runner.run_stage(
        stage='calibration', cases_path=cases_path, journal_path=journal,
        corpus_manifest_sha256='a' * 64, base_url='http://127.0.0.1:8080',
        threshold_path=threshold, transport=fake,
    )
    with pytest.raises(runner.EvaluationRunError, match='journal_identity_mismatch'):
        runner.run_stage(
            stage='calibration', cases_path=cases_path, journal_path=journal,
            corpus_manifest_sha256='b' * 64, base_url='http://127.0.0.1:8080',
            threshold_path=threshold, transport=fake, resume=True,
        )
    test_path = tmp_path / 'test.jsonl'
    write_cases(test_path, cases_for('test'))
    with pytest.raises(runner.EvaluationRunError, match='threshold_identity_mismatch'):
        runner.run_stage(
            stage='test', cases_path=test_path, journal_path=tmp_path / 'test.jsonl',
            corpus_manifest_sha256='b' * 64, base_url='http://127.0.0.1:8080',
            threshold_path=threshold, transport=fake,
        )


def test_api_error_rows_are_preserved_and_calibration_fails_closed(tmp_path):
    cases = cases_for('calibration')
    cases_path = tmp_path / 'calibration.jsonl'
    write_cases(cases_path, cases)
    journal = tmp_path / 'calibration.journal.jsonl'
    threshold = tmp_path / 'threshold.json'
    error_query = cases[0]['query']
    transport = FakeTransport({c['query']: 0.5 for c in cases}, errors={error_query: 'http_503'})
    report = runner.run_stage(
        stage='calibration', cases_path=cases_path, journal_path=journal,
        corpus_manifest_sha256='a' * 64, base_url='http://127.0.0.1:8080',
        threshold_path=threshold, transport=transport,
    )
    assert report['execution_gate_passed'] is False
    assert report['error_count'] == 1
    assert not threshold.exists()
    lines = [json.loads(line) for line in journal.read_text().splitlines()]
    error_rows = [row for row in lines if row.get('event') == 'case_result' and row.get('error_type')]
    assert len(error_rows) == 1
    assert error_rows[0]['error_type'] == 'http_503'
    assert error_rows[0]['query'] == error_query
    serialized = journal.read_text()
    assert 'synthetic test fixture rationale' not in serialized
    assert 'answer_fact' not in serialized


def test_policy_mismatch_response_fails_calibration_without_threshold(tmp_path):
    cases = cases_for('calibration')
    cases_path = tmp_path / 'calibration.jsonl'
    write_cases(cases_path, cases)

    class PolicyMismatchTransport(FakeTransport):
        def post_search(self, payload):
            result = super().post_search(payload)
            if payload['query'] == cases[0]['query']:
                result['policy_version'] = 'retrieval-policy/changed'
            return result

    threshold = tmp_path / 'threshold.json'
    report = runner.run_stage(
        stage='calibration', cases_path=cases_path, journal_path=tmp_path / 'calibration.journal.jsonl',
        corpus_manifest_sha256='a' * 64, base_url='http://127.0.0.1:8080',
        threshold_path=threshold,
        transport=PolicyMismatchTransport({case['query']: 0.5 for case in cases}),
    )
    assert report['execution_gate_passed'] is False
    assert report['errors_by_type'] == {'retrieval_policy_mismatch': 1}
    assert not threshold.exists()


def test_source_overlap_with_calibration_threshold_is_rejected_before_http(tmp_path):
    calibration_cases = cases_for('calibration')
    calibration_path = tmp_path / 'calibration.jsonl'
    write_cases(calibration_path, calibration_cases)
    threshold_path = tmp_path / 'threshold.json'
    calibration_fake = FakeTransport({case['query']: 0.8 for case in calibration_cases})
    runner.run_stage(
        stage='calibration', cases_path=calibration_path, journal_path=tmp_path / 'calibration.journal.jsonl',
        corpus_manifest_sha256='a' * 64, base_url='http://127.0.0.1:8080',
        threshold_path=threshold_path, transport=calibration_fake,
    )
    test_cases = cases_for('test')
    first = test_cases[0]
    group = first['evidence_groups'][0]
    alternative = group['alternatives'][0]
    overlap_material = calibration_cases[0]['evidence_groups'][0]['alternatives'][0]['material_id']
    first['evidence_groups'] = [{**group, 'alternatives': [{**alternative, 'material_id': overlap_material}]}]
    test_path = tmp_path / 'test.jsonl'
    write_cases(test_path, test_cases)
    no_call_transport = FakeTransport()
    with pytest.raises(runner.EvaluationRunError, match='calibration_test_source_overlap'):
        runner.run_stage(
            stage='test', cases_path=test_path, journal_path=tmp_path / 'test.journal.jsonl',
            corpus_manifest_sha256='a' * 64, base_url='http://127.0.0.1:8080',
            threshold_path=threshold_path, transport=no_call_transport,
        )
    assert no_call_transport.requests == []


def test_case_id_overlap_with_calibration_threshold_is_rejected_before_http(tmp_path):
    calibration_cases = cases_for('calibration')
    calibration_path = tmp_path / 'calibration.jsonl'
    write_cases(calibration_path, calibration_cases)
    threshold_path = tmp_path / 'threshold.json'
    runner.run_stage(
        stage='calibration', cases_path=calibration_path, journal_path=tmp_path / 'calibration.journal.jsonl',
        corpus_manifest_sha256='a' * 64, base_url='http://127.0.0.1:8080',
        threshold_path=threshold_path, transport=FakeTransport({case['query']: 0.8 for case in calibration_cases}),
    )
    test_cases = cases_for('test')
    test_cases[0] = {**test_cases[0], 'id': calibration_cases[0]['id']}
    test_path = tmp_path / 'test.jsonl'
    write_cases(test_path, test_cases)
    no_call_transport = FakeTransport()
    with pytest.raises(runner.EvaluationRunError, match='calibration_test_case_overlap'):
        runner.run_stage(
            stage='test', cases_path=test_path, journal_path=tmp_path / 'test.journal.jsonl',
            corpus_manifest_sha256='a' * 64, base_url='http://127.0.0.1:8080',
            threshold_path=threshold_path, transport=no_call_transport,
        )
    assert no_call_transport.requests == []


def test_http_transport_stops_after_two_bounded_retries():
    calls = []
    sleeps = []

    def urlopen(request, timeout):
        calls.append((request, timeout))
        raise HTTPError(request.full_url, 503, 'unavailable', {}, None)

    transport = runner.HTTPTransport('http://127.0.0.1:8080', urlopen=urlopen, sleep_fn=sleeps.append)
    with pytest.raises(runner.SearchRequestError) as error:
        transport.post_search({'query': 'synthetic', 'category': '', 'limit': 12, 'purpose': 'auto'})
    assert len(calls) == runner.MAX_HTTP_ATTEMPTS == 3
    assert len(sleeps) == 2 and all(0 <= delay <= 30 for delay in sleeps)
    assert error.value.code == 'http_503' and error.value.attempts == 3
    assert 'unavailable' not in str(error.value)


def test_journal_enforces_size_limit_before_writing_fresh_header(tmp_path, monkeypatch):
    path = tmp_path / 'too-small.journal.jsonl'
    monkeypatch.setattr(runner, 'MAX_JOURNAL_BYTES', 1)
    with pytest.raises(runner.EvaluationRunError, match='journal_size_limit'):
        runner.JsonlJournal(path, {}, resume=False)
    assert path.read_bytes() == b''


def test_journal_enforces_size_limit_before_appending_and_keeps_prior_bytes(tmp_path, monkeypatch):
    path = tmp_path / 'bounded.journal.jsonl'
    journal = runner.JsonlJournal(path, {}, resume=False)
    before = path.read_bytes()
    monkeypatch.setattr(runner, 'MAX_JOURNAL_BYTES', len(before) + 10)
    with pytest.raises(runner.EvaluationRunError, match='journal_size_limit'):
        journal.append({'event': 'case_result', 'case_id': 'case-a', 'note': 'x' * 100})
    assert path.read_bytes() == before
    assert journal.records == []
    journal.close()


def test_journal_concurrent_appends_never_exceed_cap_or_write_partial_rows(tmp_path, monkeypatch):
    path = tmp_path / 'concurrent.journal.jsonl'
    journal = runner.JsonlJournal(path, {}, resume=False)
    before = path.read_bytes()
    record_a = {'event': 'case_result', 'case_id': 'case-a'}
    record_b = {'event': 'case_result', 'case_id': 'case-b'}
    row_bytes = len((json.dumps(record_a, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode())
    monkeypatch.setattr(runner, 'MAX_JOURNAL_BYTES', len(before) + row_bytes)
    results = []

    def append(record):
        try:
            journal.append(record)
            results.append('ok')
        except runner.EvaluationRunError as error:
            results.append(error.code)

    threads = [threading.Thread(target=append, args=(record,)) for record in (record_a, record_b)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    journal.close()
    raw = path.read_bytes()
    parsed = [json.loads(line) for line in raw.splitlines()]
    assert len(raw) <= runner.MAX_JOURNAL_BYTES
    assert len(parsed) == 2
    assert sorted(results) == ['journal_size_limit', 'ok']


def test_diagnostic_quality_gate_failure_is_reported_but_does_not_fail_execution_exit(monkeypatch, capsys):
    report = {
        'stage': 'test', 'status': 'complete', 'execution_gate_passed': True,
        'case_count': 500, 'recorded_case_count': 500, 'success_count': 500, 'error_count': 0,
        'actual_confidence': 'not_provided', 'actual_action': 'not_evaluated',
        'actual_abstention': 'not_evaluated', 'threshold_proxy_enforcement': 'not_evaluated',
        'group_counts': {'intent_groups': 500, 'source_materials': 300},
        'score_metrics': {'roc_auc': 0.8},
        'quality_gates': {'passed': False, 'checks': {'ood_fpr': False}},
    }
    monkeypatch.setattr(runner, 'run_stage', lambda **_kwargs: report)
    monkeypatch.setattr(sys, 'argv', [
        'evaluate-retrieval-confidence.py', '--stage', 'test', '--cases', 'test.jsonl',
        '--journal', 'private.jsonl', '--corpus-manifest-sha256', 'a' * 64,
        '--threshold-input', 'threshold.json',
    ])
    assert runner.main() == 0
    output = json.loads(capsys.readouterr().out)
    assert output['execution_gate_passed'] is True
    assert output['quality_gates']['passed'] is False
    assert output['actual_confidence'] == 'not_provided'
    assert output['actual_action'] == output['actual_abstention'] == 'not_evaluated'
    assert output['threshold_proxy_enforcement'] == 'not_evaluated'
    assert output['group_counts']['source_materials'] == 300
    assert output['score_metrics']['roc_auc'] == pytest.approx(0.8)


def test_in_domain_missing_fpr_is_reported_as_nongated_slice():
    rows = [
        {'answerability': 'insufficient', 'boundary_type': 'in_domain_missing', 'score': 0.7},
        {'answerability': 'insufficient', 'boundary_type': 'in_domain_missing', 'score': 0.1},
        {'answerability': 'insufficient', 'boundary_type': 'ood', 'score': 0.8},
        {'answerability': 'ambiguous', 'boundary_type': 'underspecified', 'score': 0.9},
    ]
    challenge = metrics.challenge_false_positive_rates(rows, 0.5)
    gates = metrics.quality_gates({'supported_tpr': 1.0}, challenge)
    assert challenge['in_domain_missing_fpr'] == pytest.approx(0.5)
    assert challenge['in_domain_missing_denominator'] == 2
    assert 'in_domain_missing_fpr' not in gates['checks']


def test_summary_states_confidence_action_and_threshold_enforcement_are_not_provided():
    cases = cases_for('calibration')
    result_records = [
        runner._case_result_record(case, index=index, response_body=response(0.8), error=None, latency=0.01)
        for index, case in enumerate(cases)
    ]
    report = runner._summary_from_records('calibration', cases, result_records, None, bootstrap_replicates=10)
    assert report['actual_confidence'] == 'not_provided'
    assert report['actual_action'] == report['actual_abstention'] == 'not_evaluated'
    assert report['threshold_is_proxy_only'] is True
    assert report['threshold_proxy_enforcement'] == 'not_evaluated'
    assert report['case_results'][0]['actual_confidence'] == 'not_provided'
    assert report['case_results'][0]['actual_action'] == report['case_results'][0]['actual_abstention'] == 'not_evaluated'
    assert report['case_results'][0]['threshold_is_proxy_only'] is True
    assert report['group_counts'] == {
        'intent_groups': len({case['intent_group'] for case in cases}),
        'source_materials': metrics.validate_cases(cases, 'calibration')['source_material_count'],
    }


def test_cli_help_documents_calibration_then_test_commands():
    help_text = runner.build_parser().format_help()
    assert '--stage {calibration,test}' in help_text
    assert '--resume' in help_text
    assert 'calibration' in help_text and 'test' in help_text
    assert 'corpus-manifest-sha256' in help_text


def test_cli_defaults_to_baseline_rrf_and_exposes_four_modes_and_two_scores():
    args = runner.build_parser().parse_args([
        '--stage', 'calibration', '--cases', 'cal.jsonl', '--journal', 'run.jsonl',
        '--corpus-manifest-sha256', 'a' * 64, '--threshold-output', 'threshold.json',
    ])
    assert args.retrieval_mode == 'baseline'
    assert args.score_name == 'max_technical_rrf_proxy'
    assert args.evidence_advice == 'off'
    assert runner.build_parser().parse_args([
        '--stage', 'test', '--cases', 'test.jsonl', '--journal', 'run.jsonl',
        '--corpus-manifest-sha256', 'a' * 64, '--threshold-input', 'threshold.json',
        '--retrieval-mode', 'contextual_rerank',
        '--score-name', 'max_reranker_relevance_proxy',
        '--evidence-advice', 'jev',
    ]).evidence_advice == 'jev'


def test_reranker_score_requires_a_rerank_mode_before_http(tmp_path):
    cases_path = tmp_path / 'calibration.jsonl'
    write_cases(cases_path, cases_for('calibration'))

    class NoCallTransport:
        def post_search(self, _payload):
            raise AssertionError('mode validation must precede HTTP')

    with pytest.raises(runner.EvaluationRunError, match='score_requires_reranker_mode'):
        runner.run_stage(
            stage='calibration', cases_path=cases_path,
            journal_path=tmp_path / 'run.jsonl', corpus_manifest_sha256='a' * 64,
            threshold_path=tmp_path / 'threshold.json', transport=NoCallTransport(),
            retrieval_mode='contextual', score_name='max_reranker_relevance_proxy',
        )
