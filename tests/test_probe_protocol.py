import importlib.util
import io
import json
from pathlib import Path
from urllib.parse import urlsplit
import pytest

path = Path(__file__).resolve().parents[1] / 'scripts' / 'evaluate-decision-probes.py'
spec = importlib.util.spec_from_file_location('probe_protocol', path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_expected_labels_and_source_qrels_never_enter_model_payload():
    case = {'id': 'neg-hidden-label-sentinel', 'answerability': 'unsupported',
            'expected_material_ids': ['gold-source-sentinel'],
            'query': 'What is known about this workload?',
            'input': {'expected_status': 'insufficient_evidence'},
            'reason': 'private-gold-rationale'}
    payload = module.build_probe_payload(case)
    assert payload == {'kind': 'knowledge', 'question': case['query'], 'input': {}}
    serialized = json.dumps(payload)
    assert all(value not in serialized for value in ['neg-hidden-label-sentinel', 'unsupported',
        'gold-source-sentinel', 'insufficient_evidence', 'private-gold-rationale'])


def test_all_answerability_classes_use_the_same_model_visible_kind_and_input():
    for label in ['answerable', 'unsupported']:
        payload = module.build_probe_payload({'query': 'A factual question?', 'answerability': label})
        assert payload['kind'] == 'knowledge'
        assert payload['input'] == {}


@pytest.mark.parametrize('query', ['', '  ', None, 'x' * 4001])
def test_probe_question_contract_is_bounded(query):
    with pytest.raises(ValueError):
        module.build_probe_payload({'query': query})


def test_outer_whitespace_cannot_bypass_the_model_visible_question_bound():
    payload = module.build_probe_payload({'query': ' ' * 5000 + 'A factual question?  '})
    assert payload['question'] == 'A factual question?'


class FakeResponse(io.BytesIO):
    def __init__(self, payload):
        super().__init__(json.dumps(payload).encode('utf-8'))

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


class FakeDecisionAPI:
    def __init__(self, *, statuses=None, timeout_after_accept=False):
        self.statuses = statuses or {}
        self.timeout_after_accept = timeout_after_accept
        self.calls = []
        self.submitted = {}

    def open(self, request, timeout):
        method = request.get_method()
        path = urlsplit(request.full_url).path
        payload = json.loads(request.data) if request.data else None
        self.calls.append((method, path, payload))
        if method == 'POST' and path == '/api/decisions':
            job_id = f'job-{len(self.submitted) + 1}'
            self.submitted[job_id] = payload
            if self.timeout_after_accept:
                raise TimeoutError('accepted request response lost')
            return FakeResponse({'job_id': job_id})
        if method == 'GET' and path.startswith('/api/jobs/'):
            job_id = path.rsplit('/', 1)[-1]
            return FakeResponse({'id': job_id, 'status': self.statuses.get(job_id, 'succeeded'),
                                 'result': {'findings': []}, 'error': None})
        if method == 'GET' and path.startswith('/api/decisions/'):
            job_id = path.rsplit('/', 1)[-1]
            submitted = self.submitted[job_id]
            return FakeResponse({'id': job_id, 'kind': submitted['kind'], 'input': submitted['input'],
                                 'question': submitted['question'], 'result': {'findings': []}})
        raise AssertionError(f'unexpected request: {method} {path}')


def _run_with_api(monkeypatch, api, *args, **kwargs):
    monkeypatch.setattr(module.urllib.request, 'build_opener', lambda *_args, **_kwargs: api)
    return module.run(*args, **kwargs)


def _cases_file(path, *, query='A bounded knowledge question?'):
    path.write_text(json.dumps({'cases': [
        {'id': 'new-case-a', 'answerability': 'answerable', 'expected_material_ids': ['hidden-source-a'],
         'query': query, 'reason': 'private label rationale a'},
        {'id': 'new-case-b', 'answerability': 'answerable', 'expected_material_ids': ['hidden-source-b'],
         'query': 'A second bounded knowledge question?', 'reason': 'private label rationale b'},
        {'id': 'new-case-c', 'answerability': 'unsupported', 'expected_material_ids': [],
         'query': 'A third bounded knowledge question?', 'reason': 'private label rationale c'},
    ]}))
    return path


def test_probe_run_submits_all_blind_jobs_before_polling_and_gates_three_verified_successes(monkeypatch, tmp_path):
    cases = _cases_file(tmp_path / 'cases.json')
    output = tmp_path / 'fresh-probes.json'
    api = FakeDecisionAPI()

    manifest_sha256 = 'd' * 64
    report = _run_with_api(
        monkeypatch, api, cases, ['new-case-a', 'new-case-b', 'new-case-c'], output,
        'http://127.0.0.1:8080', corpus_manifest_sha256=manifest_sha256,
    )

    assert api.calls[0] == ('POST', '/api/decisions', {
        'kind': 'knowledge', 'question': 'A bounded knowledge question?', 'input': {},
    })
    first_poll = next(index for index, call in enumerate(api.calls) if call[0] == 'GET')
    post_calls = [call for call in api.calls if call[0] == 'POST']
    assert len(post_calls) == 3 and all(index < first_poll for index, call in enumerate(api.calls) if call[0] == 'POST')
    assert all(payload == {'kind': 'knowledge', 'question': payload['question'], 'input': {}}
               for _method, _path, payload in post_calls)
    assert manifest_sha256 not in json.dumps(post_calls)
    assert not any(path == '/api/feedback' for _method, path, _payload in api.calls)
    assert report['all_jobs_succeeded'] is True
    assert report['stored_blind_records_verified'] is True
    assert report['execution_gate_passed'] is True
    assert report['semantic_accuracy_evaluated'] is False
    assert report['probe_scope']['corpus_manifest_sha256'] == manifest_sha256
    assert len(report['probes']) == 3
    assert output.stat().st_mode & 0o777 == 0o600
    assert output.parent.stat().st_mode & 0o077 == 0
    assert 'hidden-source' not in json.dumps([call[2] for call in api.calls if call[0] == 'POST'])


def test_failed_terminal_probe_does_not_pass_execution_gate(monkeypatch, tmp_path):
    cases = _cases_file(tmp_path / 'cases.json')
    output = tmp_path / 'failed-probe.json'
    api = FakeDecisionAPI(statuses={'job-1': 'failed'})

    report = _run_with_api(monkeypatch, api, cases, ['new-case-a'], output, 'http://127.0.0.1:8080')

    assert report['status'] == 'complete'
    assert report['all_jobs_succeeded'] is False
    assert report['stored_blind_records_verified'] is False
    assert report['execution_gate_passed'] is False


def test_probe_fresh_mode_refuses_existing_output_without_overwriting(monkeypatch, tmp_path):
    cases = _cases_file(tmp_path / 'cases.json')
    output = tmp_path / 'old-q1-probes.json'
    output.write_text('preserve-old-report\n')
    api = FakeDecisionAPI()

    with pytest.raises(ValueError, match='fresh_output_exists'):
        _run_with_api(monkeypatch, api, cases, ['new-case-a'], output, 'http://127.0.0.1:8080')

    assert output.read_text() == 'preserve-old-report\n'
    assert api.calls == []


@pytest.mark.parametrize('mismatch', ['base_url', 'corpus_hash', 'payload'])
def test_probe_resume_rejects_base_url_hash_or_payload_scope_mismatch(monkeypatch, tmp_path, mismatch):
    cases = _cases_file(tmp_path / 'cases.json')
    output = tmp_path / 'resume-probes.json'
    api = FakeDecisionAPI()
    _run_with_api(monkeypatch, api, cases, ['new-case-a'], output, 'http://127.0.0.1:8080',
                  corpus_manifest_sha256='a' * 64)
    old_post_count = sum(method == 'POST' for method, _path, _payload in api.calls)
    resume_url = 'http://127.0.0.1:8080'
    resume_hash = 'a' * 64
    if mismatch == 'base_url':
        resume_url = 'http://127.0.0.1:8081'
    elif mismatch == 'corpus_hash':
        resume_hash = 'b' * 64
    else:
        _cases_file(cases, query='Changed query under the same case ID?')

    with pytest.raises(ValueError, match='resume_scope_mismatch'):
        _run_with_api(monkeypatch, api, cases, ['new-case-a'], output, resume_url, resume=True,
                      corpus_manifest_sha256=resume_hash)
    assert sum(method == 'POST' for method, _path, _payload in api.calls) == old_post_count


def test_probe_resume_reuses_saved_job_ids_without_new_post(monkeypatch, tmp_path):
    cases = _cases_file(tmp_path / 'cases.json')
    output = tmp_path / 'resumable-probes.json'
    api = FakeDecisionAPI()

    first = _run_with_api(monkeypatch, api, cases, ['new-case-a'], output, 'http://127.0.0.1:8080',
                          corpus_manifest_sha256='c' * 64)
    resumed = _run_with_api(monkeypatch, api, cases, ['new-case-a'], output, 'http://127.0.0.1:8080',
                             resume=True, corpus_manifest_sha256='c' * 64)

    assert first['probes'][0]['job_id'] == resumed['probes'][0]['job_id'] == 'job-1'
    assert sum(method == 'POST' for method, _path, _payload in api.calls) == 1


def test_probe_resume_refuses_legacy_report_without_explicit_scope(monkeypatch, tmp_path):
    cases = _cases_file(tmp_path / 'cases.json')
    output = tmp_path / 'legacy-probes.json'
    output.write_text(json.dumps({'status': 'complete', 'probes': [{'case_id': 'new-case-a'}]}))
    output.chmod(0o600)
    api = FakeDecisionAPI()

    with pytest.raises(ValueError, match='resume_scope_missing'):
        _run_with_api(monkeypatch, api, cases, ['new-case-a'], output, 'http://127.0.0.1:8080',
                      resume=True)
    assert api.calls == []


def test_probe_ambiguous_post_is_not_reposted_after_resume(monkeypatch, tmp_path):
    cases = _cases_file(tmp_path / 'cases.json')
    output = tmp_path / 'ambiguous-probes.json'
    api = FakeDecisionAPI(timeout_after_accept=True)

    with pytest.raises(ValueError, match='probe_submission_outcome_unknown'):
        _run_with_api(monkeypatch, api, cases, ['new-case-a'], output, 'http://127.0.0.1:8080')
    assert sum(method == 'POST' for method, _path, _payload in api.calls) == 1

    with pytest.raises(ValueError, match='probe_submission_outcome_unknown'):
        _run_with_api(monkeypatch, api, cases, ['new-case-a'], output, 'http://127.0.0.1:8080', resume=True)
    assert sum(method == 'POST' for method, _path, _payload in api.calls) == 1


def test_probe_prewrite_failure_stops_before_post_then_resume_submits_once(monkeypatch, tmp_path):
    import dse_knowledge.pipeline as pipeline

    cases = _cases_file(tmp_path / 'cases.json')
    output = tmp_path / 'prewrite-probes.json'
    api = FakeDecisionAPI()
    original_save = pipeline.save_json
    calls = []

    def fail_intent_write(path, value, *, private=True):
        calls.append(1)
        if len(calls) == 2:
            raise OSError('intent prewrite sentinel')
        return original_save(path, value, private=private)

    monkeypatch.setattr(pipeline, 'save_json', fail_intent_write)
    with pytest.raises(OSError, match='intent prewrite sentinel'):
        _run_with_api(monkeypatch, api, cases, ['new-case-a'], output, 'http://127.0.0.1:8080')
    assert api.calls == []
    monkeypatch.setattr(pipeline, 'save_json', original_save)

    report = _run_with_api(monkeypatch, api, cases, ['new-case-a'], output, 'http://127.0.0.1:8080', resume=True)
    assert report['execution_gate_passed'] is True
    assert sum(method == 'POST' for method, _path, _payload in api.calls) == 1


def test_probe_job_id_save_failure_leaves_intent_and_resume_fails_closed(monkeypatch, tmp_path):
    import dse_knowledge.pipeline as pipeline

    cases = _cases_file(tmp_path / 'cases.json')
    output = tmp_path / 'id-save-probes.json'
    api = FakeDecisionAPI()
    original_save = pipeline.save_json
    calls = []

    def fail_job_id_write(path, value, *, private=True):
        calls.append(1)
        if len(calls) == 3:
            raise OSError('job ID save sentinel')
        return original_save(path, value, private=private)

    monkeypatch.setattr(pipeline, 'save_json', fail_job_id_write)
    with pytest.raises(OSError, match='job ID save sentinel'):
        _run_with_api(monkeypatch, api, cases, ['new-case-a'], output, 'http://127.0.0.1:8080')
    assert sum(method == 'POST' for method, _path, _payload in api.calls) == 1
    monkeypatch.setattr(pipeline, 'save_json', original_save)

    with pytest.raises(ValueError, match='probe_submission_outcome_unknown'):
        _run_with_api(monkeypatch, api, cases, ['new-case-a'], output, 'http://127.0.0.1:8080', resume=True)
    assert sum(method == 'POST' for method, _path, _payload in api.calls) == 1


def test_probe_cli_requires_explicit_resume_and_accepts_manifest_hash():
    args = module.build_parser().parse_args([
        '--cases', 'cases.json', '--case-id', 'new-case-a', '--output', 'out.json',
        '--resume', '--corpus-manifest-sha256', 'a' * 64,
    ])

    assert args.resume is True
    assert args.corpus_manifest_sha256 == 'a' * 64
