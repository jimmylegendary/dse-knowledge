import json
from copy import deepcopy
import pytest
from dse_knowledge.quality import GroundedChat
from dse_knowledge.providers import CODEX_MAX_PROMPT_BYTES,CODEX_MAX_PROMPT_CHARS


def test_one_bounded_repair_keeps_actual_attempt_usage_and_requires_literal_evidence():
    doc={'material':{'id':'m'},'revision':{'sha256':'a'*64},'text':'Measured latency is 6.4 ms on the selected test.',
         'chunks':[{'id':'c','text':'Measured latency is 6.4 ms on the selected test.','start':0,'end':46}]}
    doc['chunks'][0]['end']=len(doc['text'])
    valid_parameter={'name':'latency','value':6.4,'unit':'ms','evidence':{'chunk_id':'c','quote':doc['text']}}
    invalid_parameter={'name':'unsupported-latency','value':99,'unit':'ms','evidence':{'chunk_id':'c','quote':doc['text']}}
    context={'schema_version':'claim-context/v1','parameters':[valid_parameter,invalid_parameter],
             'conditions':[],'source_scope_note':'Only this test.'}
    bad={'claims':[{'claim_id':'a','context':context}]}
    good={'claims':[{'claim_id':'a','context':{'schema_version':'claim-context/v1',
        'parameters':[deepcopy(valid_parameter)],'conditions':[],'source_scope_note':'Only this test.'}}]}
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
    candidate=json.dumps(bad,ensure_ascii=False,separators=(',',':'))
    assert 'UNTRUSTED PRIOR TYPED RESPONSE CANDIDATE' in raw.calls[1]
    assert candidate in raw.calls[1]
    assert raw.calls[1].startswith('Untrusted source')
    assert 'claims[0].context.parameters[1].value: claim_context_value_not_literal' in raw.calls[1]
    assert 'keep already-valid fields unchanged' in raw.calls[1].lower()
    assert 'do not treat prior values or quotes as evidence' in raw.calls[1].lower()
    assert 'complete numeric literal' in raw.calls[1].lower()
    assert 'do not compute or infer numeric values' in raw.calls[1].lower()
    assert chat.last_metadata['usage']['input_tokens']==20
    assert chat.last_metadata['provider_attempt_count']==2
    assert chat.last_metadata['repair_policy_version']=='literal-field-feedback/v2'
    assert chat.last_metadata['repair_context_mode']=='full_response_candidate'
    assert '"value":99' not in json.dumps(chat.last_metadata)
    assert doc['text'] not in json.dumps(chat.last_metadata)


def test_failed_repair_is_returned_to_strict_caller_validation_without_silent_emptying():
    class Chat:
        last_metadata={}
        def __init__(self):self.calls=0
        def complete(self,*args):self.calls+=1;return {'claims':[{'claim_id':'c','context':{'bad':'shape'}}]}
    raw=Chat();wrapped=GroundedChat(raw,{'material':{'id':'m'}})
    assert wrapped.complete('source',{})['claims'][0]['context']=={'bad':'shape'}
    assert raw.calls==2
    assert wrapped.last_metadata['repair_failure_paths']==[
        {'path':'claims[0].context','reason_code':'claim_context_invalid'}]

def test_large_prior_response_is_used_when_full_candidate_fits_prompt_budget():
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
    assert 'UNTRUSTED PRIOR TYPED RESPONSE CANDIDATE' in repair
    assert json.dumps(bad,ensure_ascii=False,separators=(',',':')) in repair
    assert wrapped.last_metadata['repair_context_mode']=='full_response_candidate'
    assert wrapped.last_metadata['repair_failures_truncated'] is True
    assert len(repair)<=CODEX_MAX_PROMPT_CHARS
    assert len(repair.encode('utf-8'))<=CODEX_MAX_PROMPT_BYTES
    assert wrapped.last_metadata['usage']=={'input_tokens':30,'output_tokens':4}
    assert wrapped.last_metadata['provider_attempt_count']==2
    assert len(wrapped.last_metadata['provider_attempts'])==2
    assert '"value":99' not in json.dumps(wrapped.last_metadata)
    assert quote not in json.dumps(wrapped.last_metadata)


