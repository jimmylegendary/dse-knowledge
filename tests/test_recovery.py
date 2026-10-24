from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from psycopg.types.json import Jsonb

from dse_knowledge.decisions import DecisionEngine, JobLoop


REQUEST = {
    'kind': 'knowledge',
    'question': 'Which source supports this kernel choice?',
    'input': {},
}
EVIDENCE = [{
    'chunk_id': 'chunk-1',
    'revision_id': 'revision-1',
    'material_id': 'material-1',
    'text': 'The cited source says the kernel uses a tiled reduction.',
}]


def _plain(value):
    return deepcopy(value.obj if isinstance(value, Jsonb) else value)


class MemoryConnection:
    def __init__(self, store, statements):
        self.store = store
        self.statements = statements

    def execute(self, statement, args=()):
        sql = ' '.join(statement.split())
        self.statements.append(sql)
        if sql.startswith('INSERT INTO decisions('):
            did, kind, question, context, result, evidence, snapshot = args
            self.store.decisions[did] = {
                'id': did, 'kind': kind, 'question': question,
                'input': _plain(context), 'result': _plain(result),
                'evidence': _plain(evidence), 'snapshot': _plain(snapshot),
            }
        elif sql.startswith('INSERT INTO outbox('):
            event_id, payload = args
            self.store.outbox.setdefault(event_id, {
                'id': event_id, 'payload': _plain(payload), 'status': 'pending',
                'receipt': None, 'attempts': 0,
            })
        elif sql.startswith('INSERT INTO feedback('):
            feedback_id, decision_id, verdict, notes = args
            self.store.feedback[feedback_id] = {
                'id': feedback_id, 'decision_id': decision_id, 'verdict': verdict,
                'notes': notes, 'melete': {'status': 'pending'},
            }
        elif sql.startswith('INSERT INTO gaps('):
            gap_id, decision_id, reason, next_action = args
            self.store.gaps.append({
                'id': gap_id, 'decision_id': decision_id, 'reason': reason,
                'next_action': next_action,
            })
        elif sql.startswith('INSERT INTO invocations('):
            invocation_id, provider, purpose, metadata = args
            self.store.invocations.append((invocation_id, provider, purpose, _plain(metadata)))
        elif sql.startswith('UPDATE outbox SET status='):
            status, receipt, event_id = args
            row = self.store.outbox[event_id]
            row['status'] = status
            row['receipt'] = _plain(receipt)
            row['attempts'] += 1
        elif sql.startswith('UPDATE decisions SET result=jsonb_set'):
            receipt, event_id = args
            self.store.decisions[event_id]['result']['melete'] = _plain(receipt)
        elif sql.startswith('UPDATE feedback SET melete='):
            receipt, feedback_id = args
            self.store.feedback[feedback_id]['melete'] = _plain(receipt)
        elif sql.startswith('UPDATE jobs AS j SET result=d.result'):
            (job_id,) = args
            job = self.store.jobs.get(job_id)
            if job and job['status'] == 'succeeded':
                job['result'] = deepcopy(self.store.decisions[job_id]['result'])
        elif sql.startswith("UPDATE jobs SET status='queued'"):
            # Model a process restart: no prior worker can still own these rows.
            for job in self.store.jobs.values():
                if job['status'] == 'running':
                    job['status'] = 'queued'
        else:
            raise AssertionError(f'Unexpected SQL in recovery test: {sql}')
        return self


class MemoryStore:
    def __init__(self, data_root: Path):
        self.settings = SimpleNamespace(data_root=data_root)
        self.decisions = {}
        self.outbox = {}
        self.feedback = {}
        self.gaps = []
        self.jobs = {}
        self.transactions = []
        self.invocations = []
        self.stop_after_finish = None

    def _snapshot(self):
        return deepcopy((self.decisions, self.outbox, self.feedback, self.gaps, self.jobs))

    def _restore(self, snapshot):
        self.decisions, self.outbox, self.feedback, self.gaps, self.jobs = snapshot

    @contextmanager
    def connection(self):
        before = self._snapshot()
        statements = []
        self.transactions.append(statements)
        try:
            yield MemoryConnection(self, statements)
        except Exception:
            self._restore(before)
            raise

    def one(self, statement, args=()):
        sql = ' '.join(statement.split())
        row_id = args[0]
        if 'FROM decisions WHERE id=%s' in sql:
            row = self.decisions.get(row_id)
            if not row:
                return None
            if sql.startswith('SELECT result FROM decisions'):
                return {'result': deepcopy(row['result'])}
            return {key: deepcopy(row[key]) for key in ('id', 'kind', 'question', 'result')}
        raise AssertionError(f'Unexpected SELECT in recovery test: {sql}')

    def rows(self, statement, args=()):
        sql = ' '.join(statement.split())
        if sql.startswith('SELECT id,payload FROM outbox'):
            return [deepcopy(row) for row in self.outbox.values() if row['status'] == 'pending']
        raise AssertionError(f'Unexpected query in recovery test: {sql}')

    def execute(self, statement, args=()):
        with self.connection() as connection:
            connection.execute(statement, args)

    def invocation(self, provider, purpose, metadata):
        self.invocations.append((provider, purpose, deepcopy(metadata)))

    def claim_job(self):
        queued = next((row for row in self.jobs.values() if row['status'] == 'queued'), None)
        if not queued:
            return None
        queued['status'] = 'running'
        queued['attempts'] += 1
        return deepcopy(queued)

    def finish_job(self, job_id, result=None, error=None):
        row = self.jobs[job_id]
        row.update(status='failed' if error else 'succeeded', result=deepcopy(result), error=error)
        if self.stop_after_finish is not None:
            self.stop_after_finish.set()


