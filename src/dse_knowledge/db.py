"""Canonical PostgreSQL ledger. SQL values are bound, never interpolated."""
from __future__ import annotations
import hashlib
import json
import uuid
from contextlib import contextmanager
from pathlib import Path
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from .config import Settings


def identity(*parts) -> str:
    return hashlib.sha256('\x1f'.join(str(x) for x in parts).encode()).hexdigest()[:32]


def vector_literal(values) -> str:
    import math
    if len(values) != 768 or any(isinstance(x, bool) or not isinstance(x,(int,float)) or not math.isfinite(x) for x in values):
        raise ValueError('Expected finite 768-dimensional embedding')
    return '['+','.join(format(float(x),'.9g') for x in values)+']'


class Store:
    def __init__(self, settings: Settings):
        self.settings=settings

    @contextmanager
    def connection(self):
        with psycopg.connect(**self.settings.db_kwargs(), row_factory=dict_row) as conn:
            yield conn

    def rows(self, sql, args=()):
        with self.connection() as c:
            return c.execute(sql,args).fetchall()

    def one(self, sql, args=()):
        rows=self.rows(sql,args)
        return rows[0] if rows else None

    def execute(self,sql,args=()):
        with self.connection() as c:
            c.execute(sql,args)

    def migrate(self, path: Path):
        with self.connection() as c:
            c.execute(path.read_text())

    def has_material(self, material_id):
        row=self.one('SELECT status FROM materials WHERE id=%s',(str(material_id),))
        return bool(row and row['status']=='ingested')

    def put_material(self, prepared, embeddings):
        m=prepared['material']; rev=prepared['revision']; mid=str(m.get('id') or m.get('mid'))
        rid=identity(mid,rev['sha256']); chunks=prepared['chunks']
        if not chunks or len(chunks)!=len(embeddings):
            raise ValueError('Chunk/embedding count mismatch')
        with self.connection() as c:
            c.execute('''INSERT INTO materials(id,title,url,source,category,material_type,summary,status,scope,metadata)
              VALUES(%s,%s,%s,%s,%s,%s,%s,'ingested',%s,%s)
              ON CONFLICT(id) DO UPDATE SET status='ingested',scope=excluded.scope,metadata=excluded.metadata''',
              (mid,m['title'],m.get('url') or m['link'],str(m['source']),m['category'],m.get('material_type','document'),m.get('summary',''),rev['scope'],Jsonb({'sample_seed':20261025})))
            c.execute('''INSERT INTO revisions(id,material_id,sha256,url,parser,scope,artifact_path,content,metadata)
              VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING''',
              (rid,mid,rev['sha256'],rev['url'],rev['parser'],rev['scope'],str(rev.get('artifact_path','')),prepared['text'],Jsonb({k:v for k,v in rev.items() if k not in ('artifact_path',)})))
            for chunk,emb in zip(chunks,embeddings,strict=True):
                c.execute('''INSERT INTO chunks(id,revision_id,material_id,start_offset,end_offset,text,search_text,embedding)
                  VALUES(%s,%s,%s,%s,%s,%s,%s,%s::extensions.vector) ON CONFLICT(id) DO NOTHING''',
                  (chunk['id'],rid,mid,chunk['start'],chunk['end'],chunk['text'],m['title']+'\n'+chunk['text'],vector_literal(emb)))
        return rid

    def put_claims(self, material_id, claims, metadata):
        accepted=0
        with self.connection() as c:
            for claim in claims:
                chunk=c.execute('SELECT id,text,revision_id,start_offset FROM chunks WHERE id=%s AND material_id=%s',(claim['chunk_id'],material_id)).fetchone()
                quote=claim['quote']
                if not chunk or len(quote)<16 or quote not in chunk['text']:
                    raise ValueError('Claim must cite exact source quote in its own material')
                start=claim.get('source_start',chunk['start_offset']+chunk['text'].find(quote))
                end=claim.get('source_end',start+len(quote))
                if (type(start) is not int or type(end) is not int or start<chunk['start_offset']
                    or end-start!=len(quote) or chunk['text'][start-chunk['start_offset']:end-chunk['start_offset']]!=quote):
                    raise ValueError('Claim source offsets must match the exact quote')
                cid=identity(material_id,chunk['id'],quote,claim['subject'],claim['predicate'],claim['object'])
                c.execute('''INSERT INTO claims(id,material_id,revision_id,chunk_id,kind,subject,predicate,object,summary,quote,scope,metadata)
                  VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING''',
                  (cid,material_id,chunk['revision_id'],chunk['id'],claim.get('kind','source_assertion'),claim['subject'],claim['predicate'],claim['object'],claim['summary'],quote,claim.get('scope','source_assertion'),Jsonb({**metadata,'source_start':start,'source_end':end})))
                ids=[]
                for label in (claim['subject'],claim['object']):
                    normalized=' '.join(label.casefold().split())[:400]; eid=identity('entity',normalized);ids.append(eid)
                    c.execute('INSERT INTO entities(id,label,normalized) VALUES(%s,%s,%s) ON CONFLICT(normalized) DO NOTHING',(eid,label[:400],normalized))
                c.execute('INSERT INTO edges(id,source,target,relation,claim_id,material_id) VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING',
                          (identity(cid,*ids),*ids,claim['predicate'][:200],cid,material_id))
                accepted+=1
        return accepted

    def material_detail(self, mid):
        material=self.one('SELECT * FROM materials WHERE id=%s',(mid,))
        if not material:return None
        chunks=self.rows('SELECT id,revision_id,text,start_offset AS start,end_offset AS end FROM chunks WHERE material_id=%s ORDER BY start_offset',(mid,))
        claims=self.rows('SELECT * FROM claims WHERE material_id=%s ORDER BY created_at',(mid,))
        return {'material':material,'chunks':chunks,'claims':claims}

    def materials(self,q='',category='',offset=0,limit=25):
        where="WHERE (%s='' OR title ILIKE %s OR summary ILIKE %s) AND (%s='' OR category=%s)"
        args=(q,'%'+q+'%','%'+q+'%',category,category)
        total=self.one('SELECT count(*) AS n FROM materials '+where,args)['n']
        rows=self.rows('SELECT * FROM materials '+where+' ORDER BY category,title LIMIT %s OFFSET %s',(*args,limit,offset))
        return {'items':rows,'total':total}

    def graph(self,query='',limit=80):
        edges=self.rows('''SELECT e.*,s.label AS source_label,t.label AS target_label FROM edges e
          JOIN entities s ON s.id=e.source JOIN entities t ON t.id=e.target
          WHERE (%s='' OR s.label ILIKE %s OR t.label ILIKE %s OR e.relation ILIKE %s) LIMIT %s''',
          (query,'%'+query+'%','%'+query+'%','%'+query+'%',limit))
        nodes={}
        for e in edges:
            for key in ('source','target'):nodes[e[key]]={'id':e[key],'label':e[key+'_label'],'kind':'concept'}
        return {'nodes':list(nodes.values()),'edges':edges}

    def stats(self):
        result={}
        for table in ('materials','chunks','claims','entities','edges','decisions','gaps','jobs','experiments'):
            result[table]=self.one('SELECT count(*) AS n FROM '+table)['n']
        result['category_counts']=self.rows('SELECT category,count(*) AS count FROM materials GROUP BY category ORDER BY category')
        result['scope_counts']=self.rows('SELECT scope,count(*) AS count FROM materials GROUP BY scope')
        return result

    def new_job(self, kind, payload):
        jid=uuid.uuid4().hex
        with self.connection() as c:
            c.execute("SELECT pg_advisory_xact_lock(28762025)")
            if c.execute("SELECT count(*) AS n FROM jobs WHERE status IN ('queued','running')").fetchone()['n']>=32:
                raise ValueError('Queue capacity reached')
            c.execute('INSERT INTO jobs(id,kind,payload) VALUES(%s,%s,%s)',(jid,kind,Jsonb(payload)))
        return jid

    def claim_job(self):
        with self.connection() as c:
            row=c.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1").fetchone()
            if row:c.execute("UPDATE jobs SET status='running',attempts=attempts+1,updated_at=now() WHERE id=%s",(row['id'],))
            return row

    def finish_job(self,jid,result=None,error=None):
        self.execute('UPDATE jobs SET status=%s,result=%s,error=%s,updated_at=now() WHERE id=%s',('failed' if error else 'succeeded',Jsonb(result) if result else None,error,jid))

    def invocation(self,provider,purpose,metadata):
        self.execute('INSERT INTO invocations(id,provider,purpose,metadata) VALUES(%s,%s,%s,%s)',(uuid.uuid4().hex,provider,purpose,Jsonb(metadata)))

    def ingest_event(self,mid,status,detail):
        self.execute('INSERT INTO ingest_events(id,material_id,status,detail) VALUES(%s,%s,%s,%s)',(uuid.uuid4().hex,str(mid),status,Jsonb(detail)))
