import importlib.util
from contextlib import contextmanager
from pathlib import Path
import json
import sys
import uuid

import pytest

p = Path(__file__).resolve().parents[1] / 'scripts' / 'evaluate-pilot.py'
spec = importlib.util.spec_from_file_location('evaluate_pilot', p)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def case(answerability='answerable'):
    return {'id': 'q1', 'answerability': answerability,
            'expected_material_ids': ['m1', 'm2'],
            'expected_chunks': [{'chunk_id': 'c1'}, {'chunk_id': 'c2'}]}


def paired28_cases():
    # Twelve bilingual pairs cover nine categories with at least two positive cases each.
    counts = [2, 2, 2, 1, 1, 1, 1, 1, 1]
    cases = []
    index = 1
    for category_index, count in enumerate(counts):
        for pair_index in range(count):
            pair_number = sum(counts[:category_index]) + pair_index + 1
            pair_id = str(uuid.UUID(int=1000 + pair_number))
            material_id = f'material-{pair_number}'
            for language in ('ko', 'en'):
                cases.append({
                    'id': str(uuid.UUID(int=2000 + index)),
                    'paired_id': pair_id,
                    'query': f'synthetic {language} query {pair_number}',
                    'language': language,
                    'category': f'category-{category_index + 1}',
                    'answerability': 'answerable',
                    'expected_material_ids': [material_id],
                    # Equivalent translations may point at different valid chunks.
                    'expected_chunks': [{'material_id': material_id, 'chunk_id': f'chunk-{pair_number}-{language}'}],
                })
                index += 1
    for pair_index in range(2):
        pair_id = str(uuid.UUID(int=1000 + 100 + pair_index))
        for language in ('ko', 'en'):
            cases.append({
                'id': str(uuid.UUID(int=3000 + index)), 'paired_id': pair_id,
                'query': f'synthetic unsupported {language} {pair_index}',
                'language': language, 'category': 'unsupported', 'answerability': 'unsupported',
                'expected_behavior': {'final_answer_status': 'unknown'},
            })
            index += 1
    return cases


def legacy30_cases():
    cases = []
    positive_languages = ['ko', 'en'] * 12
    counts = [3, 3, 3, 3, 3, 3, 2, 2, 2]
    positive_index = 0
    for category_index, count in enumerate(counts):
        for item_index in range(count):
            material_id = f'legacy-material-{positive_index}'
            cases.append({
                'id': f'legacy-case-{positive_index}', 'query': f'synthetic positive {positive_index}',
                'language': positive_languages[positive_index], 'category': f'category-{category_index + 1}',
                'answerability': 'answerable', 'expected_material_ids': [material_id],
                'expected_chunks': [{'material_id': material_id, 'chunk_id': f'legacy-chunk-{positive_index}'}],
            })
            positive_index += 1
    for unsupported_index in range(6):
        language = 'ko' if unsupported_index < 3 else 'en'
        cases.append({
            'id': f'legacy-unsupported-{unsupported_index}', 'query': f'synthetic unsupported {unsupported_index}',
            'language': language, 'category': 'unsupported', 'answerability': 'unsupported',
            'expected_behavior': {'final_answer_status': 'unknown'},
        })
    return cases


def score(value):
    return {metric: value for metric in module.METRICS}


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


def test_opaque_uuid_accepts_frozen_hex_and_canonical_formats_without_class_prefixes():
    value='a3f0c25ef91e4ccfa04f7db4aa0adb59'
    assert module._is_opaque_uuid(value)
    assert module._is_opaque_uuid('a3f0c25e-f91e-4ccf-a04f-7db4aa0adb59')
    assert not module._is_opaque_uuid('pos-'+value)


def test_paired28_frozen_bilingual_prose_keeps_explicit_negative_boundary():
    import pytest
    cases=paired28_cases()
    manifest={'schema_version':'paired28/v1','source_corpus_sha256':'a'*64,'source_commit':'b'*40}
    negatives=[c for c in cases if c['answerability']=='unsupported']
    for item in negatives:
        item['expected_behavior']='unknown으로 답한다. 조건을 확인하지 못했다.' if item['language']=='ko' else 'Answer unknown. The conditions are not established.'
    module.validate_cases(cases,profile='paired28',manifest=manifest)
    negatives[0]['expected_behavior']='Maybe unknown or perhaps supported.'
    with pytest.raises(ValueError,match='explicit unknown'):
        module.validate_cases(cases,profile='paired28',manifest=manifest)


def test_partial_benchmark_cannot_be_reported_as_complete():
    import pytest
    with pytest.raises(ValueError, match='24 answerable and 6 unsupported'):
        module.validate_cases([case()])


