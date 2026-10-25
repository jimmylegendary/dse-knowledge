import hashlib
import pytest
from dse_knowledge.quality import ValidatedCache, claim_limit


def test_cache_is_revision_model_schema_and_operation_bound(tmp_path):
    cache=ValidatedCache(tmp_path)
    key={'revision':'a'*64,'model':'m','schema':'s1','operation':'context'}
    value={'items':[1]}
    cache.put(key,value,{'usage':{'input_tokens':42}},lambda v: v['items']==[1])
    hit=cache.get(key,lambda v: v['items']==[1])
    assert hit['value']==value
    assert hit['metadata']['usage']=={}
    assert hit['metadata']['cache_hit'] is True
    assert cache.get({**key,'revision':'b'*64},lambda v: True) is None
    assert cache.get({**key,'schema':'s2'},lambda v: True) is None


def test_unvalidated_result_cannot_be_cached(tmp_path):
    cache=ValidatedCache(tmp_path)
    with pytest.raises(ValueError,match='validation'):
        cache.put({'operation':'x'},{'x':1},{},lambda v: False)
    assert list(tmp_path.glob('*.json'))==[]


def test_cache_revalidates_and_detects_content_tampering(tmp_path):
    import json
    cache=ValidatedCache(tmp_path); key={'operation':'x'}
    cache.put(key,{'x':1},{},lambda v: True)
    assert cache.get(key,lambda v: False) is None
    path=next(tmp_path.glob('*.json'));payload=json.loads(path.read_text())
    payload['value']={'x':2};path.write_text(json.dumps(payload))
    assert cache.get(key,lambda v: True) is None


def test_role_depth_policy_does_not_force_navigation_claims():
    assert [claim_limit(x) for x in ('core_technical','supporting_method','integration_operations','source_navigation','out_of_scope','unclassified')]==[3,2,1,0,0,0]
