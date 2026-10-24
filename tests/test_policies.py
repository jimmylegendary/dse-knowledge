import pytest
from dse_knowledge.policies import compare_experiments


def exp(metrics,cohort='a',method='measured'):
    return {'cohort':cohort,'method':method,'metrics':metrics}


def metric(value,unit='ms',name='ttft',direction='min'):
    return dict(name=name,value=value,unit=unit,direction=direction)


def test_unit_equivalence_and_missing_metrics():
    b=exp([metric(1000)])
    assert compare_experiments(b,exp([metric(1,'s')]))['dominance']=='equivalent'
    assert compare_experiments(b,exp([]))['status']=='incomplete'


def test_cohort_and_method_must_match():
    b=exp([metric(2)])
    assert compare_experiments(b,exp([metric(1)],cohort='b'))['status']=='not_comparable'
    assert compare_experiments(b,exp([metric(1)],method='analytical'))['status']=='not_comparable'


def test_tradeoff_is_not_scalarized():
    b=exp([metric(10),metric(100,'W','power')])
    c=exp([metric(9),metric(110,'W','power')])
    assert compare_experiments(b,c)['dominance']=='tradeoff'


def test_nonfinite_is_rejected():
    with pytest.raises(ValueError): compare_experiments(exp([metric(1)]),exp([metric(float('nan'))]))


def test_thirteenth_mandatory_rule_cannot_drop_at_top_k():
    from dse_knowledge.policies import evaluate_required_rules
    rules=[{'id':str(i),'value':1,'operator':'<=','limit':2,'unit':'W'} for i in range(13)]
    rules[-1]['value']=3
    report=evaluate_required_rules(rules)
    assert report['status']=='reject' and len(report['rules'])==13
    assert report['rules'][-1]['status']=='fail'


def test_unknown_rule_is_not_passed():
    from dse_knowledge.policies import evaluate_required_rules
    assert evaluate_required_rules(['must_support_tensorcore'])['status']=='incomplete'


def test_malformed_operator_is_unknown_without_crashing():
    from dse_knowledge.policies import evaluate_required_rules
    rule={'value':1,'operator':['<='],'limit':2,'unit':'W'}
    assert evaluate_required_rules([rule])['status']=='incomplete'