def test_oversized_prior_response_falls_back_to_whole_failed_entries_without_truncating_them():
    quote='SOURCE_MARKER_FOR_COMPLETE_FAILED_ENTRY ' + ('q'*1050) + ' reports latency 6.4 ms.'
    assert len(quote)<=1200
    doc={'material':{'id':'bounded-entry'},'revision':{'sha256':'d'*64},'text':quote,
         'chunks':[{'id':'c','text':quote,'start':0,'end':len(quote)}]}
    valid={'name':'valid','value':6.4,'unit':'ms','evidence':{'chunk_id':'c','quote':quote}}
    invalid={'name':'unsupported','value':99,'unit':'ms','evidence':{'chunk_id':'c','quote':quote}}
    response={'claims':[]}
    for claim_index in range(3):
        parameters=[deepcopy(valid) for _ in range(32)]
        if claim_index==0:parameters[0]=deepcopy(invalid)
        response['claims'].append({'claim_id':f'claim-{claim_index}','context':_context(parameters=parameters)})
    assert len(json.dumps(response,ensure_ascii=False,separators=(',',':')).encode('utf-8'))>CODEX_MAX_PROMPT_BYTES
    repaired=deepcopy(response)
    repaired['claims'][0]['context']['parameters'][0]=deepcopy(valid)
    class Chat:
        def __init__(self):self.calls=[];self.last_metadata={}
        def complete(self,prompt,schema):
            self.calls.append(prompt)
            self.last_metadata={'usage':{'input_tokens':11*len(self.calls),'output_tokens':3}}
            return response if len(self.calls)==1 else repaired
    raw=Chat();wrapped=GroundedChat(raw,doc)

    assert wrapped.complete('Synthetic source prompt.',{})==repaired

    assert len(raw.calls)==2
    repair=raw.calls[1]
    assert wrapped.last_metadata['repair_context_mode']=='bounded_failed_entries'
    assert json.dumps(invalid,ensure_ascii=False,separators=(',',':')) in repair
    assert json.dumps(response,ensure_ascii=False,separators=(',',':')) not in repair
    assert 'valid-2-31' not in repair
    assert 'SOURCE_MARKER_FOR_COMPLETE_FAILED_ENTRY' in repair
    assert 'do not treat prior values or quotes as evidence' in repair.lower()
    assert len(repair)<=CODEX_MAX_PROMPT_CHARS
    assert len(repair.encode('utf-8'))<=CODEX_MAX_PROMPT_BYTES
    metadata=json.dumps(wrapped.last_metadata,ensure_ascii=False)
    assert 'SOURCE_MARKER_FOR_COMPLETE_FAILED_ENTRY' not in metadata
    assert '"value":99' not in metadata


