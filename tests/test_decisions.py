import json

import pytest

from dse_knowledge import decisions as decision_module
from dse_knowledge.decisions import DecisionEngine, validate_decision

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


def test_neighbor_is_a_separate_citable_chunk_with_inherited_source_role():
    from dse_knowledge.decisions import bounded_evidence
    parent={'chunk_id':'p','material_id':'m','revision_id':'r','text':'parent evidence','role':'core_technical',
            'neighbor_evidence':[{'chunk_id':'n','material_id':'m','revision_id':'r','text':'neighbor evidence','start_offset':10,'end_offset':27}]}
    evidence,trace=bounded_evidence([parent])
    assert [x['chunk_id'] for x in evidence]==['p','n']
    assert evidence[1]['parent_chunk_id']=='p'
    assert evidence[1]['role']=='core_technical'
    r=result();r['findings']=[dict(statement='neighbor evidence',citations=['n'],confidence='source_assertion')]
    assert validate_decision(r,evidence)['status']=='evidence_supported'


def test_prompt_budget_is_explicit_and_does_not_relabel_or_truncate_source_text():
    from dse_knowledge.decisions import bounded_evidence
    items=[{'chunk_id':str(i),'material_id':'m','revision_id':'r','text':'z'*3000} for i in range(12)]
    evidence,trace=bounded_evidence(items,max_chars=6500)
    assert len(evidence)==2
    assert all(x['text']=='z'*3000 for x in evidence)
    assert trace['omitted_primary']==10


def _render_prompt(system, payload, required_rules, evidence, experiences):
    return (system+'\nTASK\n'+json.dumps(payload,ensure_ascii=False)
            +'\nMANDATORY_RULES\n'+json.dumps(required_rules,ensure_ascii=False)
            +'\nSOURCE_DATA\n'+json.dumps(evidence,ensure_ascii=False)
            +'\nEXPERIENCE_DATA\n'+json.dumps(experiences,ensure_ascii=False))


def test_fitting_prompt_drops_low_rank_experience_items_without_truncating_source():
    system='SYSTEM_SENTINEL'
    payload={'question':'TASK_SENTINEL','input':{'workload':'FULL_TASK'}}
    rules=[{'rule':'MANDATORY_RULE_SENTINEL','description':'R'*60}]
    primary={'chunk_id':'p1','material_id':'m','revision_id':'r','text':'P'*180,'role':'core_technical'}
    experiences={'status':'found','items':[
        {'memory_id':'highest','text':'H'*20},
        {'memory_id':'lowest','text':'L'*500},
    ]}
    expected_experiences={'status':'found','items':[experiences['items'][0]]}
    target_prompt=_render_prompt(system,payload,rules,[primary],expected_experiences)

    prompt,evidence,fitted_experiences,budget=decision_module.fit_decision_prompt(
        system,payload,rules,[primary],experiences,
        max_chars=len(target_prompt),max_bytes=len(target_prompt.encode('utf-8')))

    assert 'TASK_SENTINEL' in prompt and 'MANDATORY_RULE_SENTINEL' in prompt
    assert evidence==[primary] and evidence[0]['text']=='P'*180
    assert fitted_experiences==expected_experiences
    assert budget['omitted_experience']==1
    assert budget['omitted_source']==0


def test_fitting_prompt_drops_whole_source_chunks_after_experiences_neighbors_last():
    system='SYSTEM_SENTINEL'
    payload={'question':'TASK_SENTINEL','input':{'workload':'FULL_TASK'}}
    rules=[{'rule':'MANDATORY_RULE_SENTINEL','description':'R'*60}]
    primary={'chunk_id':'p1','material_id':'m','revision_id':'r','text':'P'*180,'role':'core_technical'}
    second_primary={'chunk_id':'p2','material_id':'m','revision_id':'r','text':'Q'*180,'role':'core_technical'}
    neighbor_one={'chunk_id':'n1','material_id':'m','revision_id':'r','parent_chunk_id':'p1',
                  'revision_id':'r','text':'N'*180,'result_kind':'neighbor_evidence'}
    neighbor_two={'chunk_id':'n2','material_id':'m','revision_id':'r','parent_chunk_id':'p2',
                  'text':'O'*180,'result_kind':'neighbor_evidence'}
    experiences={'status':'found','items':[
        {'memory_id':'highest','text':'H'*20},
        {'memory_id':'middle','text':'M'*500},
        {'memory_id':'lowest','text':'L'*500},
    ]}
    expected_evidence=[primary]
    expected_experiences={'status':'found','items':[]}
    target_prompt=_render_prompt(system,payload,rules,expected_evidence,expected_experiences)

    prompt,evidence,fitted_experiences,budget=decision_module.fit_decision_prompt(
        system,payload,rules,[primary,second_primary,neighbor_one,neighbor_two],experiences,
        max_chars=len(target_prompt),max_bytes=len(target_prompt.encode('utf-8')))

    assert 'TASK_SENTINEL' in prompt and 'FULL_TASK' in prompt
    assert 'MANDATORY_RULE_SENTINEL' in prompt and 'R'*60 in prompt
    assert prompt==target_prompt
    assert evidence==expected_evidence and evidence[0]['text']=='P'*180
    assert fitted_experiences==expected_experiences
    assert budget['total_chars']==len(prompt)
    assert budget['total_bytes']==len(prompt.encode('utf-8'))
    assert budget['omitted_experience']==3
    assert budget['omitted_source']==3
    assert budget['omitted_neighbors']==2
    assert budget['actual_evidence']==[{'chunk_id':'p1','material_id':'m','revision_id':'r',
                                        'result_kind':None,'parent_chunk_id':None}]


