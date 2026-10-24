"""Single-operator HTTP workbench backed by real canonical storage and providers."""
from __future__ import annotations
from contextlib import asynccontextmanager
from pathlib import Path
import json
from typing import Literal
from urllib.parse import urlsplit
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from psycopg.types.json import Jsonb
from .config import Settings
from .db import Store
from .decisions import DecisionEngine,JobLoop
from .policies import validate_metrics,compare_experiments
from .retrieval import Retriever


class Body(BaseModel):model_config=ConfigDict(extra='forbid',strict=True)
class SearchBody(Body):query:str=Field(min_length=1,max_length=2000);category:str='';limit:int=Field(default=12,ge=1,le=30)
class DecisionBody(Body):kind:Literal['hardware','kernel','experiment','knowledge'];question:str=Field(min_length=3,max_length=4000);input:dict=Field(default_factory=dict)
class FeedbackBody(Body):decision_id:str;verdict:Literal['useful','incorrect','needs_evidence'];notes:str=Field(default='',max_length=8000)
class Metric(Body):name:str=Field(min_length=1,max_length=80);value:float;unit:str=Field(min_length=1,max_length=50);direction:Literal['min','max']
class ExperimentBody(Body):name:str=Field(min_length=1,max_length=200);cohort:str=Field(min_length=1,max_length=200);method:Literal['measured','analytical','simulated','replay','imported'];metrics:list[Metric]=Field(min_length=1,max_length=50);context:dict=Field(default_factory=dict)
class CompareBody(Body):baseline_id:str;candidate_id:str
class HardwareBody(Body):source:str=Field(min_length=1,max_length=200000)