def test_saved_rankings_exclude_raw_source_body_and_vectors():
    items = module.metadata_items([{'chunk_id': 'c1', 'material_id': 'm1',
                                   'text': 'private-source-sentinel',
                                   'embedding': [1.0], 'rank': 0.1,
                                   'claim_contexts': [{'quote': 'private-quote-sentinel'}],
                                   'neighbor_evidence': [{'text': 'private-neighbor-sentinel'}]}])
    assert items == [{'chunk_id': 'c1', 'material_id': 'm1', 'rank': 0.1}]
    assert not any(secret in repr(items) for secret in ('private-source-sentinel', 'private-quote-sentinel', 'private-neighbor-sentinel'))


def test_production_hybrid_tracks_mixed_source_results_separately_from_evidence_items():
    locator = {
        'chunk_id': 'locator-chunk', 'material_id': 'm1', 'revision_id': 'r1',
        'role': 'source_navigation', 'result_kind': 'locator', 'text': 'private body',
        'role_policy': {'role': 'source_navigation', 'evidence_authority': 0.0, 'use_ceiling': 'locator',
                        'quote': 'private policy quote'},
        'trace': {'semantic_anchors': {'source_results': {
            'material_id': 'm1', 'chunk_id': 'locator-chunk', 'original_dense_rank': 1,
            'original_hybrid_position': 3, 'promoted': True, 'authority_changed': False,
        }}, 'source_text': 'private trace body'},
    }
    evidence = {
        'chunk_id': 'evidence-chunk', 'material_id': 'm2', 'revision_id': 'r2',
        'role': 'core_technical', 'result_kind': 'evidence', 'text': 'private body',
    }

    modes = module.production_modes({'source_results': [locator, evidence], 'items': [evidence]})
    exported = module.metadata_items(modes['hybrid'])

    assert [item['chunk_id'] for item in modes['hybrid']] == ['locator-chunk', 'evidence-chunk']
    assert [item['chunk_id'] for item in modes['hybrid_evidence']] == ['evidence-chunk']
    assert exported[0]['result_kind'] == 'locator'
    assert exported[0]['role'] == 'source_navigation'
    assert exported[0]['evidence_authority'] == 0.0
    assert exported[0]['role_policy']['use_ceiling'] == 'locator'
    assert exported[0]['trace']['semantic_anchors']['source_results']['original_hybrid_position'] == 3
    assert 'text' not in exported[0]
    assert 'private' not in repr(exported)
    definitions = module.mode_definitions()
    assert 'locator' in definitions['hybrid'] and 'authority' in definitions['hybrid']
    assert 'evidence-only' in definitions['hybrid_evidence']


def test_report_provenance_keeps_policy_and_semantic_anchors_without_source_payload():
    result = {
        'policy_version': 'retrieval-policy/v2.1',
        'purpose_trace': {'requested': 'design', 'resolved': 'design', 'rule': 'caller_selected_purpose'},
        'semantic_anchors': {'items': {'material_id': 'm1', 'chunk_id': 'c1', 'authority_changed': False}},
        'text': 'private source body', 'answer': 'private model answer',
    }

    provenance = module.retrieval_provenance(result)

    assert provenance == {
        'policy_version': 'retrieval-policy/v2.1',
        'purpose_trace': {'requested': 'design', 'resolved': 'design', 'rule': 'caller_selected_purpose'},
        'semantic_anchors': {'items': {'material_id': 'm1', 'chunk_id': 'c1', 'authority_changed': False}},
    }
    assert 'text' not in provenance and 'answer' not in provenance


def test_paired28_profile_validates_opaque_bilingual_pairs_and_source_qrels():
    cases = paired28_cases()
    manifest = {'schema_version': 'knowledge-quality-v2/paired28',
                'source_corpus_sha256': 'a' * 64, 'source_commit': 'b' * 40}

    module.validate_cases(cases, profile='paired28', manifest=manifest)


def test_legacy30_remains_the_default_exact_24_positive_6_negative_profile():
    cases = legacy30_cases()
    module.validate_cases(cases)
    assert len(cases) == 30
    assert sum(case['answerability'] == 'answerable' for case in cases) == 24
    assert sum(case['answerability'] == 'unsupported' for case in cases) == 6


