#!/usr/bin/env python3
"""Build an offline comparison without copying retrieved text or private prompts."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import html
import json
import math
from pathlib import Path
import re
import statistics

ROOT = Path(__file__).resolve().parents[1]


def _load(path):
    value = json.loads(Path(path).read_text())
    def check(item):
        if isinstance(item, float) and not math.isfinite(item):
            raise ValueError('nonfinite_report_input')
        if isinstance(item, dict):
            for child in item.values(): check(child)
        elif isinstance(item, list):
            for child in item: check(child)
    check(value)
    return value


def _validate(baseline, calibration, test):
    for value, stage, count in ((baseline, 'test', 500), (calibration, 'calibration', 100), (test, 'test', 500)):
        if value.get('stage') != stage or value.get('case_count') != count:
            raise ValueError('incomparable_report_stage_or_count')
        successes, errors = value.get('success_count'), value.get('error_count')
        if (type(successes) is not int or type(errors) is not int or min(successes, errors) < 0
                or successes + errors != count):
            raise ValueError('incomparable_report_execution_counts')
    for key in ('corpus_manifest_sha256', 'retrieval_mode', 'case_contract_sha256', 'policy_version'):
        if not baseline.get(key) or len({value.get(key) for value in (baseline, calibration, test)}) != 1:
            raise ValueError('incomparable_report_' + key)
    if baseline.get('case_manifest_sha256') != test.get('case_manifest_sha256'):
        raise ValueError('incomparable_report_test_cases')
    if baseline.get('score_name') != 'max_reranker_relevance_proxy':
        raise ValueError('incomparable_report_baseline_score')
    if baseline['success_count'] != 500 or baseline['error_count'] != 0:
        raise ValueError('incomparable_report_baseline_execution')
    base_request = baseline.get('request', {})
    if (baseline['retrieval_mode'] != 'contextual_rerank'
            or base_request.get('evidence_advice', 'off') != 'off'):
        raise ValueError('incomparable_report_baseline_request')
    for value in (calibration, test):
        advice_mode=value.get('evidence_advice')
        if isinstance(advice_mode,dict):advice_mode=advice_mode.get('mode')
        if (advice_mode != 'jev' or value.get('request', {}).get('evidence_advice') != 'jev'
                or value.get('score_name') != 'jev_direct_support_proxy'):
            raise ValueError('incomparable_report_advice_mode')
        if {k:v for k,v in value.get('request',{}).items() if k!='evidence_advice'} != base_request:
            raise ValueError('incomparable_report_request')
    if calibration.get('threshold') != test.get('threshold'):
        raise ValueError('incomparable_report_threshold')
    threshold = test.get('threshold', {})
    if threshold.get('calibration_case_manifest_sha256') != calibration['case_manifest_sha256']:
        raise ValueError('incomparable_report_calibration_identity')
    for key in ('corpus_manifest_sha256','retrieval_mode','case_contract_sha256','policy_version','score_name'):
        if threshold.get(key) != test.get(key):
            raise ValueError('incomparable_report_threshold_' + key)
    if threshold.get('evidence_advice') != 'jev':
        raise ValueError('incomparable_report_threshold_advice')


def _number(value, percent=False):
    if not isinstance(value, (int, float)) or isinstance(value, bool): return '미평가'
    return f'{value*100:.2f}%' if percent else f'{value:.4f}'


def _ranking(value, key):
    return value.get('rankings', {}).get('items', {}).get('metrics', {}).get(key)


def _gate(value, calibration, verified):
    return (verified and value.get('quality_gates', {}).get('passed') is True
            and value['error_count'] == 0 and calibration['error_count'] == 0)


def _operations(path, calibration, test):
    if path is None:
        return None
    value = _load(path)
    if not isinstance(value, dict) or value.get('schema_version') != 'jev-evaluation-operations/v1':
        raise ValueError('operations_schema_invalid')
    phases = value.get('phases')
    if not isinstance(phases, dict):
        raise ValueError('operations_phases_invalid')
    result = {}
    for name, expected_count, summary in (('calibration', 100, calibration), ('test', 500, test)):
        phase = phases.get(name)
        required = ('initial_journal_sha256', 'initial_case_count', 'initial_success_count', 'initial_error_count',
                    'final_assessed_count', 'recovery_rounds', 'total_http_attempts',
                    'jev_usage', 'latency')
        if not isinstance(phase, dict) or any(key not in phase for key in required):
            raise ValueError('operations_phase_invalid')
        initial_journal = phase['initial_journal_sha256']
        if not isinstance(initial_journal, str) or not re.fullmatch(r'[0-9a-f]{64}', initial_journal):
            raise ValueError('operations_journal_invalid')
        def count(key):
            item = phase[key]
            if type(item) is not int or item < 0:
                raise ValueError('operations_count_invalid')
            return item
        initial_count = count('initial_case_count')
        initial_success = count('initial_success_count')
        initial_errors = count('initial_error_count')
        final_assessed = count('final_assessed_count')
        attempts = count('total_http_attempts')
        if (initial_count != expected_count or initial_success + initial_errors != initial_count
                or final_assessed != summary.get('success_count')
                or final_assessed + summary.get('error_count', -1) != expected_count):
            raise ValueError('operations_counts_disagree')
        rounds = phase['recovery_rounds']
        if not isinstance(rounds, list):
            raise ValueError('operations_recovery_invalid')
        previous_errors = initial_errors
        previous_journal = initial_journal
        retried_total = 0
        for round_ in rounds:
            if not isinstance(round_, dict):
                raise ValueError('operations_recovery_invalid')
            for key in ('retried_cases', 'success_count', 'error_count'):
                item = round_.get(key)
                if type(item) is not int or item < 0:
                    raise ValueError('operations_recovery_count_invalid')
            retried = round_['retried_cases']
            succeeded = round_['success_count']
            failed = round_['error_count']
            parent_hash, journal_hash = round_.get('parent_journal_sha256'), round_.get('journal_sha256')
            if (retried < 1 or retried > previous_errors or succeeded + failed != retried
                    or not isinstance(parent_hash, str) or not re.fullmatch(r'[0-9a-f]{64}', parent_hash)
                    or not isinstance(journal_hash, str) or not re.fullmatch(r'[0-9a-f]{64}', journal_hash)
                    or parent_hash != previous_journal):
                raise ValueError('operations_recovery_invalid')
            retried_total += retried
            previous_errors = previous_errors - retried + failed
            previous_journal = journal_hash
        if (attempts < initial_count + retried_total
                or final_assessed != initial_success + sum(item['success_count'] for item in rounds)
                or previous_errors != summary.get('error_count')):
            raise ValueError('operations_counts_disagree')
        if summary.get('journal_sha256') != previous_journal:
            raise ValueError('operations_journal_disagrees')
        usage = phase['jev_usage']
        if not isinstance(usage, dict):
            raise ValueError('operations_usage_invalid')
        for key in ('reported_input_tokens', 'reported_provider_calls', 'unreported_cost_calls'):
            item = usage.get(key)
            if type(item) is not int or item < 0:
                raise ValueError('operations_usage_invalid')
        cost = usage.get('reported_cost_usd')
        if (isinstance(cost, bool) or not isinstance(cost, (int, float))
                or not math.isfinite(cost) or cost < 0):
            raise ValueError('operations_usage_invalid')
        latency = phase['latency']
        if not isinstance(latency, dict):
            raise ValueError('operations_latency_invalid')
        for key in ('initial_http_p50', 'initial_http_p95', 'jev_provider_p50_ms', 'jev_provider_p95_ms'):
            item = latency.get(key)
            if item is not None and (isinstance(item, bool) or not isinstance(item, (int, float))
                                     or not math.isfinite(item) or item < 0):
                raise ValueError('operations_latency_invalid')
        for low, high in (('initial_http_p50', 'initial_http_p95'),
                          ('jev_provider_p50_ms', 'jev_provider_p95_ms')):
            if latency[low] is not None and latency[high] is not None and latency[low] > latency[high]:
                raise ValueError('operations_latency_invalid')
        result[name] = {
            'initial_success_count': initial_success,
            'initial_error_count': initial_errors,
            'recovery_round_count': len(rounds),
            'retried_cases': retried_total,
            'recovery_successes': sum(item['success_count'] for item in rounds),
            'final_assessed_count': final_assessed,
            'total_http_attempts': attempts,
            'usage': {key: usage[key] for key in ('reported_input_tokens', 'reported_cost_usd',
                                                   'reported_provider_calls', 'unreported_cost_calls')},
            'latency': {key: latency[key] for key in ('initial_http_p50', 'initial_http_p95',
                                                       'jev_provider_p50_ms', 'jev_provider_p95_ms')},
        }
    return result


def _operations_table(operations):
    if operations is None:
        return ('<section class="review-section"><h2>운영 실행 신뢰도</h2><p><strong>최초 시도 신뢰도 미평가</strong> · operations 기록이 제공되지 않아 최초 요청의 성공률을 추정하지 않습니다.</p></section>',
                'NOT_EVALUATED')
    initial_gate = 'PASS' if all(operations[name]['initial_error_count'] == 0
                                 for name in ('calibration', 'test')) else 'FAIL'
    labels = {'calibration': 'Calibration', 'test': 'Test'}
    rows = []
    for name in ('calibration', 'test'):
        item = operations[name]; usage = item['usage']; latency = item['latency']
        initial_count = item['initial_success_count'] + item['initial_error_count']
        def pctile(key, suffix):
            return '미보고' if latency[key] is None else f"{latency[key]:.2f}{suffix}"
        rows.append('<tr><th scope="row">'+labels[name]+'</th><td>'+f"{item['initial_success_count']} / {initial_count}"+
                    '</td><td>'+str(item['initial_error_count'])+'</td><td>'+str(item['recovery_round_count'])+
                    '</td><td>'+str(item['retried_cases'])+'</td><td>'+str(item['recovery_successes'])+
                    '</td><td>'+str(item['final_assessed_count'])+'</td><td>'+str(item['total_http_attempts'])+
                    '</td><td>'+f"{usage['reported_input_tokens']:,} tokens · ${usage['reported_cost_usd']:.4f} · " +
                    f"{usage['reported_provider_calls']} calls reported; {usage['unreported_cost_calls']} cost-unreported"+
                    '</td><td>'+pctile('initial_http_p50','s')+' / '+pctile('initial_http_p95','s')+
                    '</td><td>'+pctile('jev_provider_p50_ms','ms')+' / '+pctile('jev_provider_p95_ms','ms')+'</td></tr>')
    return ('<section class="review-section"><h2>운영 실행 신뢰도</h2><p><strong>최초 시도 execution gate: '+initial_gate+
            '</strong> · 최초 시도 오류가 하나라도 있으면 FAIL입니다. 최종 유효점수 품질 gate와 별도 판정입니다.</p>'+
            '<div class="review-table-wrap"><table><thead><tr><th scope="col">단계</th><th scope="col">첫 시도 성공</th>'+
            '<th scope="col">첫 시도 오류</th><th scope="col">복구 회차</th><th scope="col">재시도 대상</th>'+
            '<th scope="col">복구 성공</th><th scope="col">최종 평가 완료</th>'+
            '<th scope="col">총 HTTP 시도</th><th scope="col">Jev 사용량 (응답 보고값)</th><th scope="col">HTTP p50 / p95</th>'+
            '<th scope="col">Jev p50 / p95</th></tr></thead><tbody>'+''.join(rows)+'</tbody></table></div>'+
            '<p class="review-foot">비용은 입력된 응답 보고값만 표시합니다. 미보고 비용 호출은 별도로 셉니다. 재시도 응답의 사용량 중복 여부는 원본 집계 계약에 따릅니다.</p></section>',
            initial_gate)


def _metric_rows(baseline, test):
    rows = []
    ranking = [('Source Hit@5','source_any_hit_at_5'), ('Chunk Hit@5','chunk_any_hit_at_5'),
               ('Chunk MRR@5','chunk_mrr_at_5'), ('모든 근거 group Hit@5','chunk_all_groups_hit_at_5')]
    for label, key in ranking:
        rows.append((label, _ranking(baseline,key), _ranking(test,key), key != 'chunk_mrr_at_5', '높을수록 좋음'))
    for label, key in [('ROC-AUC','roc_auc'),('Average precision','average_precision')]:
        rows.append((label, baseline.get('score_metrics',{}).get(key), test.get('score_metrics',{}).get(key),False,'높을수록 좋음'))
    for label, key, direction in [('Supported TPR','supported_tpr','≥ 90%'),('OOD FPR','ood_fpr','≤ 10%'),
                                  ('Grey-zone FPR','near_boundary_fpr','≤ 20%'),('In-domain missing FPR','in_domain_missing_fpr','낮을수록 좋음')]:
        rows.append((label, baseline.get('test_metrics',{}).get(key),test.get('test_metrics',{}).get(key),True,direction))
    rows.append(('모호 질문 지원 점수 초과율', baseline.get('test_metrics',{}).get('ambiguous_predicted_supported_rate'),
                 test.get('test_metrics',{}).get('ambiguous_predicted_supported_rate'), True,
                 '참고 · 실제 clarify 행동 미평가'))
    return ''.join('<tr><th scope="row">'+html.escape(label)+'</th><td>'+_number(a,pct)+'</td><td>'+_number(b,pct)
                   +'</td><td>'+html.escape(direction)+'</td></tr>' for label,a,b,pct,direction in rows)


def _cases(path, summary):
    if path is None: return []
    path=Path(path); opener=gzip.open if path.suffix=='.gz' else open
    records=[]; digest=hashlib.sha256();valid_count=0
    with opener(path, 'rb') as stream:
        for line in stream:
            digest.update(line)
            try: row=json.loads(line)
            except (ValueError,UnicodeDecodeError): raise ValueError('journal_invalid_json') from None
            if row.get('event')!='case_result': continue
            advice=row.get('result',{}).get('evidence_advice',{}) if isinstance(row.get('result'),dict) else {}
            assessed=advice.get('status')=='assessed'
            if assessed:
                score=advice.get('support_score')
                if (advice.get('schema_version')!='jev-evidence-advice/v1' or advice.get('advisory_only') is not True
                        or isinstance(score,bool) or not isinstance(score,(int,float)) or not math.isfinite(score)
                        or not 0<=score<=1 or row.get('status')!='ok' or row.get('score')!=score):
                    raise ValueError('journal_advice_mismatch')
                valid_count+=1
            elif row.get('status')!='error' or row.get('score') is not None or advice.get('support_score') is not None:
                raise ValueError('journal_advice_mismatch')
            # Explicit allowlist: never serialize result/items/text/quote/prompt.
            records.append({
                'id':row.get('case_id'), 'query':row.get('query'), 'language':row.get('language'),
                'difficulty':row.get('difficulty'), 'boundary':row.get('boundary_type'),
                'expected':row.get('answerability'), 'status':row.get('status'),
                'score':row.get('score'), 'choice':advice.get('choice'),
                'latency':row.get('latency_seconds'),
            })
            if len(records)>500:raise ValueError('journal_count_exceeded')
    if len(records)!=500 or len({x['id'] for x in records})!=500:
        raise ValueError('incomparable_report_journal_count')
    if digest.hexdigest()!=summary.get('journal_sha256'):
        raise ValueError('journal_sha256_mismatch')
    if valid_count!=summary['success_count'] or len(records)-valid_count!=summary['error_count']:
        raise ValueError('journal_assessed_count_mismatch')
    return records


def build_report(baseline_path, calibration_path, test_path, output_path, *, journal_path=None, threshold_path=None,
                 operations_path=None):
    baseline, calibration, test = map(_load, (baseline_path, calibration_path, test_path))
    _validate(baseline, calibration, test)
    operations = _operations(operations_path, calibration, test)
    operations_html, initial_gate = _operations_table(operations)
    cases=_cases(journal_path,test)
    threshold_verified=False
    if threshold_path is not None:
        if (_load(threshold_path)!=test['threshold'] or
                hashlib.sha256(Path(threshold_path).read_bytes()).hexdigest()!=test.get('threshold_file_sha256')):
            raise ValueError('incomparable_report_threshold_file')
        threshold_verified=True
    template=(ROOT/'web/reports/retrieval-evaluation-template.html').read_text()
    style=re.search(r'<style>(.*?)</style>',template,re.S).group(1)
    title='Jev, under review · DSE Knowledge'
    gate='PASS' if _gate(test,calibration, bool(cases) and threshold_verified) else 'FAIL'
    valid=f"{test['success_count']} / {test['case_count']}"
    metrics=_metric_rows(baseline,test)
    threshold=test.get('threshold',{}).get('threshold')
    scored=test.get('score_metrics',{}).get('scored_binary_denominator')
    hashes=''.join('<tr><th scope="row">'+html.escape(Path(path).name)+'</th><td class="mono">'
                   +hashlib.sha256(Path(path).read_bytes()).hexdigest()+'</td></tr>'
                   for path in (baseline_path,calibration_path,test_path))
    corpus=html.escape(test['corpus_manifest_sha256'])
    case_hash=html.escape(test['case_manifest_sha256'])
    latencies=sorted(x['latency'] for x in cases if x.get('status')=='ok'
                     and isinstance(x.get('latency'),(int,float)) and math.isfinite(x['latency']))
    latency_text=(f"성공 HTTP 요청 기준 p50 {statistics.median(latencies):.2f}s · p95 {latencies[max(0,math.ceil(len(latencies)*.95)-1)]:.2f}s"
                  if latencies else '성공 HTTP 응답 latency 미평가')
    partial_run = calibration['error_count'] > 0 or test['error_count'] > 0
    partial_notice = ''
    if partial_run:
        partial_notice = ('<section class="review-section"><div class="review-note"><p><strong>전체 500건 비교 불완전 · valid-assessed 조건부 지표</strong> · '
                          f"Calibration 오류 {calibration['error_count']} / 100, Test 오류 {test['error_count']} / 500입니다.</p>"
                          '<p>HTTP/검색 실패는 ranking이 누락될 수 있지만 advisor-only 오류는 정상 검색 ranking을 보존합니다. '
                          '실패 원인을 구분해 해석해야 하며, Hit/MRR 변화만으로 Jev 효과를 단정할 수 없습니다. '
                          'ROC-AUC, AP와 subgroup FPR의 유효 분모는 서로 다를 수 있습니다. 오류 응답의 빠른 반환은 latency 개선으로 계산하지 않습니다.</p></div></section>')
    # HTML script-breaking sequences are escaped even in previously public queries.
    data=json.dumps({'cases':cases,'threshold':threshold},ensure_ascii=False,allow_nan=False).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    document='''<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="light">
<title>'''+title+'''</title><style>'''+style+'''
main{padding-top:40px;padding-bottom:64px}.review-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:20px}.review-card{padding:24px;background:white;border:1px solid var(--line);border-radius:12px}.review-card strong{display:block;font:34px/1.2 var(--serif);margin:8px 0}.review-section{margin:36px 0}.review-section h2{font:normal 30px/1.2 var(--serif)}.review-table-wrap{overflow-x:auto;background:white;border:1px solid var(--line);border-radius:12px}table{border-collapse:collapse;width:100%;font-size:14px}th,td{text-align:left;padding:13px 18px;border-bottom:1px solid var(--line);vertical-align:top}thead th{background:#edf3fa}tbody th{font-weight:600}td.mono{font-family:var(--mono);overflow-wrap:anywhere;font-size:12px}.review-note{border-left:4px solid var(--blue);padding:14px 20px;background:var(--light)}.review-controls{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:16px}.review-controls input{flex:1;min-width:200px;padding:8px}.review-controls button,.review-controls select{padding:8px 14px;border:1px solid var(--line);border-radius:6px;background:white}.review-query{max-width:600px;overflow-wrap:anywhere}.review-foot{font-size:13px;color:var(--muted)}@media(max-width:700px){.review-grid{grid-template-columns:1fr}.hero{grid-template-columns:1fr;gap:12px}th,td{padding:10px}}
</style></head><body><a class="skip" href="#main">본문으로</a><header><div class="wrap"><div class="brand"><span>DSE KNOWLEDGE / EVIDENCE REVIEW</span><a href="/">Workbench</a></div><div class="hero"><div><div class="eyebrow">2026.10.27 · JEV 1.13 · REGRESSION 500</div><h1>관련성 다음에,<br>조건을 묻다.</h1><p>기존 contextual retrieval과 Qwen reranker를 유지하고, Jev의 발췌문 기반 근거 검토를 추가한 비교입니다.</p></div><div class="hero-note"><strong>'''+gate+'''</strong><span>최종 유효점수 품질 gate</span></div></div></div></header>
<main id="main" class="wrap"><div class="review-grid"><article class="review-card"><span>실제 Jev 유효 평가</span><strong>'''+valid+'''</strong><span>오류·skip은 근거 부재로 처리하지 않음</span></article><article class="review-card"><span>Calibration → test</span><strong>100 → 500</strong><span>calibration threshold를 고정한 뒤 test 실행</span></article><article class="review-card"><span>Test 응답 지연</span><strong style="font:20px/1.5 var(--mono)">'''+html.escape(latency_text)+'''</strong><span>성공 HTTP 응답 기준 latency; 오류 응답은 제외</span></article></div>
'''+partial_notice+'''
'''+operations_html+'''
<section class="review-section"><h2>비교 결과</h2><p>기존 점수는 reranker relevance, 새 점수는 Jev direct-support 확률입니다. 두 값 모두 실제 생성 답변의 정답 확률이나 답변 허가를 뜻하지 않습니다.</p><div class="review-table-wrap"><table><thead><tr><th scope="col">지표</th><th scope="col">기존 contextual + Qwen 8B</th><th scope="col">동일 검색 + Jev advice</th><th scope="col">판정 기준</th></tr></thead><tbody>'''+metrics+'''</tbody></table></div><p class="review-foot">유효 binary score 조건부 분모: '''+str(scored)+''' / 전체 binary 480. Ambiguous 20건은 기존 binary 평가에서 제외합니다. Jev는 검색 순위를 변경하지 않으며 Hit/MRR 차이가 생기면 검색 재실행 변동을 별도로 확인해야 합니다.</p></section>
<section class="review-section"><h2>해석의 범위</h2><div class="review-note"><p><strong>500건은 검색 근거 판별의 회귀 평가입니다.</strong> 실제 생성 답변 500개의 의미 정확도나 HAT 설계·성능 검증을 측정한 결과가 아닙니다. 공개된 기존 test set이므로 새로운 독립 holdout 결과로 해석하지 않습니다.</p><p>조건이 빠진 경우와 명시적으로 다른 경우를 구분합니다. 발췌문에 근거가 없다는 사실은 전체 corpus나 현실에서 불가능하다는 뜻이 아닙니다. Jev는 citation과 필수 검증 규칙을 대체하지 않습니다.</p></div><p>Jev test threshold: <code>'''+html.escape(str(threshold))+'''</code>. provider 오류·미평가가 있으면 gate는 FAIL이며 semantic 지표는 valid-assessed 표본에 대한 조건부 결과입니다. 실패를 정상 0점으로 바꾸지 않습니다.</p></section>
<section class="review-section"><h2>500개 질문 탐색</h2><p>질문·정답 유형·검토 선택·score를 확인합니다. 원문·검색 excerpt·prompt·credential은 포함하지 않습니다.</p><div class="review-controls"><input id="query-filter" type="search" aria-label="질문 검색" placeholder="질문 또는 case ID 검색"><select id="boundary-filter" aria-label="질문 유형"><option value="">모든 유형</option></select><select id="language-filter" aria-label="언어"><option value="">모든 언어</option></select><select id="difficulty-filter" aria-label="난이도"><option value="">모든 난이도</option></select><button id="previous">이전</button><button id="next">다음</button><span id="case-count" aria-live="polite"></span></div><div class="review-table-wrap"><table><thead><tr><th scope="col">질문</th><th scope="col">유형 / 기대 상태</th><th scope="col">Jev 선택</th><th scope="col">Score / 실행</th></tr></thead><tbody id="case-rows"></tbody></table></div></section>
<section class="review-section"><h2>재현과 provenance</h2><p>Corpus manifest <code>'''+corpus+'''</code></p><p>Test manifest <code>'''+case_hash+'''</code></p><div class="review-table-wrap"><table><thead><tr><th scope="col">입력 summary</th><th scope="col">SHA-256</th></tr></thead><tbody>'''+hashes+'''</tbody></table></div><p><a href="https://github.com/jimmylegendary/dse-knowledge/tree/main/research/eval500">공개 test set·결과</a> · <a href="/static/reports/retrieval-evaluation-2026-10-26.html">기존 4구성 비교</a></p></section></main>
<script id="review-data" type="application/json">'''+data+'''</script><script>
"use strict";const data=JSON.parse(document.getElementById("review-data").textContent);let page=0;const size=25,query=document.getElementById("query-filter"),filter=document.getElementById("boundary-filter"),language=document.getElementById("language-filter"),difficulty=document.getElementById("difficulty-filter"),rows=document.getElementById("case-rows");for(const [select,key,label] of [[filter,"boundary","none"],[language,"language","unknown"],[difficulty,"difficulty","unknown"]])for(const v of [...new Set(data.cases.map(x=>x[key]||label))].sort()){const o=document.createElement("option");o.value=v;o.textContent=v;select.append(o)}function render(){const q=query.value.trim().toLowerCase();const list=data.cases.filter(x=>(!q||String(x.query+" "+x.id).toLowerCase().includes(q))&&(!filter.value||(x.boundary||"none")===filter.value)&&(!language.value||(x.language||"unknown")===language.value)&&(!difficulty.value||(x.difficulty||"unknown")===difficulty.value));page=Math.min(page,Math.max(0,Math.ceil(list.length/size)-1));rows.replaceChildren();for(const x of list.slice(page*size,(page+1)*size)){const row=document.createElement("tr");for(const value of [x.query+" ["+x.id+"]",(x.boundary||"none")+" / "+x.expected,x.choice||"미평가",(typeof x.score==="number"?x.score.toFixed(4):"미평가")+" / "+x.status]){const c=document.createElement("td");c.textContent=value;c.className="review-query";row.append(c)}rows.append(row)}document.getElementById("case-count").textContent=list.length+"건 · "+(page+1)+" / "+Math.max(1,Math.ceil(list.length/size));document.getElementById("previous").disabled=page===0;document.getElementById("next").disabled=(page+1)*size>=list.length}for(const select of [query,filter,language,difficulty])select.addEventListener(select===query?"input":"change",()=>{page=0;render()});document.getElementById("previous").addEventListener("click",()=>{page--;render()});document.getElementById("next").addEventListener("click",()=>{page++;render()});render();
</script></body></html>'''
    Path(output_path).parent.mkdir(parents=True,exist_ok=True)
    Path(output_path).write_text(document)
    return {'output':str(output_path),'sha256':hashlib.sha256(document.encode()).hexdigest(),'cases':len(cases),
            'quality_gate':gate,'initial_execution_gate':initial_gate}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('baseline','calibration','test','output'): parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--journal',type=Path,required=True)
    parser.add_argument('--threshold',type=Path,required=True)
    parser.add_argument('--operations',type=Path)
    args=parser.parse_args()
    print(json.dumps(build_report(args.baseline,args.calibration,args.test,args.output,journal_path=args.journal,
                                  threshold_path=args.threshold,operations_path=args.operations),ensure_ascii=False))


if __name__=='__main__': main()
