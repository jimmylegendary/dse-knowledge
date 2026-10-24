#!/usr/bin/env python3
"""Run the live HTTP/PG pilot acceptance checks; root owns execution."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import stat
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'src'
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from psycopg.types.json import Jsonb

from dse_knowledge.config import Settings
from dse_knowledge.db import Store


DEFAULT_BASE_URL = 'http://127.0.0.1:8080'
HTTP_TIMEOUT_SECONDS = 15
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
JOB_POLL_SECONDS = 3
JOB_DEADLINE_SECONDS = 900


class VerificationError(RuntimeError):
    def __init__(self, reason: str, http_status: int | None = None):
        super().__init__(reason)
        self.reason = reason
        self.http_status = http_status


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class HTTPClient:
    def __init__(self, base_url: str):
        parsed = urllib.parse.urlsplit(base_url)
        if (parsed.scheme not in ('http', 'https') or not parsed.hostname
                or parsed.username or parsed.password or parsed.query or parsed.fragment):
            raise VerificationError('base_url_invalid')
        self.base_url = base_url.rstrip('/')
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())

    def request(self, method: str, path: str, payload: dict | None = None) -> dict:
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode('utf-8')
        request = urllib.request.Request(
            self.base_url + path, data=body, method=method,
            headers={'Accept': 'application/json', 'Content-Type': 'application/json'},
        )
        try:
            with self.opener.open(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
                status = response.status
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as error:
            status = error.code
            error.close()
            raise VerificationError('http_error', status) from None
        except (TimeoutError, urllib.error.URLError, OSError):
            raise VerificationError('http_transport_error') from None
        if status < 200 or status >= 300:
            raise VerificationError('http_error', status)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise VerificationError('http_response_too_large', status)
        try:
            result = json.loads(raw.decode('utf-8'))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise VerificationError('http_response_invalid_json', status) from None
        if not isinstance(result, dict):
            raise VerificationError('http_response_invalid_shape', status)
        return result


def _private_dir(path: Path) -> None:
    try:
        if path.is_symlink():
            raise OSError
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = path.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) & 0o077):
            raise OSError
    except OSError:
        raise VerificationError('report_directory_not_private') from None


def _write_report(path: Path, report: dict) -> None:
    _private_dir(path.parent)
    try:
        if path.is_symlink():
            raise OSError
        if path.exists():
            info = path.lstat()
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or stat.S_IMODE(info.st_mode) != 0o600):
                raise OSError
        temp = path.parent / f'.{path.name}.{uuid.uuid4().hex}.tmp'
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0)
        fd = os.open(temp, flags, 0o600)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, 'w', encoding='utf-8') as output:
                fd = -1
                json.dump(report, output, ensure_ascii=False, separators=(',', ':'))
                output.write('\n')
                output.flush()
                os.fsync(output.fileno())
            os.replace(temp, path)
            directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if fd >= 0:
                os.close(fd)
            try:
                temp.unlink()
            except FileNotFoundError:
                pass
    except OSError:
        raise VerificationError('report_write_failed') from None


def _save(path: Path, report: dict) -> None:
    report['updated_at'] = dt.datetime.now(dt.timezone.utc).isoformat()
    _write_report(path, report)


def _check(path: Path, report: dict, name: str, passed: bool, details: dict | None = None) -> None:
    report['checks'][name] = {'passed': bool(passed), 'details': details or {}}
    _save(path, report)


def _minimal_dram_twin() -> str:
    return json.dumps({
        'level_id': 'live-verify-dram', 'role': 'dram', 'capacity_bytes': 1_073_741_824,
        'bandwidth_bps': 1_000_000_000, 'line_bytes': 64,
        'children': [{'level_id': 'live-verify-compute', 'role': 'compute',
                      'peak_macs_per_s': 1_000_000_000, 'children': []}],
    })


def _component_requires_bundle() -> str:
    return json.dumps({
        'schema_version': 'hat-component/v1', 'document_kind': 'component',
        'component_id': 'live-verify-component', 'component_class': 'compute_cluster',
        'resources': [], 'instances': [], 'ports': [], 'links': [],
    })


def _fixture_metrics() -> list[dict]:
    return [
        {'name': 'ttft', 'value': 100.0, 'unit': 'ms', 'direction': 'min'},
        {'name': 'board_power', 'value': 200.0, 'unit': 'W', 'direction': 'min'},
    ]


def _experiment(client: HTTPClient, run_id: str, name: str, cohort: str, metrics: list[dict], ids: list[str]) -> str:
    response = client.request('POST', '/api/experiments', {
        'name': f'{name}-{run_id[:8]}', 'cohort': cohort, 'method': 'imported',
        'metrics': metrics,
        'context': {'test_fixture': True, 'verification_id': run_id,
                    'scope': 'synthetic policy fixture; not measured hardware data'},
    })
    experiment_id = response.get('id')
    if not isinstance(experiment_id, str) or not experiment_id:
        raise VerificationError('experiment_id_missing')
    ids.append(experiment_id)
    return experiment_id


def _compare_fixture(client: HTTPClient, baseline_id: str, candidate_id: str, expected: str) -> dict:
    result = client.request('POST', '/api/experiments/compare', {
        'baseline_id': baseline_id, 'candidate_id': candidate_id,
    })
    return {'passed': result.get('status') == expected or result.get('dominance') == expected,
            'status': result.get('status'), 'dominance': result.get('dominance'),
            'exclusions': result.get('exclusions', [])}


def _decision_payloads(run_id: str) -> list[tuple[str, dict]]:
    rules = [
        {'id': f'live-rule-{index:02d}', 'value': float(index), 'operator': '<=',
         'limit': float(index + 1), 'unit': 'verifier_fixture_units', 'fixture_only': True}
        for index in range(1, 13)
    ]
    rules.append({'id': 'live-rule-13', 'value': 13.0, 'operator': '<=', 'limit': 12.0,
                  'unit': 'verifier_fixture_units', 'fixture_only': True})
    questions = [
        ('hardware',
         'For a transformer/LLM inference accelerator, compare memory hierarchy and bandwidth design options using source evidence. Give no more than three concise findings with citations, distinguish source assertions from inference, identify unknowns, and propose one next collection or experiment. The required arithmetic rules in input are synthetic verifier fixtures only; do not treat their operands as hardware measurements.',
         {'required_rules': rules, 'verification_id': run_id,
          'required_rules_scope': 'synthetic validator control only; not measured hardware data'}),
        ('kernel',
         'For a CUDA inference workload, assess whether kernel fusion and FlashAttention-style tiling are supported by the available source evidence. Give no more than three concise cited findings, state missing target ISA/shape/precision evidence as unknown, and propose a bounded validation experiment.',
         {'verification_id': run_id, 'target_performance_claims': 'unverified'}),
        ('experiment',
         'Propose a reproducible experiment to compare an LLM serving configuration under a representative workload, including TTFT, throughput, power, units, cohort, and missing measurements. Give no more than three concise cited findings and explicit unknowns; do not claim B300 performance without calibrated measurements.',
         {'verification_id': run_id, 'performance_scope': 'proposal_only'}),
    ]
    return [(kind, {'kind': kind, 'question': question, 'input': context})
            for kind, question, context in questions]


def _poll_job(client: HTTPClient, job_id: str, report_path: Path, report: dict, kind: str) -> dict:
    deadline = time.monotonic() + JOB_DEADLINE_SECONDS
    job_path = '/api/jobs/' + urllib.parse.quote(job_id, safe='')
    last_saved = 0.0
    while time.monotonic() < deadline:
        job = client.request('GET', job_path)
        status = job.get('status')
        report['active_job'] = {'kind': kind, 'job_id': job_id, 'status': status,
                                'last_polled_at': dt.datetime.now(dt.timezone.utc).isoformat()}
        now = time.monotonic()
        if now - last_saved >= 15 or status in ('succeeded', 'failed'):
            _save(report_path, report)
            last_saved = now
        if status in ('succeeded', 'failed'):
            return job
        if status not in ('queued', 'running'):
            raise VerificationError('job_status_unrecognized')
        time.sleep(JOB_POLL_SECONDS)
    raise VerificationError('job_deadline_exceeded')


def _decision_summary(client: HTTPClient, store: Store, job: dict, kind: str) -> tuple[dict, dict | None]:
    job_id = str(job.get('id') or '')
    result = job.get('result')
    if job.get('status') != 'succeeded' or not isinstance(result, dict):
        return {'kind': kind, 'job_id': job_id, 'job_status': job.get('status'),
                'error_present': bool(job.get('error'))}, None
    record = client.request('GET', '/api/decisions/' + urllib.parse.quote(job_id, safe=''))
    evidence = record.get('evidence') if isinstance(record.get('evidence'), list) else []
    evidence_ids = {item.get('chunk_id') for item in evidence if isinstance(item, dict)}
    findings = result.get('findings') if isinstance(result.get('findings'), list) else []
    finding_citations_valid = bool(findings) and all(
        isinstance(finding, dict)
        and isinstance(finding.get('statement'), str) and bool(finding['statement'].strip())
        and isinstance(finding.get('citations'), list) and bool(finding['citations'])
        and all(isinstance(citation, str) and bool(citation) for citation in finding['citations'])
        for finding in findings
    )
    citations = [citation for finding in findings if isinstance(finding, dict)
                 and isinstance(finding.get('citations'), list)
                 for citation in finding['citations'] if isinstance(citation, str)]
    proposals = result.get('proposals') if isinstance(result.get('proposals'), list) else []
    proposals_valid = bool(proposals) and all(
        isinstance(proposal, dict)
        and isinstance(proposal.get('kind'), str) and bool(proposal['kind'])
        and isinstance(proposal.get('description'), str) and bool(proposal['description'].strip())
        and isinstance(proposal.get('evidence_ids'), list)
        and all(isinstance(source_id, str) and bool(source_id) for source_id in proposal['evidence_ids'])
        for proposal in proposals
    )
    proposal_ids = [source_id for proposal in proposals if isinstance(proposal, dict)
                    and isinstance(proposal.get('evidence_ids'), list)
                    for source_id in proposal['evidence_ids'] if isinstance(source_id, str)]
    references = sorted(set(citations + proposal_ids))
    db_rows = store.rows('SELECT id FROM chunks WHERE id = ANY(%s)', (references,)) if references else []
    db_evidence_ids = {row['id'] for row in db_rows}
    citation_valid = (finding_citations_valid and set(citations) <= evidence_ids
                      and set(proposal_ids) <= evidence_ids and set(references) <= db_evidence_ids)
    snapshot = record.get('snapshot') if isinstance(record.get('snapshot'), dict) else {}
    model = snapshot.get('model_metadata') if isinstance(snapshot.get('model_metadata'), dict) else {}
    metadata_valid = (model.get('model') == 'gpt-6.1-sol' and model.get('process_exit_code') == 0
                      and model.get('tool_calls') == 0 and model.get('turn_completed') is True)
    gaps = result.get('gaps') if isinstance(result.get('gaps'), list) else []
    gaps_valid = bool(gaps) and all(isinstance(gap, str) and bool(gap.strip()) for gap in gaps)
    summary = {
        'kind': kind, 'job_id': job_id, 'job_status': job.get('status'),
        'decision_status': result.get('status'), 'findings_count': len(findings),
        'findings_at_least_one': len(findings) >= 1,
        'findings_at_most_three': len(findings) <= 3,
        'all_findings_cited': finding_citations_valid, 'citation_count': len(citations),
        'evidence_count': len(evidence), 'citations_link_to_recorded_evidence': citation_valid,
        'gaps_count': len(gaps), 'proposals_count': len(proposals),
        'gaps_field_valid': gaps_valid, 'proposals_field_valid': proposals_valid,
        'model_metadata_valid': metadata_valid,
        'model_metadata': {key: model.get(key) for key in (
            'model', 'cli_version', 'process_exit_code', 'tool_calls', 'turn_completed',
            'usage', 'duration_seconds',
        )},
    }
    if kind == 'hardware':
        validation = result.get('mandatory_validation') if isinstance(result.get('mandatory_validation'), dict) else {}
        rules = validation.get('rules') if isinstance(validation.get('rules'), list) else []
        expected_ids = [f'live-rule-{index:02d}' for index in range(1, 14)]
        rule_ids = [rule.get('id') if isinstance(rule, dict) else None for rule in rules]
        rule_statuses = [rule.get('status') if isinstance(rule, dict) else None for rule in rules]
        expected_statuses = ['pass'] * 12 + ['fail']
        summary['required_rule_check'] = {
            'decision_rejected': result.get('status') == 'constraint_rejected',
            'validation_status': validation.get('status'), 'rule_count': len(rules),
            'rule_ids_match_expected': rule_ids == expected_ids,
            'rule_statuses_match_expected': rule_statuses == expected_statuses,
            'thirteenth_rule_failed': len(rules) == 13 and rule_statuses[12] == 'fail',
        }
    return summary, record


def _decision_checks_pass(kind: str, summary: dict) -> bool:
    checks = (
        summary.get('citations_link_to_recorded_evidence') is True,
        summary.get('model_metadata_valid') is True,
        summary.get('findings_at_least_one') is True,
        summary.get('findings_at_most_three') is True,
        summary.get('all_findings_cited') is True,
        summary.get('gaps_field_valid') is True,
        summary.get('proposals_field_valid') is True,
    )
    if not all(checks):
        return False
    if kind == 'hardware':
        rule_check = summary.get('required_rule_check')
        return isinstance(rule_check, dict) and all(
            rule_check.get(key) is True for key in (
                'decision_rejected', 'rule_ids_match_expected',
                'rule_statuses_match_expected', 'thirteenth_rule_failed',
            )
        ) and rule_check.get('validation_status') == 'reject' and rule_check.get('rule_count') == 13
    return True


def _load_report(path: Path, base_url: str, *, resume: bool) -> dict:
    if not resume:
        return {
            'run_id': uuid.uuid4().hex, 'status': 'running', 'base_url': base_url,
            'started_at': dt.datetime.now(dt.timezone.utc).isoformat(), 'checks': {},
            'jobs': [], 'limitations': [
                'This verifies the 100-material HTTP/PG pilot only; it does not validate the later 145k corpus.',
                'Native HAT status is structural only; physical feasibility and B300 measurements are not assessed.',
                'Experiment policy fixtures are synthetic declared values, not hardware measurements.',
            ],
        }
    try:
        report = json.loads(path.read_text())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise VerificationError('resume_report_unavailable') from None
    if (not isinstance(report, dict) or not isinstance(report.get('run_id'), str)
            or not report['run_id'] or not isinstance(report.get('checks'), dict)
            or not isinstance(report.get('jobs'), list)):
        raise VerificationError('resume_report_invalid')
    if report.get('base_url') != base_url:
        raise VerificationError('resume_base_url_mismatch')
    report['status'] = 'running'
    report.pop('finished_at', None)
    report['resume_count'] = int(report.get('resume_count', 0)) + 1
    report['last_resumed_at'] = dt.datetime.now(dt.timezone.utc).isoformat()
    _save(path, report)
    return report


def _existing_decision_job_id(report: dict, kind: str) -> str | None:
    checks = report.get('checks') if isinstance(report.get('checks'), dict) else {}
    for name in (f'job_{kind}_submitted', f'job_{kind}_result'):
        check = checks.get(name) if isinstance(checks.get(name), dict) else {}
        details = check.get('details') if isinstance(check.get('details'), dict) else {}
        job_id = details.get('job_id')
        if isinstance(job_id, str) and job_id:
            return job_id
    jobs = report.get('jobs') if isinstance(report.get('jobs'), list) else []
    for item in jobs:
        if not isinstance(item, dict) or item.get('kind') != kind:
            continue
        summary = item.get('summary') if isinstance(item.get('summary'), dict) else {}
        job_id = item.get('job_id') or summary.get('job_id')
        if isinstance(job_id, str) and job_id:
            return job_id
    active = report.get('active_job') if isinstance(report.get('active_job'), dict) else {}
    job_id = active.get('job_id') if active.get('kind') == kind else None
    return job_id if isinstance(job_id, str) and job_id else None


def _submit_or_resume_decision_job(client: HTTPClient, report_path: Path, report: dict,
                                   kind: str, payload: dict) -> str:
    existing = _existing_decision_job_id(report, kind)
    if existing:
        return existing
    submitted = client.request('POST', '/api/decisions', payload)
    job_id = submitted.get('job_id')
    if not isinstance(job_id, str) or not job_id:
        raise VerificationError('decision_job_id_missing')
    _check(report_path, report, 'job_' + kind + '_submitted', True, {'job_id': job_id})
    report['active_job'] = {
        'kind': kind, 'job_id': job_id, 'status': 'queued',
        'last_polled_at': dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    _save(report_path, report)
    return job_id


def _receipt_summary(result: dict | None) -> dict:
    if not isinstance(result, dict):
        return {'status': 'unavailable'}
    receipt = result.get('receipt') if isinstance(result.get('receipt'), dict) else {}
    searchability = result.get('searchability') if isinstance(result.get('searchability'), dict) else {}
    return {
        'record_status': result.get('status'), 'receipt_status': receipt.get('status'),
        'receipt_memory_count': len(receipt.get('memory_ids', [])) if isinstance(receipt.get('memory_ids'), list) else 0,
        'searchability_status': searchability.get('status'),
        'matched_memory_count': len(searchability.get('matched_memory_ids', []))
        if isinstance(searchability.get('matched_memory_ids'), list) else 0,
        'embedding_pending': searchability.get('embedding_pending'),
        'dense_candidates': searchability.get('dense_candidates'),
        'lexical_candidates': searchability.get('lexical_candidates'),
    }


def _cleanup_experiments(store: Store, run_id: str, ids: list[str]) -> dict:
    error = False
    exact_ids = list(dict.fromkeys(ids))
    before_count = len(exact_ids)
    for experiment_id in exact_ids:
        try:
            store.execute('DELETE FROM experiments WHERE id=%s AND context @> %s',
                          (experiment_id, Jsonb({'test_fixture': True, 'verification_id': run_id})))
        except Exception:
            error = True
    try:
        remaining = store.one(
            "SELECT count(*) AS n FROM experiments WHERE context->>'test_fixture'='true' AND context->>'verification_id'=%s",
            (run_id,),
        )['n']
    except Exception:
        remaining = None
        error = True
    return {'exact_fixture_ids_seen': before_count, 'remaining_fixture_rows': remaining,
            'passed': not error and remaining == 0}


def _post_first_success_feedback(client: HTTPClient, store: Store, report_path: Path, report: dict,
                                 run_id: str, decision_id: str, decision_record: dict) -> None:
    result = decision_record.get('result') if isinstance(decision_record.get('result'), dict) else {}
    try:
        feedback_note = (
            f'Verification {run_id}: needs evidence. No calibrated B300 TTFT, board-power, '
            'or representative workload measurements are available; collect same-workload '
            'calibrated measurements before making performance or power claims.'
        )
        saved_submission = report.get('feedback_submission') if isinstance(report.get('feedback_submission'), dict) else {}
        if saved_submission.get('decision_id') == decision_id and isinstance(saved_submission.get('feedback_id'), str):
            feedback_id = saved_submission['feedback_id']
            feedback_api_status = saved_submission.get('api_status')
        else:
            feedback = client.request('POST', '/api/feedback', {
                'decision_id': decision_id, 'verdict': 'needs_evidence', 'notes': feedback_note,
            })
            feedback_id = feedback.get('id')
            feedback_api_status = feedback.get('status')
            if isinstance(feedback_id, str) and feedback_id:
                report['feedback_submission'] = {
                    'decision_id': decision_id, 'feedback_id': feedback_id,
                    'api_status': feedback_api_status,
                }
                _save(report_path, report)
        canonical = store.one(
            'SELECT id,decision_id,verdict,notes,melete FROM feedback WHERE id=%s AND decision_id=%s',
            (feedback_id, decision_id),
        ) if isinstance(feedback_id, str) and feedback_id else None
        gap = store.one(
            'SELECT id FROM gaps WHERE decision_id=%s AND reason=%s', (decision_id, feedback_note),
        )
        melete = canonical.get('melete') if isinstance(canonical, dict) else {}
        if not isinstance(melete, dict):melete={}
        receipt = melete.get('receipt') if isinstance(melete.get('receipt'), dict) else {}
        feedback_memory_ids = receipt.get('memory_ids') if isinstance(receipt.get('memory_ids'), list) else []
        feedback_memory_ids = [memory_id for memory_id in feedback_memory_ids if isinstance(memory_id, str)]
        feedback_searchability = melete.get('searchability') if isinstance(melete.get('searchability'), dict) else {}
        query_text = 'No calibrated B300 TTFT board power representative workload measurements ' + run_id
        experience = client.request('GET', '/api/experiences?' + urllib.parse.urlencode({'q': query_text}))
        items = experience.get('items') if isinstance(experience.get('items'), list) else []
        source_event_match = any(isinstance(item, dict)
            and isinstance(item.get('source_event_ids'), list)
            and feedback_id in item['source_event_ids'] for item in items)
        matched_memory_ids = sorted({item.get('memory_id') for item in items if isinstance(item, dict)
            and isinstance(item.get('memory_id'), str) and item.get('memory_id') in feedback_memory_ids
            and isinstance(item.get('source_event_ids'), list) and feedback_id in item['source_event_ids']})
        feedback_memory_match = bool(matched_memory_ids)
        assistant_receipt = result.get('melete') if isinstance(result.get('melete'), dict) else {}
        assistant_nested = assistant_receipt.get('receipt') if isinstance(assistant_receipt.get('receipt'), dict) else {}
        report['melete_after_feedback'] = {
            'assistant_event_record_status': assistant_receipt.get('status'),
            'assistant_receipt_status': assistant_nested.get('status'),
            'assistant_receipt_memory_ids': assistant_nested.get('memory_ids', []),
            'feedback_id': feedback_id,
            'feedback_api_status': feedback_api_status,
            'canonical_feedback_row_found': bool(canonical and canonical.get('id') == feedback_id
                                                and canonical.get('decision_id') == decision_id
                                                and canonical.get('verdict') == 'needs_evidence'),
            'gap_reopened': bool(gap),
            'feedback_record_status': melete.get('status'),
            'feedback_receipt_status': receipt.get('status'),
            'feedback_receipt_memory_ids': feedback_memory_ids,
            'feedback_searchability_status': feedback_searchability.get('status'),
            'feedback_searchability_matched_memory_ids': feedback_searchability.get('matched_memory_ids', []),
            'feedback_embedding_pending': feedback_searchability.get('embedding_pending'),
            'feedback_dense_candidates': feedback_searchability.get('dense_candidates'),
            'feedback_lexical_candidates': feedback_searchability.get('lexical_candidates'),
            'feedback_query_status': experience.get('status'),
            'feedback_query_items': len(items),
            'feedback_source_event_found': source_event_match,
            'feedback_memory_match': feedback_memory_match,
            'feedback_matched_memory_ids': matched_memory_ids,
            'assistant_memory_class': 'assistanttrace_only'
            if assistant_nested.get('status') == 'trace_only' else assistant_nested.get('status'),
            'user_feedback_memory_class': 'userfeedbackmemory' if feedback_memory_match else 'not_observed',
        }
        details = report['melete_after_feedback']
        passed = all((
            isinstance(feedback_id, str) and bool(feedback_id),
            feedback_api_status == 'stored',
            details['canonical_feedback_row_found'], details['gap_reopened'],
            bool(feedback_memory_ids), experience.get('status') == 'found',
            source_event_match, feedback_memory_match,
        ))
        _check(report_path, report, 'needs_evidence_feedback_and_melete_query', passed, details)
    except VerificationError as error:
        _check(report_path, report, 'needs_evidence_feedback_and_melete_query', False,
               {'reason': error.reason, 'http_status': error.http_status})
    except Exception:
        _check(report_path, report, 'needs_evidence_feedback_and_melete_query', False,
               {'reason': 'feedback_verification_failed'})


def _record_experiment_feedback_snapshot(report_path: Path, report: dict,
                                         decision_record: dict) -> dict:
    snapshot = decision_record.get('snapshot') if isinstance(decision_record.get('snapshot'), dict) else {}
    experience = snapshot.get('experience_snapshot') if isinstance(snapshot.get('experience_snapshot'), dict) else {}
    items = experience.get('items') if isinstance(experience.get('items'), list) else []
    feedback = report.get('melete_after_feedback') if isinstance(report.get('melete_after_feedback'), dict) else {}
    feedback_id = feedback.get('feedback_id')
    feedback_memory_ids = set(feedback.get('feedback_receipt_memory_ids', []))
    matches = [item for item in items if isinstance(item, dict)
        and item.get('memory_id') in feedback_memory_ids
        and isinstance(item.get('source_event_ids'), list) and feedback_id in item['source_event_ids']]
    feedback_memory_found = (experience.get('status') == 'found'
                             and isinstance(feedback_id, str) and bool(feedback_id)
                             and bool(feedback_memory_ids) and bool(matches))
    details = {
        'status': experience.get('status', 'not_returned'),
        'items_count': len(items),
        'feedback_id': feedback_id,
        'feedback_memory_ids': sorted(feedback_memory_ids),
        'snapshot_memory_ids': [item.get('memory_id') for item in items if isinstance(item, dict)
                                and isinstance(item.get('memory_id'), str)],
        'feedback_memory_found': feedback_memory_found,
    }
    report['experiment_experience_snapshot'] = details
    _check(report_path, report, 'experiment_snapshot_contains_feedback_memory', feedback_memory_found, details)
    return details


def run_verification(base_url: str = DEFAULT_BASE_URL, *, resume: bool = False,
                     settings: Settings | None = None, store: Store | None = None,
                     client: HTTPClient | None = None) -> tuple[Path, dict]:
    settings = settings or Settings.load()
    store = store or Store(settings)
    report_path = settings.data_root / 'qa' / 'live-verification.json'
    client = client or HTTPClient(base_url)
    report = _load_report(report_path, client.base_url, resume=resume)
    run_id = report['run_id']
    _save(report_path, report)

    try:
        inventory = store.one(
            "SELECT count(*) AS total, count(*) FILTER (WHERE status='ingested') AS ingested FROM materials")
        chunk_count = store.one('SELECT count(*) AS n FROM chunks')['n']
        _check(report_path, report, 'inventory',
               inventory['total'] == 100 and inventory['ingested'] == 100 and chunk_count == 1912,
               {'materials': inventory['total'], 'ingested_materials': inventory['ingested'], 'chunks': chunk_count,
                'expected': {'materials': 100, 'chunks': 1912}})
    except Exception:
        _check(report_path, report, 'inventory', False, {'reason': 'database_inventory_unavailable'})

    try:
        search = client.request('POST', '/api/search', {
            'query': 'FlashAttention CUDA kernel fusion', 'limit': 8,
        })
        items = search.get('items') if isinstance(search.get('items'), list) else []
        source_match = None
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get('chunk_id'), str):
                continue
            row = store.one('SELECT id,material_id,text FROM chunks WHERE id=%s', (item['chunk_id'],))
            if row and row['text'] == item.get('text') and row['material_id'] == item.get('material_id'):
                source_match = {'chunk_id': item['chunk_id'], 'material_id': row['material_id'],
                                'text_matches_database': True}
                break
        _check(report_path, report, 'search_source_roundtrip', source_match is not None,
               {'result_count': len(items), 'verified_source': source_match})
    except VerificationError as error:
        _check(report_path, report, 'search_source_roundtrip', False,
               {'reason': error.reason, 'http_status': error.http_status})
    except Exception:
        _check(report_path, report, 'search_source_roundtrip', False, {'reason': 'search_verification_failed'})

    try:
        graph = client.request('GET', '/api/graph?limit=80')
        edges = graph.get('edges') if isinstance(graph.get('edges'), list) else []
        graph_match = None
        for edge in edges:
            if not isinstance(edge, dict) or not edge.get('material_id') or not edge.get('claim_id'):
                continue
            linked = store.one(
                'SELECT c.id,c.material_id,c.chunk_id FROM claims c JOIN chunks k ON k.id=c.chunk_id '
                'JOIN materials m ON m.id=c.material_id WHERE c.id=%s AND c.material_id=%s',
                (edge['claim_id'], edge['material_id']),
            )
            if linked:
                graph_match = {'claim_id': linked['id'], 'material_id': linked['material_id'],
                               'chunk_id': linked['chunk_id']}
                break
        _check(report_path, report, 'graph_source_link', graph_match is not None,
               {'edge_count': len(edges), 'verified_source_link': graph_match})
    except VerificationError as error:
        _check(report_path, report, 'graph_source_link', False,
               {'reason': error.reason, 'http_status': error.http_status})
    except Exception:
        _check(report_path, report, 'graph_source_link', False, {'reason': 'graph_verification_failed'})

    for name, source, expected in (
        ('native_minimal_dram_twin', _minimal_dram_twin(), 'structurally_valid'),
        ('native_component_bundle_boundary', _component_requires_bundle(), 'requires_bundle'),
    ):
        try:
            result = client.request('POST', '/api/validate/hardware', {'source': source})
            passed = result.get('status') == expected and result.get('physical_feasibility') == 'not_assessed'
            _check(report_path, report, name, passed,
                   {'status': result.get('status'), 'physical_feasibility': result.get('physical_feasibility'),
                    'validation_scope': result.get('validation_scope')})
        except VerificationError as error:
            _check(report_path, report, name, False, {'reason': error.reason, 'http_status': error.http_status})

    experiment_ids: list[str] = []
    try:
        if resume:
            existing_fixtures = store.rows(
                "SELECT id FROM experiments WHERE context->>'test_fixture'='true' AND context->>'verification_id'=%s",
                (run_id,),
            )
            experiment_ids.extend(row['id'] for row in existing_fixtures if isinstance(row.get('id'), str))
        baseline = _experiment(client, run_id, 'baseline', 'verifier-cohort', _fixture_metrics(), experiment_ids)
        unit_equivalent = _experiment(client, run_id, 'unit-equivalent', 'verifier-cohort', [
            {'name': 'ttft', 'value': 0.1, 'unit': 's', 'direction': 'min'},
            {'name': 'board_power', 'value': 200.0, 'unit': 'W', 'direction': 'min'},
        ], experiment_ids)
        pareto = _experiment(client, run_id, 'pareto-tradeoff', 'verifier-cohort', [
            {'name': 'ttft', 'value': 80.0, 'unit': 'ms', 'direction': 'min'},
            {'name': 'board_power', 'value': 220.0, 'unit': 'W', 'direction': 'min'},
        ], experiment_ids)
        missing = _experiment(client, run_id, 'missing-metric', 'verifier-cohort', [
            {'name': 'ttft', 'value': 80.0, 'unit': 'ms', 'direction': 'min'},
        ], experiment_ids)
        cohort = _experiment(client, run_id, 'cohort-mismatch', 'different-verifier-cohort', _fixture_metrics(), experiment_ids)
        comparisons = {
            'unit_equivalent': _compare_fixture(client, baseline, unit_equivalent, 'equivalent'),
            'pareto_tradeoff': _compare_fixture(client, baseline, pareto, 'tradeoff'),
            'missing_metric': _compare_fixture(client, baseline, missing, 'incomplete'),
            'cohort_mismatch': _compare_fixture(client, baseline, cohort, 'not_comparable'),
        }
        for name, result in comparisons.items():
            _check(report_path, report, 'experiment_' + name, result['passed'], result)
    except VerificationError as error:
        _check(report_path, report, 'experiment_policy_fixtures', False,
               {'reason': error.reason, 'http_status': error.http_status})
    except Exception:
        _check(report_path, report, 'experiment_policy_fixtures', False, {'reason': 'experiment_fixture_failed'})
    finally:
        cleanup = _cleanup_experiments(store, run_id, experiment_ids)
        _check(report_path, report, 'experiment_fixture_cleanup', cleanup['passed'], cleanup)

    feedback_check = report.get('checks', {}).get('needs_evidence_feedback_and_melete_query', {})
    feedback_submission = report.get('feedback_submission') if isinstance(report.get('feedback_submission'), dict) else {}
    feedback_attempted = (feedback_check.get('passed') is True
                          or isinstance(feedback_submission.get('feedback_id'), str))
    for kind, payload in _decision_payloads(run_id):
        job_id = None
        try:
            job_id = _submit_or_resume_decision_job(client, report_path, report, kind, payload)
            job = _poll_job(client, job_id, report_path, report, kind)
            summary, decision_record = _decision_summary(client, store, job, kind)
            record_checks = _decision_checks_pass(kind, summary)
            _check(report_path, report, 'job_' + kind + '_result', record_checks, summary)
            if job.get('status') == 'succeeded' and decision_record:
                current_submission = report.get('feedback_submission') if isinstance(report.get('feedback_submission'), dict) else {}
                same_feedback_decision = current_submission.get('decision_id') == job_id
                current_feedback_check = report.get('checks', {}).get('needs_evidence_feedback_and_melete_query', {})
                if current_feedback_check.get('passed') is not True and (not feedback_attempted or same_feedback_decision):
                    _post_first_success_feedback(client, store, report_path, report, run_id,
                                                 job_id, decision_record)
                    feedback_submission = report.get('feedback_submission') if isinstance(report.get('feedback_submission'), dict) else {}
                    feedback_attempted = isinstance(feedback_submission.get('feedback_id'), str)
                if kind == 'experiment':
                    _record_experiment_feedback_snapshot(report_path, report, decision_record)
            elif kind == 'experiment':
                _check(report_path, report, 'experiment_snapshot_contains_feedback_memory', False,
                       {'reason': 'experiment_decision_record_unavailable', 'job_id': job_id})
            jobs = [item for item in report.get('jobs', [])
                    if not isinstance(item, dict) or item.get('kind') != kind]
            jobs.append({'kind': kind, 'job_id': job_id, 'summary': summary})
            report['jobs'] = jobs
        except VerificationError as error:
            _check(report_path, report, 'job_' + kind + '_result', False,
                   {'reason': error.reason, 'http_status': error.http_status, 'job_id': job_id})
            jobs = [item for item in report.get('jobs', [])
                    if not isinstance(item, dict) or item.get('kind') != kind]
            jobs.append({'kind': kind, 'job_id': job_id, 'failure': error.reason})
            report['jobs'] = jobs
            if kind == 'experiment':
                _check(report_path, report, 'experiment_snapshot_contains_feedback_memory', False,
                       {'reason': error.reason, 'job_id': job_id})
        except Exception:
            _check(report_path, report, 'job_' + kind + '_result', False,
                   {'reason': 'decision_verification_failed', 'job_id': job_id})
            jobs = [item for item in report.get('jobs', [])
                    if not isinstance(item, dict) or item.get('kind') != kind]
            jobs.append({'kind': kind, 'job_id': job_id, 'failure': 'decision_verification_failed'})
            report['jobs'] = jobs
            if kind == 'experiment':
                _check(report_path, report, 'experiment_snapshot_contains_feedback_memory', False,
                       {'reason': 'decision_verification_failed', 'job_id': job_id})
        _save(report_path, report)

    feedback_check = report.get('checks', {}).get('needs_evidence_feedback_and_melete_query')
    if not isinstance(feedback_check, dict):
        _check(report_path, report, 'needs_evidence_feedback_and_melete_query', False,
               {'reason': 'feedback_submission_not_reverified' if feedback_attempted
                else 'no_successful_decision_for_feedback'})

    report['finished_at'] = dt.datetime.now(dt.timezone.utc).isoformat()
    report['status'] = 'complete' if all(item['passed'] for item in report['checks'].values()) else 'failed'
    _save(report_path, report)
    return report_path, report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default=DEFAULT_BASE_URL)
    parser.add_argument('--resume', action='store_true',
                        help='Resume the private default report and reuse its submitted decision job IDs.')
    args = parser.parse_args()
    report_path = None
    try:
        report_path, report = run_verification(args.base_url, resume=args.resume)
        summary = {'status': report['status'], 'report_path': str(report_path),
                   'checks_passed': sum(check['passed'] for check in report['checks'].values()),
                   'checks_failed': sum(not check['passed'] for check in report['checks'].values())}
        print(json.dumps(summary, separators=(',', ':')), flush=True)
        return 0 if report['status'] == 'complete' else 1
    except VerificationError as error:
        print(json.dumps({'status': 'failed', 'reason': error.reason,
                          'report_path': str(report_path) if report_path else None}, separators=(',', ':')), flush=True)
        return 1
    except Exception:
        print(json.dumps({'status': 'failed', 'reason': 'live_verification_failed',
                          'report_path': str(report_path) if report_path else None}, separators=(',', ':')), flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