class _CaptureConnection:
    def __init__(self, store): self.store=store
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def execute(self, sql, args=()):
        if 'INSERT INTO decisions' in sql:
            self.store.result=args[4]
            self.store.snapshot=args[6]
        return None


class _CaptureStore:
    def __init__(self): self.snapshot=None; self.result=None
    def one(self, *args): return None
    def connection(self): return _CaptureConnection(self)


class _DecisionRetriever:
    def __init__(self): self.calls=0
    def search(self, *args, **kwargs):
        self.calls+=1
        return {'items':[{'chunk_id':'source-1','material_id':'material-1','revision_id':'revision-1',
                          'start_offset':0,'end_offset':18,'text':'source passage text',
                          'role':'core_technical','role_policy':{'use_ceiling':'source_assertion'}}],
                'channels':{},'policy_version':'retrieval-policy/v2','purpose':'design'}


class _DecisionNative:
    def __init__(self, experiences): self.experiences=experiences; self.calls=0
    def query_experiences(self, question): self.calls+=1; return self.experiences
    def observe(self, payload): return {'status':'recorded'}


class _DecisionChat:
    last_metadata={}
    def __init__(self): self.prompts=[]
    def complete(self, prompt, schema):
        self.prompts.append(prompt)
        return result()


def test_decision_snapshot_experience_and_evidence_refs_match_fitted_prompt():
    experiences={'status':'found','items':[
        {'memory_id':f'memory-{index}','text':str(index)*22_000,'score':1-index/10}
        for index in range(5)
    ],'metrics':{'returned':5}}
    store=_CaptureStore(); chat=_DecisionChat()
    engine=DecisionEngine(store,_DecisionRetriever(),chat,_DecisionNative(experiences))

    engine.decide({'kind':'knowledge','question':'summarize this source','input':{'required_rules':[]}})

    snapshot=store.snapshot.obj if hasattr(store.snapshot,'obj') else store.snapshot
    prompt=chat.prompts[0]
    sent_experiences=json.loads(prompt.split('\nEXPERIENCE_DATA\n',1)[1])
    assert snapshot['experience_snapshot']==sent_experiences
    assert len(sent_experiences['items'])<len(experiences['items'])
    assert snapshot['experience_refs']==[item['memory_id'] for item in sent_experiences['items']]
    assert snapshot['chunk_ids']==['source-1']
    assert snapshot['context_budget']['actual_evidence'][0]['chunk_id']=='source-1'
    assert snapshot['context_budget']['total_chars']==len(prompt)
    assert snapshot['context_budget']['total_bytes']==len(prompt.encode('utf-8'))
    assert snapshot['context_budget']['total_chars']<=decision_module.CODEX_MAX_PROMPT_CHARS
    assert snapshot['context_budget']['total_bytes']<=decision_module.CODEX_MAX_PROMPT_BYTES
    assert snapshot['policy']=='source-snapshot-v2'
    stored_result=store.result.obj if hasattr(store.result,'obj') else store.result
    assert stored_result['policy_version']=='dse-evidence-v2'