class FakeRetriever:
    def __init__(self):
        self.calls = 0

    def search(self, question, limit):
        self.calls += 1
        return {'items': deepcopy(EVIDENCE)}


class FakeChat:
    def __init__(self):
        self.calls = 0
        self.last_metadata = {'model': 'test-model'}
        self.close_calls = 0

    def complete(self, prompt, schema):
        self.calls += 1
        return {
            'status': 'evidence_supported',
            'answer': 'The cited source supports a tiled reduction.',
            'findings': [{
                'statement': 'The source describes a tiled reduction.',
                'citations': ['chunk-1'],
                'confidence': 'source_assertion',
            }],
            'gaps': [], 'next_steps': [], 'proposals': [],
        }

    def close(self):
        self.close_calls += 1


class FakeNative:
    def __init__(self, callback=None):
        self.callback = callback
        self.calls = []

    def query_experiences(self, question):
        return {'status': 'no_match', 'items': []}

    def observe(self, payload):
        self.calls.append(deepcopy(payload))
        if self.callback:
            return self.callback(payload)
        return {'status': 'recorded', 'receipt': {'status': 'stored', 'event_id': payload['event_id']}}


def _engine(store, native=None):
    chat = FakeChat()
    retriever = FakeRetriever()
    native = native or FakeNative()
    return DecisionEngine(store, retriever, chat, native), chat, retriever, native


def test_decision_replay_reuses_job_id_and_does_not_repeat_provider_work(tmp_path):
    store = MemoryStore(tmp_path / 'runtime')
    engine, chat, retriever, native = _engine(store)

    first = engine.decide(REQUEST, decision_id='job-42')
    replay = engine.decide(REQUEST, decision_id='job-42')

    assert first['id'] == replay['id'] == 'job-42'
    assert chat.calls == retriever.calls == len(native.calls) == 1
    assert list(store.decisions) == ['job-42']
    assert list(store.outbox) == ['job-42']
    assert len(store.gaps) == 0


def test_restart_requeues_uncommitted_running_job_immediately(tmp_path):
    store = MemoryStore(tmp_path / 'runtime')
    store.jobs['job-7'] = {
        'id': 'job-7', 'kind': 'decision', 'payload': deepcopy(REQUEST),
        'status': 'running', 'attempts': 1, 'result': None, 'error': None,
    }
    engine, chat, _, _ = _engine(store)
    loop = JobLoop(store, engine)
    store.stop_after_finish = loop.stop_event

    loop.start()
    try:
        loop.thread.join(timeout=2)
        assert not loop.thread.is_alive()
        assert store.jobs['job-7']['status'] == 'succeeded'
        assert store.jobs['job-7']['result']['id'] == 'job-7'
        assert chat.calls == 1
    finally:
        loop.close()


def test_restart_after_decision_commit_reuses_persisted_result_without_llm(tmp_path):
    store = MemoryStore(tmp_path / 'runtime')
    committed = {
        'id': 'job-8', 'status': 'evidence_supported', 'answer': 'already committed',
        'findings': [], 'gaps': [], 'next_steps': [], 'proposals': [],
        'melete': {'status': 'pending'},
    }
    store.decisions['job-8'] = {
        'id': 'job-8', 'kind': 'knowledge', 'question': REQUEST['question'],
        'result': deepcopy(committed),
    }
    store.outbox['job-8'] = {
        'id': 'job-8', 'payload': {'event_id': 'job-8', 'event_type': 'decision'},
        'status': 'pending', 'receipt': None, 'attempts': 0,
    }
    store.jobs['job-8'] = {
        'id': 'job-8', 'kind': 'decision', 'payload': deepcopy(REQUEST),
        'status': 'running', 'attempts': 1, 'result': None, 'error': None,
    }
    engine, chat, retriever, native = _engine(store)
    loop = JobLoop(store, engine)
    store.stop_after_finish = loop.stop_event

    loop.start()
    try:
        loop.thread.join(timeout=2)
        assert not loop.thread.is_alive()
        assert store.jobs['job-8']['status'] == 'succeeded'
        assert store.jobs['job-8']['result'] == committed
        assert chat.calls == retriever.calls == len(native.calls) == 0
        assert list(store.decisions) == ['job-8']
    finally:
        loop.close()