def test_repair_falls_back_to_paths_only_when_complete_failed_entry_does_not_fit():
    quote='PATH_ONLY_SOURCE_MARKER ' + ('z'*950) + ' latency 6.4 ms.'
    doc={'material':{'id':'path-only'},'revision':{'sha256':'e'*64},'text':quote,
         'chunks':[{'id':'c','text':quote,'start':0,'end':len(quote)}]}
    invalid={'claims':[{'claim_id':'a','context':_context(parameters=[{
        'name':'latency','value':99,'unit':'ms','evidence':{'chunk_id':'c','quote':quote}}])}]}
    valid={'claims':[{'claim_id':'a','context':_context()}]}
    class Chat:
        last_metadata={}
        def __init__(self):self.calls=[]
        def complete(self,prompt,schema):
            self.calls.append(prompt);self.last_metadata={'usage':{'input_tokens':7}}
            return invalid if len(self.calls)==1 else valid
    raw=Chat();wrapped=GroundedChat(raw,doc)
    prompt='P'*(CODEX_MAX_PROMPT_CHARS-1500)

    assert wrapped.complete(prompt,{})==valid

    assert len(raw.calls)==2
    repair=raw.calls[1]
    assert wrapped.last_metadata['repair_context_mode']=='paths_only_oversize'
    assert 'claims[0].context.parameters[0].value: claim_context_value_not_literal' in repair
    assert 'previous candidate omitted because complete failed entries exceed the provider prompt budget' in repair.lower()
    assert 'PATH_ONLY_SOURCE_MARKER' not in repair
    assert '"value":99' not in repair
    assert len(repair)<=CODEX_MAX_PROMPT_CHARS
    assert len(repair.encode('utf-8'))<=CODEX_MAX_PROMPT_BYTES

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
    assert wrapped.last_metadata['repair_context_mode']=='skipped_prompt_budget'
    from dse_knowledge.knowledge import validate_claim_context
    with pytest.raises(ValueError):
        validate_claim_context(invalid['claims'][0]['context'],{'material':{'id':'m'}})


def _repair_document():
    quotes=[
        'Metric alpha reports 12.5 ms for synthetic run A.',
        'Metric beta selects H1000 for synthetic run B.',
        'Condition gamma uses 4 lanes for synthetic run C.',
        'Condition delta reports 7 cycles for synthetic run D.',
    ]
    text='\n'.join(quotes)
    return {'material':{'id':'repair-test'},'revision':{'sha256':'b'*64},'text':text,
            'chunks':[{'id':'c','text':text,'start':0,'end':len(text)}]},quotes


def _context(parameters=None,conditions=None):
    return {'schema_version':'claim-context/v1','parameters':parameters or [],
            'conditions':conditions or [],'source_scope_note':'Only these synthetic excerpts.'}


def test_repair_feedback_reports_each_document_claim_value_and_unit_path_without_raw_values_or_quotes():
    from dse_knowledge.knowledge import validate_claim_context
    doc,quotes=_repair_document()
    response1={'documents':[{'material_id':'repair-test','claims':[
        {'claim_id':'alpha','context':_context(parameters=[{'name':'alpha','value':99,'unit':'ms','evidence':{'chunk_id':'c','quote':quotes[0]}}])},
        {'claim_id':'beta','context':_context(parameters=[{'name':'beta','value':'100','unit':None,'evidence':{'chunk_id':'c','quote':quotes[1]}}])},
        {'claim_id':'gamma','context':_context(conditions=[{'dimension':'lanes','operator':'eq','value':5,'unit':'lanes','evidence':{'chunk_id':'c','quote':quotes[2]}}])},
        {'claim_id':'delta','context':_context(conditions=[{'dimension':'cycles','operator':'eq','value':7,'unit':'ms','evidence':{'chunk_id':'c','quote':quotes[3]}}])},
    ]}]}
    response2=deepcopy(response1)
    response2['documents'][0]['claims'][1]['context']['parameters'][0]['value']='H1000'
    response2['documents'][0]['claims'][2]['context']['conditions'][0]['value']=4
    response2['documents'][0]['claims'][3]['context']['conditions'][0]['unit']='cycles'
    expected=[
        {'path':'documents[0].claims[0].context.parameters[0].value','reason_code':'claim_context_value_not_literal'},
        {'path':'documents[0].claims[1].context.parameters[0].value','reason_code':'claim_context_value_not_literal'},
        {'path':'documents[0].claims[2].context.conditions[0].value','reason_code':'claim_context_value_not_literal'},
        {'path':'documents[0].claims[3].context.conditions[0].unit','reason_code':'claim_context_unit_not_literal'},
    ]
    class Chat:
        def __init__(self):self.calls=[];self.last_metadata={}
        def complete(self,prompt,schema):
            self.calls.append(prompt)
            self.last_metadata={'usage':{'input_tokens':10*len(self.calls),'output_tokens':2},'duration_seconds':1}
            return response1 if len(self.calls)==1 else response2
    raw=Chat();wrapped=GroundedChat(raw,doc)
    assert wrapped.complete('Synthetic source request.',{})==response2
    assert len(raw.calls)==2
    candidate_marker='UNTRUSTED PRIOR TYPED RESPONSE CANDIDATE'
    assert json.dumps(response1,ensure_ascii=False,separators=(',',':')) in raw.calls[1]
    feedback=raw.calls[1].split(candidate_marker,1)[0].split('LOCAL VALIDATION FAILED',1)[1]
    for failure in expected:
        assert f"{failure['path']}: {failure['reason_code']}" in feedback
    assert all(quote not in feedback for quote in quotes)
    assert '"value":99' not in feedback and '"value":"100"' not in feedback and 'H1000' not in feedback
    assert wrapped.last_metadata['repair_failure_paths']==expected
    metadata=json.dumps(wrapped.last_metadata,ensure_ascii=False)
    assert all(quote not in metadata for quote in quotes)
    assert '"value":99' not in metadata and '"value":"100"' not in metadata and 'H1000' not in metadata
    assert wrapped.last_metadata['repair_failures_truncated'] is False
    assert wrapped.last_metadata['usage']=={'input_tokens':30,'output_tokens':4}
    with pytest.raises(ValueError,match='claim_context_value_not_literal'):
        validate_claim_context(response2['documents'][0]['claims'][0]['context'],doc)