def create_app(settings=None,store=None,embedding=None,chat=None,native=None,run_jobs=True):
    settings=settings or Settings.load()
    if store is None:store=Store(settings)
    if embedding is None:
        from .providers import EmbeddingClient
        embedding=EmbeddingClient(settings)
    if chat is None:
        from .providers import ChatClient
        chat=ChatClient(settings)
    if native is None:
        from .integrations import NativeIntegrations
        native=NativeIntegrations(settings)
    retriever=Retriever(store,embedding);engine=DecisionEngine(store,retriever,chat,native);jobs=JobLoop(store,engine)

    @asynccontextmanager
    async def lifespan(app):
        if run_jobs:jobs.start()
        yield
        jobs.close()

    app=FastAPI(title='DSE Knowledge Workbench',version='0.1.0',lifespan=lifespan)
    app.state.store=store
    @app.middleware('http')
    async def guards(request:Request,call_next):
        if request.method in ('POST','PUT','PATCH','DELETE'):
            origin=request.headers.get('origin')
            if origin and urlsplit(origin).netloc!=request.headers.get('host'):
                return JSONResponse({'detail':'Origin does not match this self-hosted workbench'},status_code=403)
            size=0;parts=[]
            async for part in request.stream():
                size+=len(part)
                if size>262144:return JSONResponse({'detail':'Request too large'},status_code=413)
                parts.append(part)
            request._body=b''.join(parts)
        response=await call_next(request)
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['X-Frame-Options']='DENY'
        return response

    @app.exception_handler(ValueError)
    async def value_error(request,exc):return JSONResponse({'detail':'Invalid input or provider contract violation'},status_code=400)
    @app.exception_handler(Exception)
    async def safe_error(request,exc):return JSONResponse({'detail':'Operation failed; inspect private runtime verification'},status_code=503)

    def capabilities():
        return {'native':native.capabilities(),'chat':{'provider':settings.get('CHAT_PROVIDER'),'model':settings.get('CHAT_MODEL_ID')},
                'embedding':{'provider':settings.get('EMBEDDING_PROVIDER'),'model':settings.get('EMBEDDING_MODEL_ID'),'dimensions':768},
                'scope':'100-material pilot; single operator HTTP self-host. Source assertions and proposed designs require scoped validation.',
                'automatic_b300_dse':'not_implemented','performance_simulation':'native HAT run orchestration not yet enabled'}

    @app.get('/api/health')
    def health():
        with store.connection() as c:
            c.execute('SELECT 1')
            tls=bool(c.pgconn.ssl_in_use)
        return {'status':'ok','database':'connected','client_pooler_tls':tls,'version':'0.1.0'}

    @app.get('/api/stats')
    def stats():
        result=store.stats();result['providers']={'chat':settings.get('CHAT_MODEL_ID'),'embedding':settings.get('EMBEDDING_MODEL_ID')};result['capabilities']=capabilities();return result
    @app.get('/api/capabilities')
    def get_capabilities():return capabilities()
    @app.get('/api/materials')
    def materials(q:str='',category:str='',offset:int=Query(0,ge=0),limit:int=Query(25,ge=1,le=100)):
        return store.materials(q[:2000],category[:80],offset,limit)
    @app.get('/api/materials/{mid}')
    def material(mid:str):
        result=store.material_detail(mid)
        if not result:raise HTTPException(404,'Material not found')
        return result
    @app.post('/api/search')
    def search(body:SearchBody):return retriever.search(body.query,body.category,body.limit)
    @app.get('/api/graph')
    def graph(query:str='',limit:int=Query(80,ge=1,le=200)):return store.graph(query[:1000],limit)
    @app.get('/api/decisions')
    def decisions():return {'items':store.rows('SELECT id,kind,question,result,created_at FROM decisions ORDER BY created_at DESC LIMIT 100')}
    @app.post('/api/decisions',status_code=202)
    def decision(body:DecisionBody):return {'job_id':store.new_job('decision',body.model_dump())}
    @app.get('/api/jobs/{jid}')
    def job(jid:str):
        result=store.one('SELECT id,status,result,error,attempts,created_at,updated_at FROM jobs WHERE id=%s',(jid,))
        if not result:raise HTTPException(404,'Job not found')
        return result
    @app.get('/api/decisions/{did}')
    def get_decision(did:str):
        result=store.one('SELECT * FROM decisions WHERE id=%s',(did,))
        if not result:raise HTTPException(404,'Decision not found')
        return result
    @app.post('/api/feedback')
    def feedback(body:FeedbackBody):
        try:return engine.feedback(body.model_dump())
        except LookupError:raise HTTPException(404,'Decision not found')
    @app.get('/api/gaps')
    def gaps():return {'items':store.rows('SELECT * FROM gaps ORDER BY created_at DESC LIMIT 100')}
    @app.get('/api/experiences')
    def experiences(q:str='DSE'):return native.query_experiences(q[:2000])
    @app.get('/api/experiments')
    def experiments():return {'items':store.rows('SELECT * FROM experiments ORDER BY created_at DESC LIMIT 100')}
    @app.post('/api/experiments')
    def experiment(body:ExperimentBody):
        import uuid
        metrics=[x.model_dump() for x in body.metrics];validate_metrics(metrics);eid=uuid.uuid4().hex
        store.execute('INSERT INTO experiments(id,name,cohort,method,metrics,context) VALUES(%s,%s,%s,%s,%s,%s)',(eid,body.name,body.cohort,body.method,Jsonb(metrics),Jsonb(body.context)))
        return {'id':eid,'status':'stored','method':body.method}
    @app.post('/api/experiments/compare')
    def compare(body:CompareBody):
        b=store.one('SELECT * FROM experiments WHERE id=%s',(body.baseline_id,));c=store.one('SELECT * FROM experiments WHERE id=%s',(body.candidate_id,))
        if not b or not c:raise HTTPException(404,'Experiment not found')
        return compare_experiments(b,c)
    @app.post('/api/validate/hardware')
    def hardware(body:HardwareBody):return native.validate_hardware(body.source)

    web=Path(settings.get('DSE_WEB_ROOT',str(Path(__file__).resolve().parents[2]/'web')))
    app.mount('/static',StaticFiles(directory=web),name='static')
    @app.get('/')
    def index():return FileResponse(web/'index.html')
    return app
