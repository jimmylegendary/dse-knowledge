"""Run at most three blinded probes. Raw answers belong in an owner-only output.

Expected labels, gold references, evaluator case IDs and rationale never enter
model-visible input. All cases share one kind; this does not test kind routing.
"""
from __future__ import annotations
import argparse
import datetime
import json
import time
import urllib.request
from pathlib import Path


def build_probe_payload(case):
    query = case.get('query')
    if not isinstance(query, str) or not 3 <= len(query.strip()) <= 4000:
        raise ValueError('Probe query must contain 3 to 4000 characters')
    return {'kind': 'knowledge', 'question': query.strip(), 'input': {}}


def run(cases_path, case_ids, output_path, base_url):
    from dse_knowledge.pipeline import save_json
    loaded = json.loads(cases_path.read_text())
    cases = loaded['cases'] if isinstance(loaded, dict) else loaded
    if not 1 <= len(case_ids) <= 3 or len(set(case_ids)) != len(case_ids):
        raise ValueError('Select one to three unique case IDs')
    selected = [next(c for c in cases if c['id'] == cid) for cid in case_ids]
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def api(method, path, payload=None):
        request = urllib.request.Request(base_url.rstrip('/') + path,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={'Content-Type': 'application/json'}, method=method)
        with opener.open(request, timeout=30) as response:
            return json.load(response)

    report = json.loads(output_path.read_text()) if output_path.exists() else {
        'started_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'status': 'running', 'protocol': 'blind-question-only-v1', 'probes': []}
    if any(p['case_id'] not in case_ids for p in report['probes']):
        raise ValueError('Resume report has different cases')
    for case in selected:
        payload = build_probe_payload(case)
        previous = next((p for p in report['probes'] if p['case_id'] == case['id']), None)
        if previous is not None:
            if previous.get('model_visible_payload') != payload:
                raise ValueError('Resume report is not the same blinded payload')
            continue
        submitted = api('POST', '/api/decisions', payload)
        report['probes'].append({'case_id': case['id'],
            'expected_answerability': case['answerability'], 'question': case['query'],
            'job_id': submitted['job_id'], 'model_visible_payload': payload,
            'submitted_at': datetime.datetime.now(datetime.timezone.utc).isoformat()})
        save_json(output_path, report)
    for probe in report['probes']:
        if probe.get('job_status') in ('succeeded', 'failed'):
            if probe.get('decision_record') and (probe['decision_record']['input'] != {} or probe['decision_record']['kind'] != 'knowledge'):
                raise ValueError('Stored decision violates blinded protocol')
            continue
        deadline = time.monotonic() + 550
        while time.monotonic() < deadline:
            job = api('GET', '/api/jobs/' + probe['job_id'])
            probe['job_status'] = job['status']
            if job['status'] in ('succeeded', 'failed'):
                probe['job'] = job
                if job['status'] == 'succeeded':
                    record = api('GET', '/api/decisions/' + probe['job_id'])
                    if record['input'] != {} or record['kind'] != 'knowledge':
                        raise ValueError('Stored decision violates blinded protocol')
                    probe['decision_record'] = record
                save_json(output_path, report)
                break
            save_json(output_path, report)
            time.sleep(4)
        else:
            probe['wait_deadline_exceeded'] = True
            save_json(output_path, report)
    report['status'] = 'complete' if all(p.get('job_status') in ('succeeded', 'failed') for p in report['probes']) else 'incomplete'
    report['blinded_payload_verified'] = True
    report['finished_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    save_json(output_path, report)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--cases', type=Path, required=True)
    parser.add_argument('--case-id', action='append', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--base-url', default='http://127.0.0.1:8080')
    args = parser.parse_args()
    result = run(args.cases, args.case_id, args.output, args.base_url)
    print(json.dumps({'status': result['status'], 'probes': len(result['probes']),
                      'blinded_payload_verified': result['blinded_payload_verified']}))
