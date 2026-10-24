import pytest
from dse_knowledge.decisions import validate_decision

def result():return dict(status='evidence_supported',answer='x',findings=[],gaps=[],next_steps=[],proposals=[])

def test_empty_success_downgraded():
    assert validate_decision(result(),[])['status']=='insufficient_evidence'

def test_unknown_citation_rejected():
    r=result();r['findings']=[dict(statement='x',citations=['invented'],confidence='source_assertion')]
    with pytest.raises(ValueError):validate_decision(r,[])

def test_source_assertion_does_not_become_physical_validation():
    r=result();r['findings']=[dict(statement='x',citations=['c1'],confidence='source_assertion')]
    r=validate_decision(r,[dict(chunk_id='c1')])
    assert 'unverified' in r['scope']
