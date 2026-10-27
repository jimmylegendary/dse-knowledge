from contextlib import contextmanager

from fastapi.testclient import TestClient
from dse_knowledge.app import create_app
from dse_knowledge.config import Settings

class Store:
    def __init__(self):self.jobs=[]
    def new_job(self,kind,payload):self.jobs.append(payload);return 'j1'
    def rows(self,*a):return []
    def one(self,*a):return None
class Native:
    def capabilities(self):return {'actual':'not_used_in_unit_test'}
class Chat:
    def close(self):pass

class CapacityStore(Store):
    def __init__(self, visible_chunk_count):
        super().__init__()
        self.visible_chunk_count=visible_chunk_count
        self.connection_queries=[]

    @contextmanager
    def connection(self):
        store=self
        class Connection:
            def execute(self,sql,args=()):
                store.connection_queries.append((sql,args))
                class Cursor:
                    def __init__(self,row=None):self.row=row
                    def fetchone(self):return self.row
                if 'SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY' in sql:
                    return Cursor()
                if 'visible_chunk_count' in sql:
                    return Cursor({'visible_chunk_count':store.visible_chunk_count})
                raise AssertionError('unexpected capacity-test SQL')
        yield Connection()

class NeverEmbedding:
    def embed(self,*args,**kwargs):
        raise AssertionError('embedding must not run after the capacity guard rejects the corpus')

def client():return TestClient(create_app(Settings({}),store=Store(),embedding=object(),chat=Chat(),native=Native(),run_jobs=False))

def test_decision_is_durable_job_and_request_validated():
    with client() as c:
        r=c.post('/api/decisions',json={'kind':'hardware','question':'Check GPU memory'})
        assert r.status_code==202 and r.json()['job_id']=='j1'
        assert c.post('/api/decisions',json={'kind':'fake','question':'Check GPU memory'}).status_code==422

def test_cross_origin_mutation_denied_and_unknown_resource():
    with client() as c:
        assert c.post('/api/decisions',json={},headers={'origin':'http://other.invalid'}).status_code==403
        assert c.get('/api/jobs/missing').status_code==404

def test_nonfinite_input_does_not_become_a_metric():
    with client() as c:
        payload={'name':'test','cohort':'x','method':'measured','metrics':[{'name':'ttft','value':'NaN','unit':'ms','direction':'min'}]}
        assert c.post('/api/experiments',json=payload).status_code==422

def test_search_capacity_error_is_typed_503_before_provider_call():
    store=CapacityStore(50001)
    app=create_app(Settings({}),store=store,embedding=NeverEmbedding(),chat=Chat(),native=Native(),run_jobs=False)
    with TestClient(app) as c:
        response=c.post('/api/search',json={'query':'GPU memory'})

    assert response.status_code==503
    assert response.json()=={
        'detail':'Search unavailable for current corpus scope',
        'code':'retrieval_capacity_exceeded',
    }
    assert len(store.connection_queries)==2
    assert 'SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY' in store.connection_queries[0][0]
    assert 'visible_chunk_count' in store.connection_queries[1][0]


def _search_app(monkeypatch, values, advisor=None):
    import dse_knowledge.app as app_module

    class SearchRetriever:
        def __init__(self, *args, **kwargs):
            self.results = {
                'query': '', 'retrieval_mode': 'contextual_rerank',
                'items': [{
                    'chunk_id': 'chunk-a', 'material_id': 'material-a', 'revision_id': 'revision-a',
                    'text': 'The cited source passage.', 'role': 'core_technical',
                    'trace': {'rank': 1},
                }],
                'locators': [], 'channels': {'context_dense': 1, 'graph': 0},
            }
        def search(self, query, category='', limit=12, *, purpose='auto', retrieval_mode=None):
            self.results['query'] = query
            return self.results

    monkeypatch.setattr(app_module, 'Retriever', SearchRetriever)
    store = Store()
    app = app_module.create_app(
        Settings(values), store=store, embedding=object(), chat=Chat(), native=Native(),
        run_jobs=False, evidence_advisor=advisor,
    )
    return app, store