def test_repair_feedback_is_capped_at_eight_failures():
    doc,quotes=_repair_document()
    quote=quotes[0]
    parameters=[{'name':f'p{index}','value':99,'unit':'ms','evidence':{'chunk_id':'c','quote':quote}}
                for index in range(9)]
    invalid={'claims':[{'claim_id':'many','context':_context(parameters=parameters)}]}
    class Chat:
        last_metadata={}
        def __init__(self):self.calls=[]
        def complete(self,prompt,schema):self.calls.append(prompt);return invalid
    raw=Chat();wrapped=GroundedChat(raw,doc)
    wrapped.complete('Synthetic request.',{})
    assert len(raw.calls)==2
    feedback=raw.calls[1].split('LOCAL VALIDATION FAILED',1)[1]
    assert all(f'claims[0].context.parameters[{index}].value: claim_context_value_not_literal' in feedback
               for index in range(8))
    assert 'claims[0].context.parameters[8].value' not in feedback
    assert 'more validation failures omitted' in feedback
    assert len(wrapped.last_metadata['repair_failure_paths'])==8
    assert wrapped.last_metadata['repair_failures_truncated'] is True


def test_full_value_token_embedded_in_word_remains_invalid_after_one_repair():
    from dse_knowledge.knowledge import validate_claim_context
    quote='This synthetic workload targets H1000 for testing.'
    doc={'material':{'id':'token-test'},'revision':{'sha256':'c'*64},'text':quote,
         'chunks':[{'id':'c','text':quote,'start':0,'end':len(quote)}]}
    invalid={'claims':[{'claim_id':'token','context':_context(parameters=[
        {'name':'target','value':'100','unit':None,'evidence':{'chunk_id':'c','quote':quote}}])}]}
    class Chat:
        last_metadata={}
        def __init__(self):self.calls=[]
        def complete(self,prompt,schema):self.calls.append(prompt);return invalid
    raw=Chat();wrapped=GroundedChat(raw,doc)
    assert wrapped.complete('Synthetic request.',{})==invalid
    assert len(raw.calls)==2
    repair=raw.calls[1]
    feedback=repair.split('UNTRUSTED PRIOR TYPED RESPONSE CANDIDATE',1)[0].split('LOCAL VALIDATION FAILED',1)[1]
    assert 'claims[0].context.parameters[0].value: claim_context_value_not_literal' in feedback
    assert 'complete string value or complete numeric literal' in feedback.lower()
    assert 'never take a substring from an identifier' in feedback.lower()
    assert json.dumps(invalid,ensure_ascii=False,separators=(',',':')) in repair
    metadata=json.dumps(wrapped.last_metadata,ensure_ascii=False)
    assert 'H1000' not in metadata and '"value":"100"' not in metadata
    with pytest.raises(ValueError,match='claim_context_value_not_literal'):
        validate_claim_context(invalid['claims'][0]['context'],doc)


