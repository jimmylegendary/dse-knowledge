"""Run at most three blinded probes. Raw answers belong in an owner-only output.

Expected labels, gold references, evaluator case IDs and rationale never enter
model-visible input. All cases share one kind; this does not test kind routing.
"""
from __future__ import annotations
import argparse
import datetime
import hashlib
import json
import os
import re
import stat
import time
import uuid
import urllib.request
from pathlib import Path


def build_probe_payload(case):
    query = case.get('query')
    if not isinstance(query, str) or not 3 <= len(query.strip()) <= 4000:
        raise ValueError('Probe query must contain 3 to 4000 characters')
    return {'kind': 'knowledge', 'question': query.strip(), 'input': {}}


def _validate_corpus_manifest_sha256(value):
    if value is None:
        return None
    if not isinstance(value, str) or re.fullmatch(r'[0-9a-f]{64}', value) is None:
        raise ValueError('corpus_manifest_sha256_invalid')
    return value


def _payload_set_sha256(case_ids, payloads):
    scope = [{'case_id': case_id, 'payload': payloads[case_id]} for case_id in sorted(case_ids)]
    encoded = json.dumps(scope, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def _probe_scope(base_url, case_ids, payloads, corpus_manifest_sha256):
    return {
        'base_url': base_url.rstrip('/'),
        'case_ids': sorted(case_ids),
        'model_visible_payload_sha256': _payload_set_sha256(case_ids, payloads),
        'corpus_manifest_sha256': corpus_manifest_sha256,
    }


def _read_resume_report(output_path, scope, payloads):
    try:
        info = output_path.lstat()
        if (stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600):
            raise ValueError
        report = json.loads(output_path.read_text(encoding='utf-8'))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise ValueError('resume_report_unavailable_or_not_private') from None
    if not isinstance(report, dict) or report.get('protocol') != 'blind-question-only-v1':
        raise ValueError('resume_scope_missing')
    if 'probe_scope' not in report:
        raise ValueError('resume_scope_missing')
    if report.get('probe_scope') != scope:
        raise ValueError('resume_scope_mismatch')
    probes = report.get('probes')
    if not isinstance(probes, list):
        raise ValueError('resume_report_invalid')
    allowed = set(scope['case_ids'])
    seen = set()
    for probe in probes:
        if not isinstance(probe, dict) or probe.get('case_id') not in allowed or probe['case_id'] in seen:
            raise ValueError('resume_scope_mismatch')
        seen.add(probe['case_id'])
        if probe.get('model_visible_payload') != payloads[probe['case_id']]:
            raise ValueError('resume_scope_mismatch')
        if not isinstance(probe.get('job_id'), str) or not probe['job_id']:
            raise ValueError('probe_submission_outcome_unknown')
    return report


def _stored_record_matches(probe, record):
    payload = probe.get('model_visible_payload') if isinstance(probe.get('model_visible_payload'), dict) else {}
    return (isinstance(record, dict) and record.get('kind') == 'knowledge'
            and record.get('input') == {} and record.get('question') == payload.get('question'))


def _set_execution_gate(report, case_ids):
    probes = report.get('probes') if isinstance(report.get('probes'), list) else []
    by_id = {probe.get('case_id'): probe for probe in probes if isinstance(probe, dict)}
    all_present = set(by_id) == set(case_ids) and len(probes) == len(case_ids)
    all_jobs_succeeded = all_present and all(by_id[cid].get('job_status') == 'succeeded' for cid in case_ids)
    stored_records_verified = all_jobs_succeeded and all(
        by_id[cid].get('stored_blind_record_verified') is True for cid in case_ids
    )
    report['all_jobs_succeeded'] = bool(all_jobs_succeeded)
    report['stored_blind_records_verified'] = bool(stored_records_verified)
    report['execution_gate_passed'] = bool(all_jobs_succeeded and stored_records_verified)
    report['blinded_payload_verified'] = bool(all_present and all(
        by_id[cid].get('model_visible_payload', {}).get('kind') == 'knowledge'
        and by_id[cid].get('model_visible_payload', {}).get('input') == {}
        for cid in case_ids
    ))
    report['semantic_accuracy_evaluated'] = False


def run(cases_path, case_ids, output_path, base_url, *, resume=False,
        corpus_manifest_sha256=None):
    from dse_knowledge.pipeline import save_json
    loaded = json.loads(cases_path.read_text())
    cases = loaded['cases'] if isinstance(loaded, dict) else loaded
    if not 1 <= len(case_ids) <= 3 or len(set(case_ids)) != len(case_ids):
        raise ValueError('Select one to three unique case IDs')
    selected = [next(c for c in cases if c['id'] == cid) for cid in case_ids]
    corpus_manifest_sha256 = _validate_corpus_manifest_sha256(corpus_manifest_sha256)
    payloads = {case['id']: build_probe_payload(case) for case in selected}
    scope = _probe_scope(base_url, case_ids, payloads, corpus_manifest_sha256)
    output_path = Path(output_path)
    if resume:
        report = _read_resume_report(output_path, scope, payloads)
        report['status'] = 'running'
        report.pop('finished_at', None)
        report['resume_count'] = int(report.get('resume_count', 0)) + 1
        report['last_resumed_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        save_json(output_path, report, private=True)
    else:
        if output_path.exists() or output_path.is_symlink():
            raise ValueError('fresh_output_exists')
        report = {
            'run_id': uuid.uuid4().hex,
            'started_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'status': 'running', 'protocol': 'blind-question-only-v1',
            'probe_scope': scope, 'probes': [],
        }
        save_json(output_path, report, private=True)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def api(method, path, payload=None):
        request = urllib.request.Request(base_url.rstrip('/') + path,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={'Content-Type': 'application/json'}, method=method)
        with opener.open(request, timeout=30) as response:
            return json.load(response)

    for case in selected:
        payload = payloads[case['id']]
        previous = next((p for p in report['probes'] if p['case_id'] == case['id']), None)
        if previous is not None:
            if previous.get('model_visible_payload') != payload:
                raise ValueError('resume_scope_mismatch')
            if not isinstance(previous.get('job_id'), str) or not previous['job_id']:
                raise ValueError('probe_submission_outcome_unknown')
            continue
        probe = {'case_id': case['id'],
            'expected_answerability': case['answerability'], 'question': case['query'],
            'model_visible_payload': payload, 'submission_state': 'intent_pending',
            'submission_intent_at': datetime.datetime.now(datetime.timezone.utc).isoformat()}
        report['probes'].append(probe)
        save_json(output_path, report, private=True)
        try:
            submitted = api('POST', '/api/decisions', payload)
        except Exception:
            probe['submission_state'] = 'outcome_unknown'
            report['status'] = 'submission_outcome_unknown'
            try:
                save_json(output_path, report, private=True)
            except Exception:
                pass
            raise ValueError('probe_submission_outcome_unknown') from None
        job_id = submitted.get('job_id') if isinstance(submitted, dict) else None
        if not isinstance(job_id, str) or not job_id:
            probe['submission_state'] = 'outcome_unknown'
            report['status'] = 'submission_outcome_unknown'
            save_json(output_path, report, private=True)
            raise ValueError('probe_submission_outcome_unknown')
        probe.update(job_id=job_id, submission_state='submitted',
                     submitted_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
        # Persist the accepted ID before polling or any other fallible report write.
        save_json(output_path, report, private=True)
    for probe in report['probes']:
        if probe.get('job_status') in ('succeeded', 'failed'):
            if probe['job_status'] == 'failed':
                continue
            record = probe.get('decision_record')
            if not isinstance(record, dict):
                record = api('GET', '/api/decisions/' + probe['job_id'])
                probe['decision_record'] = record
            probe['stored_blind_record_verified'] = _stored_record_matches(probe, record)
            save_json(output_path, report, private=True)
            continue
        deadline = time.monotonic() + 550
        while time.monotonic() < deadline:
            job = api('GET', '/api/jobs/' + probe['job_id'])
            probe['job_status'] = job['status']
            if job['status'] in ('succeeded', 'failed'):
                probe['job'] = job
                if job['status'] == 'succeeded':
                    record = api('GET', '/api/decisions/' + probe['job_id'])
                    probe['decision_record'] = record
                    probe['stored_blind_record_verified'] = _stored_record_matches(probe, record)
                save_json(output_path, report, private=True)
                break
            save_json(output_path, report, private=True)
            time.sleep(4)
        else:
            probe['wait_deadline_exceeded'] = True
            save_json(output_path, report, private=True)
    report['status'] = 'complete' if all(p.get('job_status') in ('succeeded', 'failed') for p in report['probes']) else 'incomplete'
    _set_execution_gate(report, case_ids)
    report['finished_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    save_json(output_path, report, private=True)
    return report


def build_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument('--cases', type=Path, required=True)
    parser.add_argument('--case-id', action='append', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--base-url', default='http://127.0.0.1:8080')
    parser.add_argument('--resume', action='store_true', help='Resume only an explicitly scoped private report.')
    parser.add_argument('--corpus-manifest-sha256', help='Optional manifest hash recorded in report scope only.')
    return parser


def main():
    args = build_parser().parse_args()
    result = run(args.cases, args.case_id, args.output, args.base_url,
                 resume=args.resume, corpus_manifest_sha256=args.corpus_manifest_sha256)
    print(json.dumps({
        'status': result['status'], 'probes': len(result['probes']),
        'all_jobs_succeeded': result['all_jobs_succeeded'],
        'stored_blind_records_verified': result['stored_blind_records_verified'],
        'execution_gate_passed': result['execution_gate_passed'],
    }, separators=(',', ':')))
    return 0 if result['execution_gate_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