def test_paired28_rejects_pair_qrel_mismatch_mixed_pair_field_or_nonopaque_case_id():
    import pytest
    manifest = {'schema_version': 'knowledge-quality-v2/paired28',
                'source_corpus_sha256': 'a' * 64, 'source_commit': 'b' * 40}
    cases = paired28_cases()
    cases[1]['expected_material_ids'] = ['different-material']
    cases[1]['expected_chunks'] = [{'material_id': 'different-material', 'chunk_id': 'chunk-en'}]
    with pytest.raises(ValueError, match='paired material qrels'):
        module.validate_cases(cases, profile='paired28', manifest=manifest)

    cases = paired28_cases()
    cases[0]['pair_id'] = cases[0]['paired_id']
    with pytest.raises(ValueError, match='paired_id'):
        module.validate_cases(cases, profile='paired28', manifest=manifest)

    cases = paired28_cases()
    cases[0]['id'] = 'ko-answerable-category-1'
    with pytest.raises(ValueError, match='opaque UUID'):
        module.validate_cases(cases, profile='paired28', manifest=manifest)


def test_paired_language_aggregate_weights_pairs_equally_and_excludes_unsupported():
    rows = []
    for pair_index in range(12):
        pair_id = str(uuid.UUID(int=5000 + pair_index))
        ko_value = pair_index / 12
        en_value = min(1, ko_value + 0.25)
        rows.extend([
            {'paired_id': pair_id, 'answerability': 'answerable', 'language': 'ko',
             'scores': {'hybrid': score(ko_value)}},
            {'paired_id': pair_id, 'answerability': 'answerable', 'language': 'en',
             'scores': {'hybrid': score(en_value)}},
        ])
    rows.extend([
        {'paired_id': str(uuid.UUID(int=6000 + pair_index)), 'answerability': 'unsupported',
         'language': language, 'scores': {'hybrid': None}}
        for pair_index in range(2) for language in ('ko', 'en')
    ])

    result = module.aggregate_paired_language(rows)
    hybrid = result['modes']['hybrid']
    assert hybrid['paired_denominator'] == 12
    assert hybrid['unsupported_pairs_excluded'] == 2
    assert hybrid['ko']['denominator'] == hybrid['en']['denominator'] == 12
    expected_delta = sum(min(1, i / 12 + 0.25) - i / 12 for i in range(12)) / 12
    assert hybrid['en_minus_ko']['known_source_hit_at_1'] == expected_delta
    assert result['weighting'] == 'equal_per_bilingual_pair'


def test_capture_store_separates_neighbors_and_delegates_projection(monkeypatch):
    class Store:
        def __init__(self):
            self.projection_args = None

        def rows(self, sql, args=()):
            if 'JOIN LATERAL' in sql:
                return [{'chunk_id': 'neighbor', 'text': 'source quote'}]
            return [{'chunk_id': 'graph-edge'}]

        def context_projection(self, chunk_ids, max_per_chunk=2):
            self.projection_args = (chunk_ids, max_per_chunk)
            return {'c1': [{'annotation_id': 'a1'}]}

        def invocation(self, *args):
            return None

    now = [0.0]
    def clock():
        now[0] += 1.0
        return now[0]
    monkeypatch.setattr(module.time, 'monotonic', clock)
    store = Store()
    capture = module.CaptureStore(store)
    dense_rows = capture.rows('SELECT * FROM chunks c ORDER BY c.embedding <=> vector')
    lexical_rows = capture.rows('SELECT * FROM chunks c WHERE c.search_vector @@ query')
    exact_rows = capture.rows('SELECT * FROM materials m WHERE m.title ILIKE ANY(patterns)')
    graph_rows = capture.rows('SELECT * FROM graph JOIN edges e ON true')
    neighbor_rows = capture.rows('SELECT * FROM chunks selected JOIN LATERAL (...) n ON true')
    contexts = capture.context_projection(['c1'], max_per_chunk=2)

    assert dense_rows == lexical_rows == exact_rows == graph_rows == [{'chunk_id': 'graph-edge'}]
    assert graph_rows == [{'chunk_id': 'graph-edge'}]
    assert neighbor_rows == [{'chunk_id': 'neighbor', 'text': 'source quote'}]
    assert capture.channels['graph'] == graph_rows
    assert capture.channels['neighbors'] == neighbor_rows
    assert {channel: capture.timings[channel] for channel in ('dense', 'lexical', 'exact', 'graph', 'neighbors', 'context_projection')} == {
        'dense': 1.0, 'lexical': 1.0, 'exact': 1.0, 'graph': 1.0, 'neighbors': 1.0, 'context_projection': 1.0,
    }
    assert {channel: capture.channel_counts[channel] for channel in ('dense', 'lexical', 'exact', 'graph', 'neighbors', 'context_projection')} == {
        'dense': 1, 'lexical': 1, 'exact': 1, 'graph': 1, 'neighbors': 1, 'context_projection': 1,
    }
    assert contexts == {'c1': [{'annotation_id': 'a1'}]}
    assert store.projection_args == (['c1'], 2)


