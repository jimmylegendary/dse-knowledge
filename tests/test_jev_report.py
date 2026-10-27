"""Public Jev report must reject incomparable runs and never copy source bodies."""
from pathlib import Path
import importlib.util
import hashlib
import json
import pytest


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/build-jev-evaluation-report.py'


def load_builder():
    spec = importlib.util.spec_from_file_location('jev_report_builder', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def summaries(tmp_path):
    base = dict(stage='test', case_count=500, success_count=500, error_count=0,
                case_manifest_sha256='a'*64, corpus_manifest_sha256='b'*64,
                case_contract_sha256='e'*64, policy_version='retrieval-policy/v2.2',
                retrieval_mode='contextual_rerank', score_name='max_reranker_relevance_proxy',
                request={'category':'','limit':12,'purpose':'auto','retrieval_mode':'contextual_rerank'},
                rankings={'items':{'denominator':300,'metrics':{'chunk_any_hit_at_5':.95,'chunk_mrr_at_5':.88}}},
                score_metrics={'roc_auc':.93,'average_precision':.94,'scored_binary_denominator':480},
                test_metrics={'supported_tpr':.95,'near_boundary_fpr':.39,'ood_fpr':0.,'in_domain_missing_fpr':.2},
                quality_gates={'passed':False}, threshold={'threshold':.98})
    test = json.loads(json.dumps(base))
    test.update(score_name='jev_direct_support_proxy', evidence_advice='jev')
    test['request']['evidence_advice']='jev'
    test['private_source_body']='PRIVATE SOURCE MUST NOT APPEAR'
    cal = dict(test, stage='calibration', case_count=100, success_count=100,
               case_manifest_sha256='c'*64)
    threshold = dict(threshold=.5, calibration_case_manifest_sha256='c'*64,
                     case_contract_sha256='e'*64, policy_version='retrieval-policy/v2.2',
                     corpus_manifest_sha256='b'*64, retrieval_mode='contextual_rerank',
                     evidence_advice='jev',score_name='jev_direct_support_proxy')
    test['threshold']=dict(threshold);cal['threshold']=dict(threshold)
    threshold_path=tmp_path/'threshold.json';threshold_path.write_text(json.dumps(threshold))
    test['threshold_file_sha256']=hashlib.sha256(threshold_path.read_bytes()).hexdigest()
    paths=[]
    for name, data in [('baseline',base),('calibration',cal),('test',test)]:
        path=tmp_path/(name+'.json');path.write_text(json.dumps(data));paths.append(path)
    return paths


def test_report_rejects_different_corpus(tmp_path):
    paths=summaries(tmp_path)
    data=json.loads(paths[2].read_text());data['corpus_manifest_sha256']='d'*64
    paths[2].write_text(json.dumps(data))
    with pytest.raises(ValueError,match='incomparable'):
        load_builder().build_report(*paths, tmp_path/'report.html')


def test_report_rejects_nonfinite_metrics(tmp_path):
    paths=summaries(tmp_path)
    data=json.loads(paths[2].read_text());data['score_metrics']['roc_auc']=float('nan')
    paths[2].write_text(json.dumps(data))
    with pytest.raises(ValueError,match='nonfinite'):
        load_builder().build_report(*paths, tmp_path/'report.html')


def test_report_shows_failed_gate_and_excludes_unknown_source_fields(tmp_path):
    paths=summaries(tmp_path);output=tmp_path/'report.html'
    result=load_builder().build_report(*paths, output)
    text=output.read_text()
    assert '39.00%' in text
    assert result['quality_gate']=='FAIL'
    assert 'PRIVATE SOURCE MUST NOT APPEAR' not in text
    assert '500' in text and '실제 생성 답변' in text


def test_report_does_not_turn_provider_failure_into_no_support(tmp_path):
    paths=summaries(tmp_path)
    data=json.loads(paths[2].read_text());data.update(success_count=499,error_count=1)
    data['quality_gates']={'passed':True}
    paths[2].write_text(json.dumps(data));output=tmp_path/'report.html'
    result=load_builder().build_report(*paths, output)
    text=output.read_text()
    assert result['quality_gate']=='FAIL'
    assert '499 / 500' in text
    assert '조건부' in text


def test_report_rejects_different_calibration_threshold(tmp_path):
    paths=summaries(tmp_path)
    data=json.loads(paths[1].read_text());data['threshold']['threshold']=.9
    paths[1].write_text(json.dumps(data))
    with pytest.raises(ValueError,match='incomparable'):
        load_builder().build_report(*paths,tmp_path/'report.html')


def test_report_rejects_contradictory_request_advice_mode(tmp_path):
    paths=summaries(tmp_path)
    data=json.loads(paths[2].read_text());data['request']['evidence_advice']='off'
    paths[2].write_text(json.dumps(data))
    with pytest.raises(ValueError,match='incomparable'):
        load_builder().build_report(*paths,tmp_path/'report.html')


def test_report_reads_runner_advice_mode_with_status_counts(tmp_path):
    paths=summaries(tmp_path)
    for path, count in [(paths[1],100),(paths[2],500)]:
        data=json.loads(path.read_text())
        data['evidence_advice']={'mode':'jev','status_counts':{'assessed':count},'assessed_count':count,'unassessed_count':0}
        path.write_text(json.dumps(data))
    result=load_builder().build_report(*paths,tmp_path/'report.html')
    assert result['quality_gate']=='FAIL'


def test_report_rejects_incomplete_baseline(tmp_path):
    paths=summaries(tmp_path)
    data=json.loads(paths[0].read_text());data.update(success_count=499,error_count=1)
    paths[0].write_text(json.dumps(data))
    with pytest.raises(ValueError,match='incomparable'):
        load_builder().build_report(*paths,tmp_path/'report.html')


def test_report_cannot_pass_with_failed_calibration(tmp_path):
    paths=summaries(tmp_path)
    cal=json.loads(paths[1].read_text());cal.update(success_count=99,error_count=1)
    paths[1].write_text(json.dumps(cal))
    test=json.loads(paths[2].read_text());test['quality_gates']={'passed':True}
    paths[2].write_text(json.dumps(test));out=tmp_path/'report.html'
    result=load_builder().build_report(*paths,out)
    assert result['quality_gate']=='FAIL'


def write_journal(tmp_path, paths, *, hidden_failure=False, hidden_failure_count=1,
                  latency_success=None, latency_error=None):
    records=[]
    for i in range(500):
        advice={'schema_version':'jev-evidence-advice/v1','advisory_only':True,
                'status':'assessed','support_score':.9,'choice':'direct_support_candidate'}
        failed=hidden_failure and i<hidden_failure_count
        if failed: advice.update(status='unavailable',support_score=None)
        record={'event':'case_result','case_id':str(i),'query':'public diagnostic query',
                'status':'error' if failed else 'ok','score':None if failed else .9,
                'result':{'evidence_advice':advice}}
        if latency_success is not None:
            record['latency_seconds']=latency_error if failed else latency_success
        records.append(record)
    journal=tmp_path/'journal.jsonl';journal.write_text(''.join(json.dumps(x)+'\n' for x in records))
    test=json.loads(paths[2].read_text());test['journal_sha256']=hashlib.sha256(journal.read_bytes()).hexdigest()
    paths[2].write_text(json.dumps(test))
    return journal


def test_report_rejects_journal_drift(tmp_path):
    paths=summaries(tmp_path);journal=write_journal(tmp_path,paths)
    journal.write_text(journal.read_text()+'\n')
    with pytest.raises(ValueError,match='journal'):
        load_builder().build_report(*paths,tmp_path/'report.html',journal_path=journal)


def test_report_rejects_http_success_with_unavailable_advice(tmp_path):
    paths=summaries(tmp_path);journal=write_journal(tmp_path,paths,hidden_failure=True)
    with pytest.raises(ValueError,match='journal'):
        load_builder().build_report(*paths,tmp_path/'report.html',journal_path=journal)


def test_partial_report_labels_conditional_metrics_and_uses_success_latency_only(tmp_path):
    paths=summaries(tmp_path)
    test=json.loads(paths[2].read_text());test.update(success_count=400,error_count=100)
    test['quality_gates']={'passed':True};paths[2].write_text(json.dumps(test))
    journal=write_journal(tmp_path,paths,hidden_failure=True,hidden_failure_count=100,
                          latency_success=2.0,latency_error=100.0)
    out=tmp_path/'report.html';result=load_builder().build_report(*paths,out,journal_path=journal)
    text=out.read_text()
    assert result['quality_gate']=='FAIL'
    assert '전체 500건 비교 불완전' in text
    assert 'valid-assessed 조건부 지표' in text
    assert '성공 HTTP 요청 기준 p50 2.00s · p95 2.00s' in text
    assert '오류 응답의 빠른 반환은 latency 개선으로 계산하지 않습니다' in text
    assert '실패 case는 ranking이 missing' in text
    assert 'ROC-AUC, AP와 subgroup FPR의 유효 분모는 서로 다를 수 있습니다' in text


def test_report_pass_requires_validated_journal_and_threshold(tmp_path):
    paths=summaries(tmp_path);journal=write_journal(tmp_path,paths)
    test=json.loads(paths[2].read_text());test['quality_gates']={'passed':True}
    paths[2].write_text(json.dumps(test));out=tmp_path/'report.html'
    result=load_builder().build_report(*paths,out,journal_path=journal,threshold_path=tmp_path/'threshold.json')
    assert result['quality_gate']=='PASS'


def operations(tmp_path):
    common = dict(initial_case_count=100, initial_success_count=100,
                  initial_error_count=0, final_assessed_count=100,
                  recovery_rounds=[], total_http_attempts=100,
                  jev_usage={'reported_input_tokens':12000,'reported_cost_usd':.02,
                             'reported_provider_calls':100,'unreported_cost_calls':0},
                  latency={'initial_http_p50':1.2,'initial_http_p95':2.4,
                           'jev_provider_p50_ms':200,'jev_provider_p95_ms':500})
    test = dict(common, initial_case_count=500, initial_success_count=496,
                initial_error_count=4, final_assessed_count=500,
                recovery_rounds=[{'retried_cases':2,'success_count':1,'error_count':1,
                                  'parent_journal_sha256':'a'*64,'journal_sha256':'c'*64},
                                 {'retried_cases':3,'success_count':3,'error_count':0,
                                  'parent_journal_sha256':'c'*64,'journal_sha256':'b'*64}],
                total_http_attempts=505,
                jev_usage={'reported_input_tokens':60000,'reported_cost_usd':.12,
                           'reported_provider_calls':505,'unreported_cost_calls':4})
    value={'schema_version':'jev-evaluation-operations/v1',
           'phases':{'calibration':common,'test':test},
           'source_body':'PRIVATE OPERATIONS BODY MUST NOT APPEAR'}
    path=tmp_path/'operations.json';path.write_text(json.dumps(value));return path


def test_report_separates_first_attempt_failure_from_final_quality_pass(tmp_path):
    paths=summaries(tmp_path);journal=write_journal(tmp_path,paths)
    test=json.loads(paths[2].read_text());test['quality_gates']={'passed':True}
    paths[2].write_text(json.dumps(test))
    ops=operations(tmp_path);ops_data=json.loads(ops.read_text())
    ops_data['phases']['test']['recovery_rounds'][1]['journal_sha256']=test['journal_sha256']
    ops.write_text(json.dumps(ops_data));out=tmp_path/'report.html'
    result=load_builder().build_report(*paths,out,journal_path=journal,
        threshold_path=tmp_path/'threshold.json',operations_path=ops)
    text=out.read_text()
    assert result['quality_gate']=='PASS'
    assert result['initial_execution_gate']=='FAIL'
    assert '최종 유효점수 품질 gate' in text
    assert '496 / 500' in text and '505' in text and '복구 성공' in text
    assert 'source_body' not in text and 'PRIVATE OPERATIONS BODY MUST NOT APPEAR' not in text


def test_report_without_operations_marks_first_attempt_unassessed(tmp_path):
    paths=summaries(tmp_path);out=tmp_path/'report.html'
    load_builder().build_report(*paths,out)
    text=out.read_text()
    assert '최초 시도 신뢰도 미평가' in text
    assert '첫 시도 성공률 100%' not in text


def test_report_exposes_ambiguous_reference_metric_and_case_filters(tmp_path):
    paths=summaries(tmp_path)
    for path in (paths[0],paths[2]):
        data=json.loads(path.read_text())
        data['test_metrics']['ambiguous_predicted_supported_rate']=.25
        path.write_text(json.dumps(data))
    out=tmp_path/'report.html';load_builder().build_report(*paths,out)
    text=out.read_text()
    assert '모호 질문 지원 점수 초과율' in text
    assert '참고 · 실제 clarify 행동 미평가' in text
    assert 'id="language-filter"' in text and 'id="difficulty-filter"' in text


def test_report_rejects_malformed_operations_counts(tmp_path):
    paths=summaries(tmp_path);ops=operations(tmp_path)
    value=json.loads(ops.read_text());value['phases']['test']['initial_success_count']=501
    ops.write_text(json.dumps(value))
    with pytest.raises(ValueError,match='operations'):
        load_builder().build_report(*paths,tmp_path/'report.html',operations_path=ops)