def test_invalid_output_recorder_stores_small_output_and_hashes_large_private_output(tmp_path):
    import stat
    from dse_knowledge.quality import _record_invalid_output
    key={'operation':'claim_context','material_id':'material-test','revision':'d'*64,'claim_ids':['claim-1']}
    metadata={'provider_attempt_count':2,'repair_policy_version':'literal-field-feedback/v2',
              'repair_context_mode':'full_response_candidate',
              'repair_failure_paths':[{'path':'claims[0].context.parameters[0].value',
                                       'reason_code':'claim_context_value_not_literal'}],
              'usage':{'input_tokens':12,'output_tokens':4},'authorization':'PRIVATE_CREDENTIAL_SENTINEL'}
    small={'claims':[{'claim_id':'claim-1','context':{'schema_version':'claim-context/v1'}}]}
    _record_invalid_output(tmp_path,'claim_context',key,small,metadata)
    failures=tmp_path/'quality-cache'/'failures'
    assert stat.S_IMODE(failures.stat().st_mode)==0o700
    first=json.loads(next(failures.glob('*.json')).read_text())
    assert first['operation']=='claim_context'
    assert first['material_id']=='material-test'
    assert first['revision_sha256']=='d'*64
    assert len(first['request_identity'])==64
    assert first['invalid_output']==small
    assert first['provider_metadata']['usage']=={'input_tokens':12,'output_tokens':4}
    assert first['provider_metadata']['repair_context_mode']=='full_response_candidate'
    assert 'authorization' not in first['provider_metadata']
    assert 'PRIVATE_CREDENTIAL_SENTINEL' not in json.dumps(first)

    large={'response':'x'*(1024*1024+10)}
    _record_invalid_output(tmp_path,'structured_claims',key,large,metadata)
    records=[json.loads(path.read_text()) for path in sorted(failures.glob('*.json'))]
    assert len(records)==2
    second=next(item for item in records if item['operation']=='structured_claims')
    assert 'invalid_output' not in second
    assert len(second['invalid_output_sha256'])==64
    assert second['invalid_output_size_bytes']==len(json.dumps(large,ensure_ascii=False,separators=(',',':')).encode('utf-8'))
    assert second['invalid_output_omission_reason']=='response_exceeds_1MiB'
    assert stat.S_IMODE(next(failures.glob('*.json')).stat().st_mode)==0o600