def test_capture_store_delegates_snapshot_and_captures_dense_fetchall_once(monkeypatch):
    class Cursor:
        def __init__(self, one=None, many=None):
            self.one = one
            self.many = many
            self.fetchone_calls = 0
            self.fetchall_calls = 0

        def fetchone(self):
            self.fetchone_calls += 1
            return self.one

        def fetchall(self):
            self.fetchall_calls += 1
            return self.many

    dense_rows = [{'chunk_id': 'dense-1'}, {'chunk_id': 'dense-2'}]

    class Connection:
        def __init__(self, owner):
            self.owner = owner

        def execute(self, sql, args=()):
            self.owner.executions.append((sql, args))
            if sql.startswith('SET TRANSACTION'):
                return Cursor()
            if 'visible_chunk_count' in sql:
                self.owner.scope_cursor = Cursor(one={'visible_chunk_count': 1234})
                return self.owner.scope_cursor
            if 'c.embedding <=>' in sql:
                self.owner.dense_cursor = Cursor(many=dense_rows)
                return self.owner.dense_cursor
            raise AssertionError('unexpected SQL')

    class Store:
        def __init__(self):
            self.executions = []
            self.context_entries = 0
            self.context_exits = 0

        @contextmanager
        def connection(self):
            self.context_entries += 1
            try:
                yield Connection(self)
            finally:
                self.context_exits += 1

    ticks = [0.0]

    def clock():
        ticks[0] += 0.25
        return ticks[0]

    monkeypatch.setattr(module.time, 'monotonic', clock)
    store = Store()
    capture = module.CaptureStore(store)
    with capture.connection() as connection:
        connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        scope = connection.execute('SELECT visible_chunk_count', ('category-filter',)).fetchone()
        captured_dense = connection.execute('SELECT c.embedding <=> vector', ('query-vector',)).fetchall()

    assert store.context_entries == store.context_exits == 1
    assert store.executions == [
        ('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY', ()),
        ('SELECT visible_chunk_count', ('category-filter',)),
        ('SELECT c.embedding <=> vector', ('query-vector',)),
    ]
    assert scope == {'visible_chunk_count': 1234}
    assert store.scope_cursor.fetchone_calls == 1
    assert store.dense_cursor.fetchall_calls == 1
    assert captured_dense is dense_rows
    assert capture.dense_scope_count == 1234
    assert capture.channel_counts['dense_scope_count_query'] == 1
    assert capture.channels['dense'] == dense_rows
    assert capture.channel_counts['dense'] == 2
    assert capture.timings['dense'] == 0.25


def test_execution_gate_counts_capture_and_http_failures_separately():
    good_rows = [{'error_type': None}]
    good_http = [{'status': 200}, {'status': 200}]
    assert module.execution_status(good_rows, good_http) == {
        'errors': 0, 'http_errors': 0, 'execution_gate_passed': True,
    }

    capture_error = module.execution_status([{'error_type': 'AttributeError'}], good_http)
    assert capture_error == {'errors': 1, 'http_errors': 0, 'execution_gate_passed': False}

    http_error = module.execution_status(good_rows, [{'error_type': 'HTTPError'}])
    assert http_error == {'errors': 0, 'http_errors': 1, 'execution_gate_passed': False}
    non_200 = module.execution_status(good_rows, [{'status': 503}])
    assert non_200 == {'errors': 0, 'http_errors': 1, 'execution_gate_passed': False}


@pytest.mark.parametrize(('errors', 'http_errors', 'gate_passed', 'exit_code'), [
    (0, 0, True, 0),
    (1, 0, False, 1),
    (0, 1, False, 1),
])
def test_main_exit_code_follows_execution_gate(
    monkeypatch, capsys, errors, http_errors, gate_passed, exit_code,
):
    result = {
        'profile': 'legacy30', 'status': 'complete', 'observations': 30,
        'errors': errors, 'http_errors': http_errors,
        'execution_gate_passed': gate_passed, 'summary': {}, 'latency': {},
        'http_latency': {},
    }
    monkeypatch.setattr(module, 'run', lambda *args, **kwargs: result)
    monkeypatch.setattr(sys, 'argv', ['evaluate-pilot.py', '--cases', 'cases.json', '--output', 'report.json'])
    assert module.main() == exit_code
    output = json.loads(capsys.readouterr().out)
    assert output['execution_gate_passed'] is gate_passed


def test_cli_profile_is_opt_in_and_defaults_to_legacy30():
    assert module.build_parser().parse_args(['--cases', 'cases.json', '--output', 'out.json']).profile == 'legacy30'
    assert module.build_parser().parse_args(['--cases', 'cases.json', '--output', 'out.json', '--profile', 'paired28']).profile == 'paired28'
