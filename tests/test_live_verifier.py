from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

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


class SubmissionHTTP(FakeHTTP):
    def __init__(self, *, post_error=None):
        super().__init__()
        self.post_error = post_error
        self.post_count = 0

    def request(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        if method == 'POST' and path == '/api/decisions':
            self.post_count += 1
            if self.post_error is not None:
                raise self.post_error
            return {'job_id': f'job-{self.post_count}'}
        raise AssertionError(f'unexpected HTTP request: {method} {path}')


class InventoryOnlyStore:
    def __init__(self, *, unavailable=False, total=999, ingested=999, chunks=624):
        self.unavailable = unavailable
        self.total = total
        self.ingested = ingested
        self.chunks = chunks
        self.queries = []

    def one(self, statement, args=()):
        self.queries.append(statement)
        if self.unavailable:
            raise RuntimeError('private inventory sentinel')
        if 'FROM materials' in statement:
            return {'total': self.total, 'ingested': self.ingested}
        if 'FROM chunks' in statement:
            return {'n': self.chunks}
        raise AssertionError(f'unexpected inventory SQL: {statement}')

    def rows(self, *args, **kwargs):
        raise AssertionError('unexpected rows call before inventory gate')

    def execute(self, *args, **kwargs):
        raise AssertionError('unexpected write before inventory gate')


class WorkflowStore:
    def __init__(self, timeline=None):
        self.events = []
        self.timeline = timeline if timeline is not None else []

    def one(self, statement, args=()):
        self.events.append(('one', statement))
        self.timeline.append(('store', 'one', statement))
        if 'FROM materials' in statement:
            return {'total': 1, 'ingested': 1}
        if 'FROM chunks' in statement and 'WHERE id' not in statement:
            return {'n': 1}
        if "FROM experiments WHERE context->>'test_fixture'" in statement:
            return {'n': 0}
        raise AssertionError(f'unexpected SQL: {statement}')

    def rows(self, statement, args=()):
        self.events.append(('rows', statement))
        self.timeline.append(('store', 'rows', statement))
        if 'FROM experiments' in statement:
            return []
        raise AssertionError(f'unexpected SQL: {statement}')

    def execute(self, statement, args=()):
        self.events.append(('execute', statement, args))
        self.timeline.append(('store', 'execute', statement))


class WorkflowHTTP(FakeHTTP):
    def __init__(self, *, first_decision='unknown', timeline=None):
        super().__init__()
        self.first_decision = first_decision
        self.experiment_count = 0
        self.compare_statuses = iter(('equivalent', 'tradeoff', 'incomplete', 'not_comparable'))
        self.events = []
        self.timeline = timeline if timeline is not None else []

    def request(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        self.events.append((method, path))
        self.timeline.append(('http', method, path))
        if method == 'POST' and path == '/api/search':
            return {'items': []}
        if method == 'GET' and path == '/api/graph?limit=80':
            return {'edges': []}
        if method == 'POST' and path == '/api/validate/hardware':
            status = 'structurally_valid' if len([c for c in self.calls if c[1] == path]) == 1 else 'requires_bundle'
            return {'status': status, 'physical_feasibility': 'not_assessed'}
        if method == 'POST' and path == '/api/experiments':
            self.experiment_count += 1
            return {'id': f'exp-{self.experiment_count}'}
        if method == 'POST' and path == '/api/experiments/compare':
            return {'status': next(self.compare_statuses)}
        if method == 'POST' and path == '/api/decisions':
            if len([call for call in self.calls if call[1] == '/api/decisions']) > 1:
                return {'job_id': 'second-kind-should-not-run'}
            if self.first_decision == 'timeout':
                raise verify_live.VerificationError('http_transport_error')
            if self.first_decision == 'missing_id':
                return {}
            if self.first_decision in ('save_id_failure', 'known_ids'):
                return {'job_id': 'accepted-job-1'}
            raise AssertionError(f'unexpected first_decision={self.first_decision}')
        if method == 'GET' and path.startswith('/api/jobs/'):
            return {'id': path.rsplit('/', 1)[-1], 'status': 'failed'}
        raise AssertionError(f'unexpected HTTP request: {method} {path}')


def _run_workflow(tmp_path, *, client=None, store=None, resume=False, report_path=None):
    report_path = report_path or (tmp_path / 'workflow.json')
    return verify_live.run_verification(
        client=client or WorkflowHTTP(), store=store or WorkflowStore(),
        settings=SimpleNamespace(data_root=tmp_path), report_path=report_path,
        expected_materials=1, expected_chunks=1, resume=resume,
    )


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


@pytest.mark.parametrize('unavailable', [False, True])
def test_inventory_mismatch_or_unavailable_fails_before_any_http_or_fixture_write(tmp_path, unavailable):
    store = InventoryOnlyStore(unavailable=unavailable, total=999, ingested=999, chunks=624)
    client = FakeHTTP()
    report_path = tmp_path / 'fresh-inventory-report.json'

    path, report = verify_live.run_verification(
        client=client, store=store, settings=SimpleNamespace(data_root=tmp_path),
        report_path=report_path, expected_materials=1000, expected_chunks=624,
    )

    assert path == report_path
    assert report['status'] == 'failed'
    assert report['checks']['inventory']['passed'] is False
    assert client.calls == []
    assert len(store.queries) <= 2
    assert report_path.exists()


def test_fresh_live_run_refuses_to_overwrite_existing_output_before_db_or_http(tmp_path):
    report_path = tmp_path / 'old-q1-report.json'
    report_path.write_text('preserve-this-report\n')
    report_path.chmod(0o600)
    store = InventoryOnlyStore()
    client = FakeHTTP()

    with pytest.raises(verify_live.VerificationError, match='fresh_report_exists'):
        verify_live.run_verification(
            client=client, store=store, settings=SimpleNamespace(data_root=tmp_path),
            report_path=report_path, expected_materials=1000, expected_chunks=624,
        )

    assert report_path.read_text() == 'preserve-this-report\n'
    assert store.queries == []
    assert client.calls == []


def test_live_resume_scope_includes_optional_manifest_hash_and_rejects_mismatch(tmp_path):
    report_path = tmp_path / 'manifest-scoped-report.json'
    manifest_sha256 = 'a' * 64

    report = verify_live._load_report(
        report_path, 'http://127.0.0.1:8080', resume=False,
        expected_materials=1000, expected_chunks=624,
        corpus_manifest_sha256=manifest_sha256,
    )
    assert report['inventory_scope'] == {
        'materials': 1000, 'chunks': 624, 'corpus_manifest_sha256': manifest_sha256,
    }
    assert manifest_sha256 not in json.dumps(verify_live._decision_payloads(report['run_id']))
    verify_live._save(report_path, report)

    resumed = verify_live._load_report(
        report_path, 'http://127.0.0.1:8080', resume=True,
        expected_materials=1000, expected_chunks=624,
        corpus_manifest_sha256=manifest_sha256,
    )
    assert resumed['run_id'] == report['run_id']
    with pytest.raises(verify_live.VerificationError, match='resume_inventory_scope_mismatch'):
        verify_live._load_report(
            report_path, 'http://127.0.0.1:8080', resume=True,
            expected_materials=1000, expected_chunks=624,
            corpus_manifest_sha256='b' * 64,
        )
    with pytest.raises(verify_live.VerificationError, match='corpus_manifest_sha256_invalid'):
        verify_live._load_report(
            tmp_path / 'bad-hash.json', 'http://127.0.0.1:8080', resume=False,
            expected_materials=1000, expected_chunks=624,
            corpus_manifest_sha256='not-a-hash',
        )


def test_live_resume_rejects_base_url_mismatch_before_reusing_saved_job_ids(tmp_path):
    report_path = tmp_path / 'base-scoped-report.json'
    report = verify_live._load_report(
        report_path, 'http://127.0.0.1:8080', resume=False,
        expected_materials=1000, expected_chunks=624,
    )
    verify_live._save(report_path, report)

    with pytest.raises(verify_live.VerificationError, match='resume_base_url_mismatch'):
        verify_live._load_report(
            report_path, 'http://127.0.0.1:8081', resume=True,
            expected_materials=1000, expected_chunks=624,
        )


def test_legacy_native_100_resume_remains_explicit_and_nohash_only(tmp_path):
    report_path = tmp_path / 'legacy-native-100.json'
    report_path.write_text(json.dumps({
        'run_id': 'legacy-run', 'base_url': 'http://127.0.0.1:8080',
        'checks': {}, 'jobs': [],
    }))
    report_path.chmod(0o600)

    resumed = verify_live._load_report(
        report_path, 'http://127.0.0.1:8080', resume=True,
    )
    assert resumed['run_id'] == 'legacy-run'
    with pytest.raises(verify_live.VerificationError, match='resume_inventory_scope_mismatch'):
        verify_live._load_report(
            report_path, 'http://127.0.0.1:8080', resume=True,
            corpus_manifest_sha256='a' * 64,
        )


def test_decision_submission_persists_intent_before_post_and_stops_on_prewrite_failure(monkeypatch, tmp_path):
    report = verify_live._load_report(
        tmp_path / 'report.json', 'http://127.0.0.1:8080', resume=False,
        expected_materials=1000, expected_chunks=624,
    )
    client = SubmissionHTTP()
    original_save = verify_live._save

    def fail_before_write(*_args, **_kwargs):
        raise OSError('private write sentinel')

    monkeypatch.setattr(verify_live, '_save', fail_before_write)
    with pytest.raises(verify_live.VerificationError, match='decision_submission_intent_write_failed'):
        verify_live._submit_or_resume_decision_job(
            client, tmp_path / 'report.json', report, 'kernel',
            dict(verify_live._decision_payloads(report['run_id']))['kernel'],
        )

    assert client.post_count == 0
    monkeypatch.setattr(verify_live, '_save', original_save)
    fresh_report = verify_live._load_report(
        tmp_path / 'report.json', client.base_url, resume=False,
        expected_materials=1000, expected_chunks=624,
    )
    verify_live._submit_or_resume_decision_job(
        client, tmp_path / 'report.json', fresh_report, 'kernel',
        dict(verify_live._decision_payloads(fresh_report['run_id']))['kernel'],
    )
    assert client.post_count == 1


def test_ambiguous_decision_post_is_not_reposted_after_resume(tmp_path):
    report_path = tmp_path / 'report.json'
    report = verify_live._load_report(
        report_path, 'http://127.0.0.1:8080', resume=False,
        expected_materials=1000, expected_chunks=624,
    )
    client = SubmissionHTTP(post_error=verify_live.VerificationError('http_transport_error'))
    payload = dict(verify_live._decision_payloads(report['run_id']))['kernel']

    with pytest.raises(verify_live.VerificationError, match='decision_submission_outcome_unknown'):
        verify_live._submit_or_resume_decision_job(client, report_path, report, 'kernel', payload)
    assert client.post_count == 1
    assert report_path.exists()

    with pytest.raises(verify_live.VerificationError, match='decision_submission_outcome_unknown'):
        verify_live._load_report(
            report_path, client.base_url, resume=True,
            expected_materials=1000, expected_chunks=624,
        )
    assert client.post_count == 1


def test_decision_job_id_save_failure_leaves_intent_and_resume_does_not_repost(monkeypatch, tmp_path):
    report_path = tmp_path / 'report.json'
    report = verify_live._load_report(
        report_path, 'http://127.0.0.1:8080', resume=False,
        expected_materials=1000, expected_chunks=624,
    )
    client = SubmissionHTTP()
    original_save = verify_live._save
    writes = []

    def fail_after_post(path, value):
        writes.append(1)
        if len(writes) == 2:
            raise OSError('job id save sentinel')
        return original_save(path, value)

    monkeypatch.setattr(verify_live, '_save', fail_after_post)
    payload = {'kind': 'kernel', 'question': 'q', 'input': {}}
    payload = dict(verify_live._decision_payloads(report['run_id']))['kernel']
    with pytest.raises(verify_live.VerificationError, match='decision_submission_job_id_save_failed'):
        verify_live._submit_or_resume_decision_job(client, report_path, report, 'kernel', payload)
    assert client.post_count == 1
    monkeypatch.setattr(verify_live, '_save', original_save)
    with pytest.raises(verify_live.VerificationError, match='decision_submission_outcome_unknown'):
        verify_live._load_report(
            report_path, client.base_url, resume=True,
            expected_materials=1000, expected_chunks=624,
        )


def _workflow_payloads(run_id):
    return [(kind, {'kind': kind, 'question': f'question-{kind}', 'input': {}})
            for kind in ('hardware', 'kernel')]


@pytest.mark.parametrize('failure,expected_reason', [
    ('timeout', 'decision_submission_outcome_unknown'),
    ('missing_id', 'decision_submission_outcome_unknown'),
    ('save_id_failure', 'decision_submission_job_id_save_failed'),
])
def test_outer_workflow_stops_after_unknown_first_decision_submission(
        monkeypatch, tmp_path, failure, expected_reason):
    monkeypatch.setattr(verify_live, '_decision_payloads', _workflow_payloads)
    timeline = []
    client = WorkflowHTTP(first_decision=failure, timeline=timeline)
    store = WorkflowStore(timeline=timeline)
    report_path = tmp_path / f'{failure}.json'
    original_save = verify_live._save
    failed_id_save = False

    if failure == 'save_id_failure':
        def fail_job_id_save(path, report):
            nonlocal failed_id_save
            intent = report.get('decision_submission_intents', {}).get('hardware', {})
            if intent.get('state') == 'submitted' and not failed_id_save:
                failed_id_save = True
                raise OSError('job ID write sentinel')
            original_save(path, report)
        monkeypatch.setattr(verify_live, '_save', fail_job_id_save)

    with pytest.raises(verify_live.VerificationError, match=expected_reason):
        _run_workflow(tmp_path, client=client, store=store, report_path=report_path)

    decision_post_indexes = [index for index, event in enumerate(timeline)
                             if event == ('http', 'POST', '/api/decisions')]
    assert len(decision_post_indexes) == 1
    assert decision_post_indexes[0] == len(timeline) - 1
    assert not any(path == '/api/feedback' for _, path in client.events)

    # The persisted unresolved intent must be rejected before the resumed run touches DB or HTTP.
    monkeypatch.setattr(verify_live, '_save', original_save)
    resume_timeline = []
    resumed_client = WorkflowHTTP(first_decision='known_ids', timeline=resume_timeline)
    resumed_store = WorkflowStore(timeline=resume_timeline)
    with pytest.raises(verify_live.VerificationError, match='decision_submission_outcome_unknown'):
        _run_workflow(tmp_path, client=resumed_client, store=resumed_store,
                      resume=True, report_path=report_path)
    assert resume_timeline == []


def test_submission_intent_write_failure_aborts_controller_before_post(monkeypatch, tmp_path):
    monkeypatch.setattr(verify_live, '_decision_payloads', _workflow_payloads)
    timeline = []
    client = WorkflowHTTP(timeline=timeline)
    store = WorkflowStore(timeline=timeline)
    original_save = verify_live._save

    def fail_pending_intent(path, report):
        intent = report.get('decision_submission_intents', {}).get('hardware', {})
        if intent.get('state') == 'pending':
            raise OSError('intent write sentinel')
        original_save(path, report)

    monkeypatch.setattr(verify_live, '_save', fail_pending_intent)
    with pytest.raises(verify_live.VerificationError, match='decision_submission_intent_write_failed'):
        _run_workflow(tmp_path, client=client, store=store)

    assert not any(path == '/api/decisions' for _, path in client.events)
    assert not any(path == '/api/feedback' for _, path in client.events)


def test_resume_checks_unresolved_intent_before_any_inventory_http_or_fixture_action(monkeypatch, tmp_path):
    monkeypatch.setattr(verify_live, '_decision_payloads', _workflow_payloads)
    report_path = tmp_path / 'unknown-submission.json'
    report = verify_live._load_report(
        report_path, 'http://127.0.0.1:8080', resume=False,
        expected_materials=1, expected_chunks=1,
    )
    kind, payload = _workflow_payloads(report['run_id'])[0]
    report['decision_submission_intents'][kind] = {
        'kind': kind, 'payload_sha256': verify_live._decision_payload_sha256(payload),
        'state': 'outcome_unknown',
    }
    verify_live._save(report_path, report)
    before = report_path.read_bytes()
    timeline = []
    client = WorkflowHTTP(timeline=timeline)
    store = WorkflowStore(timeline=timeline)

    with pytest.raises(verify_live.VerificationError, match='decision_submission_outcome_unknown'):
        _run_workflow(tmp_path, client=client, store=store, resume=True, report_path=report_path)

    assert timeline == []
    assert report_path.read_bytes() == before


def test_resume_rejects_conflicting_submission_ids_before_any_workflow_action(monkeypatch, tmp_path):
    monkeypatch.setattr(verify_live, '_decision_payloads', _workflow_payloads)
    report_path = tmp_path / 'conflicting-submission-ids.json'
    report = verify_live._load_report(
        report_path, 'http://127.0.0.1:8080', resume=False,
        expected_materials=1, expected_chunks=1,
    )
    kind, payload = _workflow_payloads(report['run_id'])[0]
    report['decision_submission_intents'][kind] = {
        'kind': kind, 'payload_sha256': verify_live._decision_payload_sha256(payload),
        'state': 'submitted', 'job_id': 'job-intent',
    }
    report['checks'][f'job_{kind}_submitted'] = {
        'passed': True, 'details': {'job_id': 'job-checks'},
    }
    verify_live._save(report_path, report)
    before = report_path.read_bytes()
    timeline = []

    with pytest.raises(verify_live.VerificationError, match='decision_submission_id_conflict'):
        _run_workflow(
            tmp_path, client=WorkflowHTTP(timeline=timeline),
            store=WorkflowStore(timeline=timeline), resume=True, report_path=report_path,
        )

    assert timeline == []
    assert report_path.read_bytes() == before


def test_resume_with_all_known_submission_ids_reuses_them_without_new_posts(monkeypatch, tmp_path):
    monkeypatch.setattr(verify_live, '_decision_payloads', _workflow_payloads)
    report_path = tmp_path / 'known-submissions.json'
    report = verify_live._load_report(
        report_path, 'http://127.0.0.1:8080', resume=False,
        expected_materials=1, expected_chunks=1,
    )
    for index, (kind, payload) in enumerate(_workflow_payloads(report['run_id']), start=1):
        report['decision_submission_intents'][kind] = {
            'kind': kind, 'payload_sha256': verify_live._decision_payload_sha256(payload),
            'state': 'submitted', 'job_id': f'known-job-{index}',
        }
    verify_live._save(report_path, report)
    timeline = []
    client = WorkflowHTTP(first_decision='known_ids', timeline=timeline)
    store = WorkflowStore(timeline=timeline)

    path, resumed = _run_workflow(
        tmp_path, client=client, store=store, resume=True, report_path=report_path,
    )

    assert path == report_path
    assert [(item['kind'], item['job_id']) for item in resumed['jobs']] == [
        ('hardware', 'known-job-1'), ('kernel', 'known-job-2'),
    ]
    assert not any(method == 'POST' and route == '/api/decisions'
                   for method, route, _ in client.calls)


def test_decision_submission_with_saved_job_id_resumes_without_posting_again(tmp_path):
    report_path = tmp_path / 'report.json'
    report = verify_live._load_report(
        report_path, 'http://127.0.0.1:8080', resume=False,
        expected_materials=1000, expected_chunks=624,
    )
    client = SubmissionHTTP()
    payload = dict(verify_live._decision_payloads(report['run_id']))['kernel']

    first = verify_live._submit_or_resume_decision_job(client, report_path, report, 'kernel', payload)
    resumed = verify_live._load_report(
        report_path, client.base_url, resume=True,
        expected_materials=1000, expected_chunks=624,
    )
    second = verify_live._submit_or_resume_decision_job(client, report_path, resumed, 'kernel', payload)

    assert first == second == 'job-1'
    assert client.post_count == 1


def test_saved_decision_intent_rejects_changed_model_payload(tmp_path):
    report_path = tmp_path / 'report.json'
    report = verify_live._load_report(
        report_path, 'http://127.0.0.1:8080', resume=False,
        expected_materials=1000, expected_chunks=624,
    )
    client = SubmissionHTTP()
    verify_live._submit_or_resume_decision_job(
        client, report_path, report, 'kernel',
        dict(verify_live._decision_payloads(report['run_id']))['kernel'],
    )

    with pytest.raises(verify_live.VerificationError, match='decision_submission_payload_mismatch'):
        verify_live._submit_or_resume_decision_job(
            client, report_path, report, 'kernel',
            {'kind': 'kernel', 'question': 'changed', 'input': {}},
        )
    assert client.post_count == 1


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
        '--expected-chunks', '624', '--corpus-manifest-sha256', 'a' * 64, '--resume',
    ])

    assert verify_live.main() == 0
    assert calls == [(verify_live.DEFAULT_BASE_URL, {
        'resume': True, 'report_path': output, 'expected_materials': 24, 'expected_chunks': 624,
        'corpus_manifest_sha256': 'a' * 64,
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