@pytest.mark.parametrize('operation',['enrich_context','extract_structured'])
def test_failed_quality_operation_records_invalid_response_without_validating_failure_cache(tmp_path,monkeypatch,operation):
    from dse_knowledge import providers,quality
    from dse_knowledge.ingestion import IngestionError
    quote='The synthetic latency measured 12.5 ms for this case.'
    doc={'material':{'id':'material-failure','title':'Synthetic diagnostic','category':'benchmark','source':'fixture'},
         'revision':{'sha256':'e'*64,'scope':'synthetic'},'text':quote,
         'chunks':[{'id':'c','text':quote,'start':0,'end':len(quote)}]}
    context={'schema_version':'claim-context/v1','parameters':[
        {'name':'latency','value':99,'unit':'ms','evidence':{'chunk_id':'c','quote':quote}}],
        'conditions':[],'source_scope_note':'Synthetic diagnostic only.'}
    context_response={'claims':[{'claim_id':'claim-1','context':context}]}
    structured_response={'documents':[{'material_id':'material-failure','claims':[{
        'chunk_id':'c','quote':quote,'kind':'measurement','subject':'latency',
        'predicate':'measured_at','object':'12.5 ms','summary':'Synthetic measurement.',
        'scope':'Synthetic source only.','context':context}]}]}
    response=context_response if operation=='enrich_context' else structured_response
    claim={'id':'claim-1','claim_id':'claim-1','material_id':'material-failure','revision_id':'revision-1',
           'chunk_id':'c','quote':quote,'kind':'measurement','subject':'latency','predicate':'measured_at',
           'object':'12.5 ms','summary':'Synthetic measurement.','scope':'Synthetic source only.'}
    class Settings:
        data_root=tmp_path
        def get(self,key,default=None):return 'synthetic-model' if key=='CHAT_MODEL_ID' else default
    class Store:
        def __init__(self):self.invocations=[];self.events=[]
        def one(self,*args):return {'role':'core_technical'}
        def rows(self,sql,args=()):
            if 'SELECT cl.* FROM claims cl' in sql:return [claim]
            if 'SELECT a.claim_id FROM claim_annotations' in sql:return []
            raise AssertionError('Unexpected fake store query')
        def put_claim_context(self,*args):pytest.fail('invalid output reached annotation write')
        def put_claims(self,*args):pytest.fail('invalid output reached claim write')
        def invocation(self,*args):self.invocations.append(args)
        def ingest_event(self,*args):self.events.append(args)
    clients=[]
    class Provider:
        def __init__(self):self.calls=0;self.last_metadata={}
        def complete(self,prompt,schema):
            self.calls+=1
            self.last_metadata={'usage':{'input_tokens':17,'output_tokens':5},
                                'authorization':'PRIVATE_CREDENTIAL_SENTINEL'}
            return response
        def close(self):pass
    def make_provider(settings):
        client=Provider();clients.append(client);return client
    monkeypatch.setattr(providers,'ChatClient',make_provider)
    store=Store();settings=Settings()
    function=quality.enrich_context if operation=='enrich_context' else quality.extract_structured
    for _ in range(2):
        with pytest.raises(IngestionError,match='claim_context_value_not_literal'):
            function(doc,settings,store=store)
    assert len(clients)==2 and sum(client.calls for client in clients)==4
    assert len(store.invocations)==2 and len(store.events)==2
    cache_root=tmp_path/'quality-cache'
    assert [p.name for p in cache_root.iterdir()]==['failures']
    failure_paths=list((cache_root/'failures').glob('*.json'))
    assert len(failure_paths)==2
    for path in failure_paths:
        artifact=json.loads(path.read_text())
        assert artifact['operation']==('claim_context' if operation=='enrich_context' else 'structured_claims')
        assert artifact['invalid_output']==response
        assert artifact['provider_metadata']['repair_failure_paths'][0]['reason_code']=='claim_context_value_not_literal'
        assert 'PRIVATE_CREDENTIAL_SENTINEL' not in path.read_text()


def _outer_contract_fixture(operation,response):
    from dse_knowledge import providers,quality
    quote='Synthetic source reports a 12.5 ms latency for this test.'
    doc={'material':{'id':'outer-contract','title':'Synthetic diagnostic','category':'benchmark','source':'fixture'},
         'revision':{'sha256':'f'*64,'scope':'synthetic'},'text':quote,
         'chunks':[{'id':'outer-chunk','text':quote,'start':0,'end':len(quote)}]}
    context={'schema_version':'claim-context/v1','parameters':[],'conditions':[],
             'source_scope_note':'Only this synthetic source.'}
    claim={'id':'claim-outer','claim_id':'claim-outer','material_id':'outer-contract','revision_id':'revision-outer',
           'chunk_id':'outer-chunk','quote':quote,'kind':'measurement','subject':'latency',
           'predicate':'measured_at','object':'12.5 ms','summary':'Synthetic measurement.',
           'scope':'Synthetic source only.'}
    class Settings:
        data_root=None
        def __init__(self,root):self.data_root=root
        def get(self,key,default=None):return 'synthetic-model' if key=='CHAT_MODEL_ID' else default
    class Store:
        def __init__(self):self.invocations=[];self.events=[]
        def one(self,*args):return {'role':'core_technical'}
        def rows(self,sql,args=()):
            if 'SELECT cl.* FROM claims cl' in sql:return [claim]
            if 'SELECT a.claim_id FROM claim_annotations' in sql:return []
            raise AssertionError('Unexpected fake store query')
        def put_claim_context(self,*args):return 'annotation-outer'
        def put_claims(self,*args):return len(args[1])
        def invocation(self,*args):self.invocations.append(args)
        def ingest_event(self,*args):self.events.append(args)
    class Provider:
        def __init__(self):self.calls=0;self.last_metadata={}
        def complete(self,prompt,schema):
            self.calls+=1
            self.last_metadata={'usage':{'input_tokens':9,'output_tokens':3}}
            return response
        def close(self):pass
    return quality,providers,Settings,Store,Provider,doc,claim,context


