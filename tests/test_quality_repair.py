import json
from copy import deepcopy
import pytest
from dse_knowledge.quality import GroundedChat
from dse_knowledge.providers import CODEX_MAX_PROMPT_BYTES,CODEX_MAX_PROMPT_CHARS


def test_one_bounded_repair_keeps_actual_attempt_usage_and_requires_literal_evidence():
    doc={'material':{'id':'m'},'revision':{'sha256':'a'*64},'text':'Measured latency is 6.4 ms on the selected test.',
         'chunks':[{'id':'c','text':'Measured latency is 6.4 ms on the selected test.','start':0,'end':46}]}
    doc['chunks'][0]['end']=len(doc['text'])
    context={'schema_version':'claim-context/v1','parameters':[{'name':'latency','value':99,'unit':'ms','evidence':{'chunk_id':'c','quote':doc['text']}}],'conditions':[],'source_scope_note':'Only this test.'}
    bad={'claims':[{'claim_id':'a','context':context}]};good=deepcopy(bad);good['claims'][0]['context']['parameters'][0]['value']=6.4
    class Chat:
        last_metadata={}
        def __init__(self):self.calls=[]
        def complete(self,prompt,schema):
            self.calls.append(prompt);self.last_metadata={'usage':{'input_tokens':10,'output_tokens':2},'duration_seconds':1,'tool_calls':0}
            return bad if len(self.calls)==1 else good
        def close(self):pass
    raw=Chat();chat=GroundedChat(raw,doc)
    assert chat.complete('Untrusted source',{})==good
    assert len(raw.calls)==2
    assert 'claim_context_value_not_literal' in raw.calls[1]
    assert raw.calls[1].startswith('Untrusted source')
    assert '"value":99' in raw.calls[1]
    assert chat.last_metadata['usage']['input_tokens']==20
    assert chat.last_metadata['provider_attempt_count']==2


def test_failed_repair_is_returned_to_strict_caller_validation_without_silent_emptying():
    class Chat:
        last_metadata={}
        def __init__(self):self.calls=0
        def complete(self,*args):self.calls+=1;return {'claims':[{'claim_id':'c','context':{'bad':'shape'}}]}
    raw=Chat();wrapped=GroundedChat(raw,{'material':{'id':'m'}})
    assert wrapped.complete('source',{})['claims'][0]['context']=={'bad':'shape'}
    assert raw.calls==2

def test_large_invalid_context_is_omitted_from_bounded_repair_and_usage_counts_both_attempts():
    quote='The source gives a technical observation without numeric values. '*18
    doc={'material':{'id':'m'},'revision':{'sha256':'a'*64},'text':quote,
         'chunks':[{'id':'c','text':quote,'start':0,'end':len(quote)}]}
    parameter={'name':'latency','value':99,'unit':'ms','evidence':{'chunk_id':'c','quote':quote}}
    bad={'claims':[{'claim_id':'a','context':{'schema_version':'claim-context/v1',
        'parameters':[parameter.copy() for _ in range(32)],'conditions':[],
        'source_scope_note':'Only this source.'}}]}
    good={'claims':[{'claim_id':'a','context':{'schema_version':'claim-context/v1',
        'parameters':[],'conditions':[],'source_scope_note':'No literal parameter value was available.'}}]}
    assert len(json.dumps(bad,ensure_ascii=False))>4000
    class Chat:
        def __init__(self):self.calls=[];self.last_metadata={}
        def complete(self,prompt,schema):
            self.calls.append(prompt)
            self.last_metadata={'usage':{'input_tokens':10*len(self.calls),'output_tokens':2},
                                'duration_seconds':1,'tool_calls':0}
            return bad if len(self.calls)==1 else good
    raw=Chat();wrapped=GroundedChat(raw,doc)
    assert wrapped.complete('Source chunks were supplied above.',{})==good
    assert len(raw.calls)==2
    repair=raw.calls[1]
    assert 'Previous response omitted' in repair
    assert quote not in repair
    assert len(repair)<=CODEX_MAX_PROMPT_CHARS
    assert len(repair.encode('utf-8'))<=CODEX_MAX_PROMPT_BYTES
    assert wrapped.last_metadata['usage']=={'input_tokens':30,'output_tokens':4}
    assert wrapped.last_metadata['provider_attempt_count']==2
    assert len(wrapped.last_metadata['provider_attempts'])==2

@pytest.mark.parametrize('prompt_kind',['character_limit','utf8_byte_limit'])
def test_repair_is_skipped_when_original_prompt_plus_instruction_would_exceed_provider_limit(prompt_kind):
    if prompt_kind=='character_limit':
        prompt='x'*CODEX_MAX_PROMPT_CHARS
    else:
        prompt='한'*34_050
        assert len(prompt)<CODEX_MAX_PROMPT_CHARS
        assert len(prompt.encode('utf-8'))<CODEX_MAX_PROMPT_BYTES
    invalid={'claims':[{'claim_id':'a','context':{'bad':'shape'}}]}
    class Chat:
        last_metadata={}
        def __init__(self):self.calls=[]
        def complete(self,request,schema):
            self.calls.append(request)
            self.last_metadata={'usage':{'input_tokens':7},'duration_seconds':0.5}
            return invalid
    raw=Chat();wrapped=GroundedChat(raw,{'material':{'id':'m'}})
    assert wrapped.complete(prompt,{})==invalid
    assert raw.calls==[prompt]
    assert wrapped.last_metadata['usage']=={'input_tokens':7}
    assert wrapped.last_metadata['provider_attempt_count']==1
    from dse_knowledge.knowledge import validate_claim_context
    with pytest.raises(ValueError):
        validate_claim_context(invalid['claims'][0]['context'],{'material':{'id':'m'}})