class RecordingAdvice:
    def __init__(self): self.calls=[]
    def assess(self, query, evidence, *, kind='knowledge', required_rules=None):
        self.calls.append((query, evidence, kind, required_rules))
        return {
            'schema_version':'jev-evidence-advice/v1','status':'assessed','advisory_only':True,
            'choice':'direct_support_candidate','support_score':0.8,
            'score_kind':'uncalibrated_direct_support_probability','policy_version':'jev-evidence-advice/v1',
            'evidence_ids':['chunk-a'],'projection':{},'metadata':{},'consumed_by_generator':False,
        }


def test_search_jev_advice_is_opt_in_and_preserves_ranked_result(monkeypatch):
    advisor = RecordingAdvice()
    app, _ = _search_app(monkeypatch, {
        'DSE_JEV_EVIDENCE_ENABLED':'true', 'DSE_RETRIEVAL_ALLOW_MODE_OVERRIDE':'false',
    }, advisor)
    with TestClient(app) as c:
        response = c.post('/api/search', json={'query':'GPU memory', 'evidence_advice':'jev'})

    assert response.status_code == 200
    body = response.json()
    assert [item['chunk_id'] for item in body['items']] == ['chunk-a']
    assert body['items'][0]['trace'] == {'rank':1}
    assert body['evidence_advice']['status'] == 'assessed'
    assert body['evidence_advice']['consumed_by_generator'] is False
    assert advisor.calls[0][0] == 'GPU memory'
    assert advisor.calls[0][1][0]['chunk_id'] == 'chunk-a'


def test_search_disabled_envelope_and_explicit_unavailable_jev_request(monkeypatch):
    app, _ = _search_app(monkeypatch, {})
    with TestClient(app) as c:
        default_response = c.post('/api/search', json={'query':'GPU memory'})
        requested_response = c.post('/api/search', json={'query':'GPU memory', 'evidence_advice':'jev'})

    assert default_response.status_code == 200
    assert default_response.json()['evidence_advice']['status'] == 'disabled'
    assert default_response.json()['evidence_advice']['support_score'] is None
    assert requested_response.status_code == 503
    assert requested_response.json()['code'] == 'evidence_advice_not_enabled'


def test_search_advice_override_obeys_existing_override_flag_and_capabilities(monkeypatch):
    advisor = RecordingAdvice()
    app, _ = _search_app(monkeypatch, {
        'DSE_JEV_EVIDENCE_ENABLED':'true', 'DSE_RETRIEVAL_ALLOW_MODE_OVERRIDE':'false',
    }, advisor)
    with TestClient(app) as c:
        denied = c.post('/api/search', json={'query':'GPU memory', 'evidence_advice':'off'})
        capabilities = c.get('/api/capabilities').json()

    assert denied.status_code == 400
    assert denied.json()['code'] == 'evidence_advice_override_disabled'
    assert capabilities['retrieval']['evidence_advice_enabled'] is True
    assert capabilities['retrieval']['evidence_advice_score_kind'] == 'uncalibrated_direct_support_probability'
    assert capabilities['retrieval']['evidence_advice_max_state_bytes'] == 24000
    assert capabilities['retrieval']['evidence_advice_max_sources'] == 12
    assert capabilities['retrieval']['evidence_advice_changes_ranking'] is False
    assert advisor.calls == []


def test_settings_loads_jev_owner_only_file(tmp_path, monkeypatch):
    config_dir = tmp_path / 'config'
    config_dir.mkdir(mode=0o700)
    jev = config_dir / 'jev.env'
    jev.write_text('DSE_JEV_EVIDENCE_ENABLED=true\nDSE_JEV_TIMEOUT_SECONDS=45\n')
    jev.chmod(0o600)
    monkeypatch.setenv('DSE_CONFIG_DIR', str(config_dir))

    loaded = Settings.load()

    assert loaded.get('DSE_JEV_EVIDENCE_ENABLED') == 'true'
    assert loaded.get('DSE_JEV_TIMEOUT_SECONDS') == '45'