@pytest.mark.parametrize('operation',['enrich_context','extract_structured'])
@pytest.mark.parametrize('response_kind',['empty_object','empty_documents'])
def test_outer_extraction_contract_failures_record_last_response_not_success_cache(
        tmp_path,monkeypatch,operation,response_kind):
    from dse_knowledge.ingestion import IngestionError
    response={} if response_kind=='empty_object' else {'documents':[]}
    quality,providers,Settings,Store,Provider,doc,_,_= _outer_contract_fixture(operation,response)
    clients=[]
    def make_provider(settings):
        client=Provider();clients.append(client);return client
    monkeypatch.setattr(providers,'ChatClient',make_provider)
    settings=Settings(tmp_path);store=Store()
    function=quality.enrich_context if operation=='enrich_context' else quality.extract_structured
    with pytest.raises(IngestionError):function(doc,settings,store=store)
    assert len(clients)==1 and clients[0].calls==1
    cache_root=tmp_path/'quality-cache'
    assert sorted(path.name for path in cache_root.iterdir())==['failures']
    failures=list((cache_root/'failures').glob('*.json'))
    assert len(failures)==1
    artifact=json.loads(failures[0].read_text())
    assert artifact['invalid_output']==response
    assert artifact['operation']==('claim_context' if operation=='enrich_context' else 'structured_claims')
    assert artifact['provider_metadata']['repair_context_mode']=='not_needed'
    assert '"value":99' not in json.dumps(store.invocations)
    assert doc['text'] not in json.dumps(store.invocations)


@pytest.mark.parametrize('operation',['enrich_context','extract_structured'])
def test_fully_valid_quality_response_is_cached_without_failure_artifact(tmp_path,monkeypatch,operation):
    quality,providers,Settings,Store,Provider,doc,_,context=_outer_contract_fixture(operation,{})
    if operation=='enrich_context':
        response={'claims':[{'claim_id':'claim-outer','context':context}]}
    else:
        quote=doc['text']
        response={'documents':[{'material_id':'outer-contract','claims':[{
            'chunk_id':'outer-chunk','quote':quote,'kind':'measurement','subject':'latency',
            'predicate':'measured_at','object':'12.5 ms','summary':'Synthetic measurement.',
            'scope':'Synthetic source only.','context':context}]}]}
    clients=[]
    def make_provider(settings):
        client=Provider();client_response=response
        client.complete=lambda prompt,schema:(setattr(client,'calls',client.calls+1) or client_response)
        clients.append(client);return client
    monkeypatch.setattr(providers,'ChatClient',make_provider)
    settings=Settings(tmp_path);store=Store()
    function=quality.enrich_context if operation=='enrich_context' else quality.extract_structured
    result=function(doc,settings,store=store)
    assert result['status'] in ('enriched','complete')
    assert result['provider_metadata']['repair_context_mode']=='not_needed'
    assert len(clients)==1 and clients[0].calls==1
    cache_root=tmp_path/'quality-cache'
    assert len(list(cache_root.glob('*.json')))==1
    assert not (cache_root/'failures').exists()
