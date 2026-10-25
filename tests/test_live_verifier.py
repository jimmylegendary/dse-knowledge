from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


VERIFY_PATH = Path(__file__).resolve().parents[1] / 'scripts' / 'verify-live.py'
SPEC = importlib.util.spec_from_file_location('verify_live', VERIFY_PATH)
verify_live = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verify_live)


class FakeStore:
    def __init__(self):
        self.chunk_ids = {'chunk-1'}
        self.feedback_row = None
        self.gap_row = None

    def rows(self, statement, args=()):
        if 'FROM chunks WHERE id = ANY(%s)' in statement:
            return [{'id': chunk_id} for chunk_id in args[0] if chunk_id in self.chunk_ids]
        raise AssertionError(f'unexpected SQL: {statement}')

    def one(self, statement, args=()):
        if 'FROM feedback WHERE id=%s AND decision_id=%s' in statement:
            if self.feedback_row and (self.feedback_row['id'], self.feedback_row['decision_id']) == args:
                return dict(self.feedback_row)
            return None
        if 'FROM gaps WHERE decision_id=%s AND reason=%s' in statement:
            if self.gap_row and (self.gap_row['decision_id'], self.gap_row['reason']) == args:
                return dict(self.gap_row)
            return None
        raise AssertionError(f'unexpected SQL: {statement}')


