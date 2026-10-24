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