def test_job_loop_lock_allows_only_one_worker_for_a_data_root(tmp_path):
    data_root = tmp_path / 'runtime'
    first_store = MemoryStore(data_root)
    second_store = MemoryStore(data_root)
    first_engine, _, _, _ = _engine(first_store)
    second_engine, _, _, _ = _engine(second_store)
    first = JobLoop(first_store, first_engine)
    second = JobLoop(second_store, second_engine)

    first.start()
    try:
        with pytest.raises(RuntimeError, match='job_worker_already_running'):
            second.start()
    finally:
        first.close()

    second.start()
    second.close()


def test_retry_memory_updates_outbox_and_canonical_owner_receipts(tmp_path):
    store = MemoryStore(tmp_path / 'runtime')
    decision_result = {'id': 'job-1', 'answer': 'saved', 'melete': {'status': 'pending'}}
    store.decisions['job-1'] = {'id': 'job-1', 'result': deepcopy(decision_result)}
    store.jobs['job-1'] = {'id': 'job-1', 'status': 'succeeded', 'result': deepcopy(decision_result)}
    store.feedback['feedback-1'] = {'id': 'feedback-1', 'melete': {'status': 'pending'}}
    decision_payload = {'event_id': 'job-1', 'event_type': 'decision'}
    feedback_payload = {'event_id': 'feedback-1', 'event_type': 'feedback'}
    store.outbox['job-1'] = {'id': 'job-1', 'payload': decision_payload, 'status': 'pending', 'receipt': None, 'attempts': 1}
    store.outbox['feedback-1'] = {'id': 'feedback-1', 'payload': feedback_payload, 'status': 'pending', 'receipt': None, 'attempts': 1}

    native = FakeNative(lambda payload: {'status': 'recorded', 'receipt': {'status': 'stored', 'event_id': payload['event_id']}})
    engine, _, _, _ = _engine(store, native)
    decision_receipt = engine.retry_memory('job-1', decision_payload)
    feedback_receipt = engine.retry_memory('feedback-1', feedback_payload)

    assert store.outbox['job-1']['receipt'] == decision_receipt
    assert store.decisions['job-1']['result']['melete'] == decision_receipt
    assert store.jobs['job-1']['result']['melete'] == decision_receipt
    assert store.outbox['feedback-1']['receipt'] == feedback_receipt
    assert store.feedback['feedback-1']['melete'] == feedback_receipt
    for statements in store.transactions:
        if any(sql.startswith('UPDATE outbox SET status=') for sql in statements):
            assert any(sql.startswith('UPDATE decisions SET result=jsonb_set') for sql in statements) or any(
                sql.startswith('UPDATE feedback SET melete=') for sql in statements
            )


def test_needs_evidence_gap_is_committed_before_native_feedback_delivery(tmp_path):
    store = MemoryStore(tmp_path / 'runtime')
    store.decisions['decision-1'] = {
        'id': 'decision-1', 'kind': 'kernel', 'question': 'Select a kernel',
        'result': {'id': 'decision-1'},
    }
    observed_state = []

    def unavailable(payload):
        observed_state.append((len(store.feedback), len(store.outbox), len(store.gaps)))
        raise OSError('native store unavailable')

    native = FakeNative(unavailable)
    engine, _, _, _ = _engine(store, native)
    result = engine.feedback({
        'decision_id': 'decision-1', 'verdict': 'needs_evidence',
        'notes': 'The cited source does not specify ISA revision.',
    })

    assert observed_state == [(1, 1, 1)]
    assert result['melete']['status'] == 'pending'
    feedback_id = result['id']
    assert store.feedback[feedback_id]['decision_id'] == 'decision-1'
    assert store.outbox[feedback_id]['status'] == 'pending'
    feedback_transaction = next(
        tx for tx in store.transactions if any(sql.startswith('INSERT INTO feedback(') for sql in tx)
    )
    assert any(sql.startswith('INSERT INTO outbox(') for sql in feedback_transaction)
    assert any(sql.startswith('INSERT INTO gaps(') for sql in feedback_transaction)


def test_provider_failure_keeps_safe_diagnostics_without_exception_body(tmp_path):
    from dse_knowledge.providers import ProviderError
    store=MemoryStore(tmp_path/'runtime')
    store.jobs['job-error']={'id':'job-error','kind':'decision','payload':deepcopy(REQUEST),'status':'queued','attempts':0}
    engine,chat,_,_=_engine(store)
    chat.last_metadata={'model':'gpt-6.1-sol','duration_seconds':360.1,'turn_completed':False}
    def failed(*_args,**_kwargs):
        raise ProviderError('codex_timeout')
    engine.decide=failed
    loop=JobLoop(store,engine);store.stop_after_finish=loop.stop_event
    loop.run()
    assert store.jobs['job-error']['status']=='failed'
    assert len(store.invocations)==1
    assert store.invocations[0][1]=='decision_failed'
    assert store.invocations[0][2]['reason']=='codex_timeout'
    assert store.invocations[0][2]['job_id']=='job-error'
    assert store.invocations[0][2]['model_metadata']['turn_completed'] is False