def test_snapshot_keeps_retriever_trace_only_for_auditing_and_marks_final_evidence():
    item_anchor={
        'material_id':'material-1','chunk_id':'kept','original_dense_rank':1,
        'original_hybrid_position':2,'promoted':True,
        'selection_basis':'dense_material_then_best_hybrid_passage','authority_changed':False,
    }
    source_anchor={
        'material_id':'material-1','chunk_id':'kept','original_dense_rank':1,
        'original_hybrid_position':1,'promoted':False,
        'selection_basis':'dense_material_then_best_hybrid_passage','authority_changed':False,
    }
    kept={
        'chunk_id':'kept','material_id':'material-1','revision_id':'revision-1',
        'start_offset':0,'end_offset':25_000,'text':'P'*25_000,'role':'core_technical',
        'role_policy':{'use_ceiling':'source_assertion'},
        'trace':{'channel_ranks':{'dense':1,'lexical':4},
                 'semantic_anchors':{'items':item_anchor},
                 'graph_rank':2,'TRACE_TEXT_SENTINEL':'must stay out of prompt and snapshot'},
        'graph_provenance':[{'relation_kind':'topic','relation':'mentions','edge_id':'edge-kept',
                             'claim_id':'claim-kept','evidence_chunk_id':'proof-kept','topic_key':'kv-cache'}],
        'neighbor_evidence':[{'chunk_id':'neighbor','material_id':'material-1','revision_id':'revision-1',
                              'text':'N'*8_000,'start_offset':25_000,'end_offset':33_000}],
    }
    dropped={
        'chunk_id':'dropped','material_id':'material-2','revision_id':'revision-2',
        'start_offset':0,'end_offset':40_000,'text':'D'*40_000,'role':'core_technical',
        'trace':{'channel_ranks':{'dense':2},'semantic_anchors':{'items':{'chunk_id':'dropped'}},
                 'graph_rank':3,'TRACE_TEXT_SENTINEL':'must stay out of prompt and snapshot'},
        'graph_provenance':[{'relation_kind':'claim','relation':'supports','edge_id':'edge-dropped',
                             'claim_id':'claim-dropped','evidence_chunk_id':'proof-dropped','topic_key':'other'}],
    }
    retrieval={'items':[kept,dropped],'semantic_anchors':{'items':item_anchor,'source_results':source_anchor},
               'channels':{},'policy_version':'retrieval-policy/v2','purpose':'design'}

    class TracedRetriever:
        def search(self,*args,**kwargs):return retrieval

    class CitedChat:
        last_metadata={}
        def __init__(self):self.prompts=[]
        def complete(self,prompt,schema):
            self.prompts.append(prompt)
            answer=result()
            answer['findings']=[{'statement':'Both excerpts support this citation test.',
                                 'citations':['kept','neighbor'],'confidence':'source_assertion'}]
            return answer

    store=_CaptureStore();chat=CitedChat()
    engine=DecisionEngine(store,TracedRetriever(),chat,_DecisionNative({'status':'no_match','items':[]}))
    engine.decide({'kind':'knowledge','question':'cite these retrieved passages','input':{'required_rules':[]}})

    snapshot=store.snapshot.obj if hasattr(store.snapshot,'obj') else store.snapshot
    stored_result=store.result.obj if hasattr(store.result,'obj') else store.result
    assert snapshot['chunk_ids']==['kept','neighbor']
    assert stored_result['findings'][0]['citations']==['kept','neighbor']
    prompt=chat.prompts[0]
    assert 'TRACE_TEXT_SENTINEL' not in prompt
    records={item['chunk_id']:item for item in snapshot['retrieval_evidence_trace']}
    assert records['kept']['trace']['channel_ranks']=={'dense':1,'lexical':4}
    assert records['kept']['graph_provenance']==kept['graph_provenance']
    assert records['kept']['in_final_evidence'] is True
    assert records['dropped']['in_final_evidence'] is False
    assert records['dropped']['chunk_id'] not in snapshot['chunk_ids']
    assert records['neighbor']['trace'] is None
    assert records['neighbor']['parent_chunk_id']=='kept'
    anchors=snapshot['retrieval_semantic_anchors']
    assert anchors['streams']==retrieval['semantic_anchors']
    item_anchors={item['chunk_id']:item for item in anchors['per_item']}
    assert item_anchors['kept']['item_anchor']=={'items':item_anchor}
    assert item_anchors['kept']['in_final_evidence'] is True
    assert item_anchors['dropped']['in_final_evidence'] is False
    assert item_anchors['neighbor']['item_anchor'] is None
    assert item_anchors['neighbor']['parent_chunk_id']=='kept'


def test_oversized_mandatory_rules_fail_before_chat_provider_call():
    chat=_DecisionChat()
    retriever=_DecisionRetriever()
    native=_DecisionNative({'status':'no_match','items':[]})
    engine=DecisionEngine(_CaptureStore(),retriever,chat,native)
    payload={'kind':'knowledge','question':'summarize this source',
             'input':{'required_rules':[{'rule':'mandatory-'+('X'*120_000)}]}}

    with pytest.raises(ValueError,match='decision_mandatory_context_exceeds_provider_budget'):
        engine.decide(payload)

    assert chat.prompts==[]
    assert retriever.calls==0
    assert native.calls==0