class FakeHTTP:
    def __init__(self, *, decision_record=None, feedback=None, experiences=None):
        self.decision_record = decision_record or {}
        self.feedback = feedback or {}
        self.experiences = experiences or {'status': 'no_match', 'items': []}
        self.calls = []
        self.base_url = 'http://127.0.0.1:8080'

    def request(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        if method == 'GET' and path.startswith('/api/decisions/'):
            return self.decision_record
        if method == 'POST' and path == '/api/feedback':
            return self.feedback
        if method == 'GET' and path.startswith('/api/experiences?'):
            return self.experiences
        if method == 'POST' and path == '/api/decisions':
            return {'job_id': 'unexpected-new-job'}
        raise AssertionError(f'unexpected HTTP request: {method} {path}')


def _snapshot():
    return {'model_metadata': {
        'model': 'gpt-6.1-sol', 'process_exit_code': 0,
        'tool_calls': 0, 'turn_completed': True,
    }}


def _result(*, findings=None, gaps=None, proposals=None, rules=None, validation_status='incomplete'):
    result = {
        'status': 'evidence_supported',
        'findings': findings if findings is not None else [{
            'statement': 'The cited source supports this statement.',
            'citations': ['chunk-1'],
        }],
        'gaps': gaps if gaps is not None else ['Target ISA remains unknown.'],
        'proposals': proposals if proposals is not None else [{
            'kind': 'collection', 'description': 'Collect the target ISA source.',
            'evidence_ids': [],
        }],
    }
    if rules is not None:
        result['status'] = 'constraint_rejected'
        result['mandatory_validation'] = {'status': validation_status, 'rules': rules}
    return result


def _summary(store, result, *, kind='kernel'):
    record = {'evidence': [{'chunk_id': 'chunk-1'}], 'snapshot': _snapshot()}
    client = FakeHTTP(decision_record=record)
    job = {'id': 'decision-1', 'status': 'succeeded', 'result': result}
    return verify_live._decision_summary(client, store, job, kind)[0]


def test_decision_gate_rejects_empty_findings_and_vacuous_citation_sets():
    store = FakeStore()
    empty = _summary(store, _result(findings=[]))
    uncited = _summary(store, _result(findings=[{'statement': 'Uncited claim.', 'citations': []}]))

    assert empty['findings_count'] == 0
    assert empty['citation_count'] == 0
    assert not verify_live._decision_checks_pass('kernel', empty)
    assert not verify_live._decision_checks_pass('kernel', uncited)


def test_decision_gate_requires_unknowns_and_next_proposal():
    store = FakeStore()
    no_gaps = _summary(store, _result(gaps=[]))
    no_proposals = _summary(store, _result(proposals=[]))

    assert not verify_live._decision_checks_pass('kernel', no_gaps)
    assert not verify_live._decision_checks_pass('kernel', no_proposals)


def test_hardware_gate_requires_exact_twelve_pass_one_fail_rule_vector():
    store = FakeStore()
    wrong = [{'id': f'live-rule-{i:02d}', 'status': 'fail'} for i in range(1, 14)]
    summary = _summary(store, _result(rules=wrong, validation_status='reject'), kind='hardware')

    rule_check = summary['required_rule_check']
    assert rule_check['rule_count'] == 13
    assert not rule_check['rule_statuses_match_expected']
    assert not verify_live._decision_checks_pass('hardware', summary)


def _feedback_fixtures():
    feedback_id = 'feedback-1'
    decision_id = 'decision-1'
    note = ('Verification run-1: needs evidence. No calibrated B300 TTFT, board-power, '
            'or representative workload measurements are available; collect same-workload '
            'calibrated measurements before making performance or power claims.')
    melete = {
        'status': 'recorded',
        'receipt': {'status': 'stored', 'memory_ids': ['memory-1']},
        'searchability': {'status': 'searchable', 'matched_memory_ids': ['memory-1']},
    }
    feedback = {'id': feedback_id, 'status': 'stored', 'melete': melete}
    store = FakeStore()
    store.feedback_row = {
        'id': feedback_id, 'decision_id': decision_id, 'verdict': 'needs_evidence',
        'melete': melete,
    }
    store.gap_row = {'id': 'gap-1', 'decision_id': decision_id, 'reason': note}
    report = {'run_id': 'run-1', 'checks': {}}
    return feedback_id, decision_id, note, melete, feedback, store, report


def test_feedback_gate_fails_when_id_exists_but_experience_is_not_queryable(tmp_path):
    feedback_id, decision_id, note, melete, feedback, store, report = _feedback_fixtures()
    client = FakeHTTP(feedback=feedback, experiences={'status': 'no_match', 'items': []})

    verify_live._post_first_success_feedback(
        client, store, tmp_path / 'report.json', report, 'run-1', decision_id, {},
    )

    check = report['checks']['needs_evidence_feedback_and_melete_query']
    assert check['details']['feedback_id'] == feedback_id
    assert check['details']['feedback_source_event_found'] is False
    assert check['passed'] is False


def test_feedback_gate_requires_receipt_memory_and_source_event_in_query(tmp_path):
    feedback_id, decision_id, note, melete, feedback, store, report = _feedback_fixtures()
    client = FakeHTTP(feedback=feedback, experiences={'status': 'found', 'items': [{
        'memory_id': 'memory-1', 'source_event_ids': [feedback_id],
    }]})

    verify_live._post_first_success_feedback(
        client, store, tmp_path / 'report.json', report, 'run-1', decision_id, {},
    )

    check = report['checks']['needs_evidence_feedback_and_melete_query']
    assert check['passed'] is True
    assert check['details']['feedback_memory_match'] is True
    assert check['details']['canonical_feedback_row_found'] is True
    assert check['details']['gap_reopened'] is True


def test_resume_reuses_existing_run_and_submitted_job_without_posting_again(tmp_path):
    path = tmp_path / 'report.json'
    path.write_text(json.dumps({
        'run_id': 'same-run', 'base_url': 'http://127.0.0.1:8080', 'status': 'running',
        'checks': {'job_hardware_submitted': {'passed': True, 'details': {'job_id': 'job-existing'}}},
        'jobs': [],
    }))
    path.chmod(0o600)
    client = FakeHTTP()

    report = verify_live._load_report(path, client.base_url, resume=True)
    job_id = verify_live._submit_or_resume_decision_job(
        client, path, report, 'hardware', {'kind': 'hardware'},
    )

    assert report['run_id'] == 'same-run'
    assert job_id == 'job-existing'
    assert not any(method == 'POST' and route == '/api/decisions' for method, route, _ in client.calls)


def test_expected_inventory_defaults_and_requires_explicit_chunks_for_other_scopes():
    assert verify_live._resolve_expected_inventory(100, None) == (100, 1912)
    assert verify_live._resolve_expected_inventory(100, 2000) == (100, 2000)
    assert verify_live._resolve_expected_inventory(24, 624) == (24, 624)

    with pytest.raises(verify_live.VerificationError, match='expected_chunks_required'):
        verify_live._resolve_expected_inventory(24, None)
    with pytest.raises(verify_live.VerificationError, match='expected_chunks_invalid'):
        verify_live._resolve_expected_inventory(24, 0)


def test_inventory_gate_uses_all_configured_counts():
    passed, details = verify_live._inventory_result(
        {'total': 24, 'ingested': 24}, 624, 24, 624,
    )

    assert passed is True
    assert details['expected'] == {
        'materials': 24, 'ingested_materials': 24, 'chunks': 624,
    }
    assert verify_live._inventory_result({'total': 24, 'ingested': 23}, 624, 24, 624)[0] is False
    assert verify_live._inventory_result({'total': 24, 'ingested': 24}, 623, 24, 624)[0] is False


def test_initial_report_records_configured_frozen_scope_without_legacy_fixed_count(tmp_path):
    path = tmp_path / 'report.json'

    report = verify_live._load_report(
        path, 'http://127.0.0.1:8080', resume=False,
        expected_materials=24, expected_chunks=624,
    )

    assert report['inventory_scope'] == {'materials': 24, 'chunks': 624}
    assert any('24 materials and 624 chunks' in item for item in report['limitations'])
    assert not any('100-material' in item for item in report['limitations'])


def test_resume_preserves_run_job_ids_and_rejects_different_inventory_scope(tmp_path):
    path = tmp_path / 'report.json'
    path.write_text(json.dumps({
        'run_id': 'same-run', 'base_url': 'http://127.0.0.1:8080', 'status': 'running',
        'inventory_scope': {'materials': 24, 'chunks': 624},
        'checks': {'job_hardware_submitted': {'passed': True, 'details': {'job_id': 'job-existing'}}},
        'jobs': [],
    }))
    path.chmod(0o600)

    report = verify_live._load_report(
        path, 'http://127.0.0.1:8080', resume=True,
        expected_materials=24, expected_chunks=624,
    )

    assert report['run_id'] == 'same-run'
    assert verify_live._existing_decision_job_id(report, 'hardware') == 'job-existing'
    with pytest.raises(verify_live.VerificationError, match='resume_inventory_scope_mismatch'):
        verify_live._load_report(
            path, 'http://127.0.0.1:8080', resume=True,
            expected_materials=100, expected_chunks=1912,
        )


def test_cli_forwards_output_and_expected_inventory(monkeypatch, tmp_path):
    output = tmp_path / 'custom.json'
    calls = []

    def fake_run(base_url, **kwargs):
        calls.append((base_url, kwargs))
        return output, {'status': 'complete', 'checks': {'one': {'passed': True}}}

    monkeypatch.setattr(verify_live, 'run_verification', fake_run)
    monkeypatch.setattr(verify_live.sys, 'argv', [
        str(VERIFY_PATH), '--output', str(output), '--expected-materials', '24',
        '--expected-chunks', '624', '--resume',
    ])

    assert verify_live.main() == 0
    assert calls == [(verify_live.DEFAULT_BASE_URL, {
        'resume': True, 'report_path': output, 'expected_materials': 24, 'expected_chunks': 624,
    })]


def test_later_experiment_snapshot_must_include_feedback_memory_source_event(tmp_path):
    report = {
        'checks': {},
        'melete_after_feedback': {
            'feedback_id': 'feedback-1', 'feedback_receipt_memory_ids': ['memory-1'],
        },
    }
    decision_record = {'snapshot': {'experience_snapshot': {
        'status': 'found', 'items': [{'memory_id': 'memory-2', 'source_event_ids': ['feedback-1']}],
    }}}

    details = verify_live._record_experiment_feedback_snapshot(
        tmp_path / 'report.json', report, decision_record,
    )

    assert details['feedback_memory_found'] is False
    assert report['checks']['experiment_snapshot_contains_feedback_memory']['passed'] is False


def test_later_experiment_snapshot_requires_found_status_even_with_matching_item(tmp_path):
    report = {
        'checks': {},
        'melete_after_feedback': {
            'feedback_id': 'feedback-1', 'feedback_receipt_memory_ids': ['memory-1'],
        },
    }
    decision_record = {'snapshot': {'experience_snapshot': {
        'status': 'no_match', 'items': [{
            'memory_id': 'memory-1', 'source_event_ids': ['feedback-1'],
        }],
    }}}

    details = verify_live._record_experiment_feedback_snapshot(
        tmp_path / 'report.json', report, decision_record,
    )

    assert details['feedback_memory_found'] is False
    assert report['checks']['experiment_snapshot_contains_feedback_memory']['passed'] is False
