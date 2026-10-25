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
