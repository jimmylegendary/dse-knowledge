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

    def assess_material(self, material_id, role, metadata):
        """Revision-bound advisory annotation, committed together with its audit event."""
        from .knowledge import SOURCE_ROLES
        if role not in SOURCE_ROLES:
            raise ValueError('material_role_invalid')
        proof=dict(metadata)
        with self.connection() as c:
            material=c.execute('SELECT id,role,role_metadata FROM materials WHERE id=%s FOR UPDATE',(str(material_id),)).fetchone()
            if not material:raise ValueError('material_not_found')
            revision=c.execute('SELECT id,sha256 FROM revisions WHERE material_id=%s ORDER BY created_at DESC,id DESC LIMIT 1',(str(material_id),)).fetchone()
            if not revision or proof.get('revision_sha256')!=revision['sha256']:
                raise ValueError('material_role_revision_mismatch')
            proof.update(schema_version='source-role/v1',revision_id=revision['id'],advisory=True,
                         independent_validations=0)
            proof['assessment_id']=identity('role',material_id,role,json.dumps(proof,sort_keys=True,ensure_ascii=False))
            c.execute('UPDATE materials SET role=%s,role_metadata=%s WHERE id=%s',(role,Jsonb(proof),str(material_id)))
            c.execute('INSERT INTO ingest_events(id,material_id,status,detail) VALUES(%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING',
                      (proof['assessment_id'],str(material_id),'role_assessed',Jsonb({'role':role,**proof})))
        return proof

    def put_claim_context(self, claim_id, context, metadata):
        """Validate against canonical source bytes before appending an annotation."""
        from .knowledge import validate_claim_context
        with self.connection() as c:
            claim=c.execute('SELECT * FROM claims WHERE id=%s',(claim_id,)).fetchone()
            if not claim:raise ValueError('claim_not_found')
            revision=c.execute('SELECT * FROM revisions WHERE id=%s',(claim['revision_id'],)).fetchone()
            chunks=c.execute('SELECT id,material_id,revision_id,text,start_offset AS start,end_offset AS end FROM chunks WHERE revision_id=%s ORDER BY start_offset',(revision['id'],)).fetchall()
            if (revision['material_id']!=claim['material_id'] or not any(x['id']==claim['chunk_id'] for x in chunks)
                    or any(x['material_id']!=claim['material_id'] for x in chunks)):
                raise ValueError('claim_material_revision_chunk_mismatch')
            document={'material':{'id':claim['material_id']},'text':revision['content'],
                      'revision':{'id':revision['id'],'sha256':revision['sha256']},'chunks':chunks}
            # Callers supply the raw schema, never their own allegedly validated proof.
            validated=validate_claim_context(context,document)
            aid=identity('context',claim_id,revision['sha256'],json.dumps(validated,sort_keys=True,ensure_ascii=False))
            proof={**metadata,'revision_sha256':revision['sha256'],'validation':'literal_grounded_unverified_association',
                   'use_policy':'source_assertion_only','independent_validations':0}
            c.execute('''INSERT INTO claim_annotations(id,claim_id,revision_id,version,context,metadata)
              VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING''',
                      (aid,claim_id,revision['id'],'claim-context/v1',Jsonb(validated),Jsonb(proof)))
            self._put_topic_links(c,claim,chunks,revision,validated)
        return aid

    @staticmethod
    def _put_topic_links(c,claim,chunks,revision,context=None):
        from .knowledge import canonical_topic_mentions
        chunks_by_id={x['id']:x for x in chunks}
        evidence=[{'chunk_id':claim['chunk_id'],'quote':claim['quote'],
                   'source_start':claim.get('metadata',{}).get('source_start')}]
        for group in ('parameters','conditions'):
            evidence.extend(x['evidence'] for x in (context or {}).get(group,[]))
        source_id=identity('entity',' '.join(claim['subject'].casefold().split())[:400])
        for item in evidence:
            chunk=chunks_by_id.get(item['chunk_id']);quote=item['quote']
            if not chunk or quote not in chunk['text']:raise ValueError('topic_evidence_mismatch')
            for topic in canonical_topic_mentions(quote):
                key=topic['key'];tid=identity('topic',key)
                c.execute('''INSERT INTO entities(id,label,kind,normalized,metadata) VALUES(%s,%s,%s,%s,%s)
                  ON CONFLICT(normalized) DO NOTHING''',
                          (tid,topic['label'],topic['kind'],'topic:v1:'+key,Jsonb({'topic_key':key,'registry_version':'v1'})))
                start=item.get('source_start')
                if start is None:
                    if chunk['text'].count(quote)!=1:raise ValueError('topic_quote_ambiguous')
                    start=chunk['start']+chunk['text'].find(quote)
                if (type(start) is not int or start<chunk['start'] or start+len(quote)>chunk['end']
                        or chunk['text'][start-chunk['start']:start-chunk['start']+len(quote)]!=quote):
                    raise ValueError('topic_quote_offset_mismatch')
                proof={'scope':'evidence_topic_not_property','registry_version':'v1','quote':quote,
                       'source_start':start,'source_end':start+len(quote),'revision_sha256':revision['sha256']}
                c.execute('''INSERT INTO edges(id,source,target,relation,claim_id,material_id,relation_kind,evidence_chunk_id,metadata)
                  VALUES(%s,%s,%s,'mentions',%s,%s,'topic',%s,%s) ON CONFLICT(id) DO NOTHING''',
                          (identity('topic-edge',claim['id'],tid,item['chunk_id'],quote),source_id,tid,claim['id'],claim['material_id'],item['chunk_id'],Jsonb(proof)))

    def backfill_topic_links(self):
        """Deterministic projection of existing exact Claim quotes; no model calls."""
        with self.connection() as c:
            claims=c.execute('SELECT * FROM claims ORDER BY id').fetchall()
            annotations=c.execute('SELECT DISTINCT ON(claim_id) claim_id,context FROM claim_annotations ORDER BY claim_id,created_at DESC,id DESC').fetchall()
            contexts={x['claim_id']:x['context'] for x in annotations}
            for claim in claims:
                revision=c.execute('SELECT id,sha256 FROM revisions WHERE id=%s',(claim['revision_id'],)).fetchone()
                context=contexts.get(claim['id'],{})
                ids={claim['chunk_id']}|{x['evidence']['chunk_id'] for group in ('parameters','conditions') for x in context.get(group,[])}
                chunks=c.execute('SELECT id,text,start_offset AS start,end_offset AS end FROM chunks WHERE revision_id=%s AND id=ANY(%s)',(claim['revision_id'],list(ids))).fetchall()
                self._put_topic_links(c,claim,chunks,revision,context)
        return len(claims)

    def context_projection(self, chunk_ids, max_per_chunk=2, full=False):
        if not chunk_ids:return {}
        rows=self.rows('''SELECT cl.id AS claim_id,cl.chunk_id,a.id AS annotation_id,a.version,a.context,a.metadata
          FROM claims cl JOIN LATERAL (SELECT * FROM claim_annotations x WHERE x.claim_id=cl.id ORDER BY created_at DESC,id DESC LIMIT 1) a ON true
          WHERE cl.chunk_id=ANY(%s) ORDER BY cl.chunk_id,a.created_at DESC,a.id''',(list(chunk_ids),))
        result={}
        for row in rows:
            items=result.setdefault(row['chunk_id'],[])
            if len(items)>=max_per_chunk:continue
            context=row['context']
            parameters=context.get('parameters',[]);conditions=context.get('conditions',[]);note=context.get('source_scope_note','')
            items.append({'annotation_id':row['annotation_id'],'claim_id':row['claim_id'],'version':row['version'],
                          'parameters':parameters if full else parameters[:6],'conditions':conditions if full else conditions[:8],
                          'source_scope_note':note if full else note[:1200],
                          'projection':{'parameters_total':len(parameters),'conditions_total':len(conditions),
                                        'truncated':False if full else len(parameters)>6 or len(conditions)>8 or len(note)>1200},
                          'use_policy':'source_assertion_only','validation':'literal_grounded_unverified_association',
                          'revision_sha256':row['metadata'].get('revision_sha256'),'independent_validations':0})
        return result

    def put_material(self, prepared, embeddings):
        m=prepared['material']; rev=prepared['revision']; mid=str(m.get('id') or m.get('mid'))
        rid=identity(mid,rev['sha256']); chunks=prepared['chunks']
        if not chunks or len(chunks)!=len(embeddings):
            raise ValueError('Chunk/embedding count mismatch')
        with self.connection() as c:
            c.execute('''INSERT INTO materials(id,title,url,source,category,material_type,summary,status,scope,metadata)
              VALUES(%s,%s,%s,%s,%s,%s,%s,'ingested',%s,%s)
              ON CONFLICT(id) DO UPDATE SET status='ingested',scope=excluded.scope,metadata=materials.metadata||excluded.metadata''',
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
        projection=self.context_projection([x['id'] for x in chunks],max_per_chunk=32,full=True)
        for chunk in chunks:chunk['claim_contexts']=projection.get(chunk['id'],[])
        annotated={a['claim_id'] for values in projection.values() for a in values}
        coverage={'claims_total':len(claims),'claims_annotated':len(annotated),
                  'status':'no_claims' if not claims else ('annotations_available' if len(annotated)==len(claims) else 'needs_review'),
                  'scope':'bounded_source_excerpts_not_exhaustive','independent_validations':0}
        return {'material':material,'chunks':chunks,'claims':claims,'annotation_coverage':coverage}

    def materials(self,q='',category='',offset=0,limit=25):
        where="WHERE (%s='' OR title ILIKE %s OR summary ILIKE %s) AND (%s='' OR category=%s)"
        args=(q,'%'+q+'%','%'+q+'%',category,category)
        total=self.one('SELECT count(*) AS n FROM materials '+where,args)['n']
        rows=self.rows('SELECT * FROM materials '+where+' ORDER BY category,title LIMIT %s OFFSET %s',(*args,limit,offset))
        return {'items':rows,'total':total}

    def graph(self,query='',limit=80):
        edges=self.rows('''SELECT e.*,s.label AS source_label,t.label AS target_label,s.kind AS source_kind,t.kind AS target_kind FROM edges e
          JOIN entities s ON s.id=e.source JOIN entities t ON t.id=e.target
          WHERE (%s='' OR s.label ILIKE %s OR t.label ILIKE %s OR e.relation ILIKE %s) ORDER BY e.relation_kind DESC,e.id LIMIT %s''',
          (query,'%'+query+'%','%'+query+'%','%'+query+'%',limit))
        nodes={}
        for e in edges:
            for key in ('source','target'):nodes[e[key]]={'id':e[key],'label':e[key+'_label'],'kind':e[key+'_kind']}
        return {'nodes':list(nodes.values()),'edges':edges}

    def stats(self):
        result={}
        for table in ('materials','chunks','claims','entities','edges','decisions','gaps','jobs','experiments'):
            result[table]=self.one('SELECT count(*) AS n FROM '+table)['n']
        result['category_counts']=self.rows('SELECT category,count(*) AS count FROM materials GROUP BY category ORDER BY category')
        result['scope_counts']=self.rows('SELECT scope,count(*) AS count FROM materials GROUP BY scope')
        result['role_counts']=self.rows('SELECT role,count(*) AS count FROM materials GROUP BY role ORDER BY role')
        result['claim_annotations']=self.one('SELECT count(*) AS n FROM claim_annotations')['n']
        result['edge_kind_counts']=self.rows('SELECT relation_kind,count(*) AS count FROM edges GROUP BY relation_kind ORDER BY relation_kind')
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

    def contextual_corpus_manifest(self, connection=None):
        """Fingerprint the baseline-visible current-revision cohort without returning source text."""
        sql = '''/* contextual_corpus_manifest */
          WITH latest_revision AS MATERIALIZED (
            SELECT DISTINCT ON (material_id) material_id,id AS revision_id
            FROM revisions ORDER BY material_id,created_at DESC,id DESC
          ), latest_content AS MATERIALIZED (
            SELECT lr.material_id,lr.revision_id,r.sha256 AS revision_sha256,
                   md5(r.content) AS normalized_content_md5,m.category,m.role
            FROM latest_revision lr JOIN revisions r
              ON r.material_id=lr.material_id AND r.id=lr.revision_id
            JOIN materials m ON m.id=lr.material_id
          ), current_chunks AS MATERIALIZED (
            SELECT c.material_id,c.revision_id,c.id AS chunk_id,c.start_offset,c.end_offset,
                   lc.revision_sha256,lc.normalized_content_md5,lc.category,lc.role
            FROM chunks c JOIN latest_content lc
              ON lc.material_id=c.material_id AND lc.revision_id=c.revision_id
          ), eligible_chunks AS MATERIALIZED (
            SELECT * FROM current_chunks
            WHERE COALESCE(role,'unclassified') <> 'out_of_scope'
          )
          SELECT md5(COALESCE((SELECT string_agg(
                   concat_ws(chr(31),material_id,revision_id,revision_sha256,
                     normalized_content_md5,category,chunk_id,
                     start_offset::text,end_offset::text),
                   chr(30) ORDER BY material_id,start_offset,chunk_id) FROM eligible_chunks),'')) AS corpus_hash,
                 (SELECT count(DISTINCT material_id)::bigint FROM eligible_chunks) AS source_count,
                 (SELECT count(*)::bigint FROM eligible_chunks) AS chunk_count,
                 (SELECT count(DISTINCT material_id)::bigint FROM current_chunks) AS canonical_source_count,
                 (SELECT count(*)::bigint FROM current_chunks) AS canonical_chunk_count'''
        if connection is not None:
            row = connection.execute(sql).fetchone()
        else:
            with self.connection() as conn:
                row = conn.execute(sql).fetchone()
        if not isinstance(row, dict):
            raise ValueError('contextual_corpus_manifest_invalid')
        corpus_hash = row.get('corpus_hash')
        source_count = row.get('source_count')
        chunk_count = row.get('chunk_count')
        canonical_source_count = row.get('canonical_source_count')
        canonical_chunk_count = row.get('canonical_chunk_count')
        if (not isinstance(corpus_hash, str) or len(corpus_hash) != 32
                or type(source_count) is not int or source_count <= 0
                or type(chunk_count) is not int or chunk_count <= 0 or chunk_count > 50000
                or type(canonical_source_count) is not int or canonical_source_count < source_count
                or type(canonical_chunk_count) is not int or canonical_chunk_count < chunk_count):
            raise ValueError('contextual_corpus_manifest_invalid')
        return {'corpus_hash': corpus_hash, 'source_count': source_count, 'chunk_count': chunk_count,
                'canonical_source_count': canonical_source_count,
                'canonical_chunk_count': canonical_chunk_count}

    def contextual_document_refs(self):
        return self.rows('''WITH latest_revision AS MATERIALIZED (
              SELECT DISTINCT ON (material_id) material_id,id AS revision_id
              FROM revisions ORDER BY material_id,created_at DESC,id DESC)
            SELECT m.id AS material_id,r.id AS revision_id,r.sha256 AS revision_sha256,
                   r.metadata->>'normalized_content_sha256' AS stored_normalized_content_sha256,m.category
            FROM materials m JOIN latest_revision lr ON lr.material_id=m.id
            JOIN revisions r ON r.id=lr.revision_id
            WHERE EXISTS (SELECT 1 FROM chunks c WHERE c.material_id=m.id AND c.revision_id=r.id)
              AND COALESCE(m.role,'unclassified') <> 'out_of_scope'
            ORDER BY m.id''')

    def contextual_document(self, material_id, revision_id):
        document = self.one('''SELECT m.id AS material_id,r.id AS revision_id,r.sha256 AS revision_sha256,
                r.metadata,m.category,r.content
            FROM materials m JOIN revisions r ON r.material_id=m.id
            WHERE m.id=%s AND r.id=%s''', (material_id, revision_id))
        if not document:
            raise ValueError('contextual_source_revision_unavailable')
        normalized_sha256 = hashlib.sha256(document['content'].encode('utf-8')).hexdigest()
        stored_sha256 = (document.get('metadata') or {}).get('normalized_content_sha256')
        if stored_sha256 and stored_sha256 != normalized_sha256:
            raise ValueError('contextual_normalized_content_hash_mismatch')
        chunks = self.rows('''SELECT id,start_offset,end_offset,text FROM chunks
            WHERE material_id=%s AND revision_id=%s ORDER BY start_offset,id''', (material_id, revision_id))
        if not chunks:
            raise ValueError('contextual_source_chunks_unavailable')
        return {**document, 'normalized_content_sha256': normalized_sha256, 'chunks': chunks}

    def contextual_normalized_content_manifest(self):
        """Stream current normalized bodies and validate any stored normalized hash metadata."""
        from .contextual_index import normalized_content_manifest_hash

        sql = '''WITH latest_revision AS MATERIALIZED (
              SELECT DISTINCT ON (material_id) material_id,id AS revision_id
              FROM revisions ORDER BY material_id,created_at DESC,id DESC)
            SELECT m.id AS material_id,r.id AS revision_id,r.sha256 AS revision_sha256,
                   r.metadata->>'normalized_content_sha256' AS normalized_content_sha256,r.content
            FROM materials m JOIN latest_revision lr ON lr.material_id=m.id
            JOIN revisions r ON r.id=lr.revision_id
            WHERE EXISTS (SELECT 1 FROM chunks c WHERE c.material_id=m.id AND c.revision_id=r.id)
              AND COALESCE(m.role,'unclassified') <> 'out_of_scope'
            ORDER BY m.id'''
        sources = []
        with self.connection() as connection:
            with connection.cursor(name='dse_contextual_normalized_manifest') as cursor:
                cursor.execute(sql)
                while rows := cursor.fetchmany(16):
                    for row in rows:
                        normalized_sha256 = hashlib.sha256(row['content'].encode('utf-8')).hexdigest()
                        if (row.get('normalized_content_sha256')
                                and row['normalized_content_sha256'] != normalized_sha256):
                            raise ValueError('contextual_normalized_content_hash_mismatch')
                        sources.append({
                            'material_id': row['material_id'], 'revision_id': row['revision_id'],
                            'revision_sha256': row['revision_sha256'],
                            'normalized_content_sha256': normalized_sha256,
                        })
        return normalized_content_manifest_hash(sources)

    def contextual_hydrate_candidates(self, candidates, connection=None):
        """Rebind projected IDs to current PostgreSQL revisions before ranking payloads."""
        if not isinstance(candidates, (list, tuple)):
            raise ValueError('contextual_candidate_set_invalid')
        expected = {}
        for item in candidates:
            if not isinstance(item, dict):
                raise ValueError('contextual_candidate_set_invalid')
            chunk_id, material_id, revision_id = (item.get('chunk_id'), item.get('material_id'), item.get('revision_id'))
            if not all(isinstance(value, str) and value for value in (chunk_id, material_id, revision_id)):
                raise ValueError('contextual_candidate_set_invalid')
            binding = (material_id, revision_id)
            if chunk_id in expected and expected[chunk_id] != binding:
                raise ValueError('contextual_candidate_binding_conflict')
            expected[chunk_id] = binding
        if not expected:
            return []
        ids = list(expected)
        sql = '''/* contextual_candidate_hydration */
          WITH latest_revision AS MATERIALIZED (
            SELECT DISTINCT ON (material_id) material_id,id AS revision_id
            FROM revisions ORDER BY material_id,created_at DESC,id DESC
          )
          SELECT c.id AS chunk_id,c.material_id,c.revision_id,c.start_offset,c.end_offset,c.text,
                 m.title,m.url,m.source,m.category,m.scope,m.role,m.role_metadata
          FROM chunks c JOIN materials m ON m.id=c.material_id
          JOIN latest_revision lr ON lr.material_id=c.material_id AND lr.revision_id=c.revision_id
          WHERE c.id=ANY(%s::text[])
            AND COALESCE(m.role,'unclassified') <> 'out_of_scope'
          ORDER BY array_position(%s::text[],c.id)'''
        if connection is not None:
            rows = connection.execute(sql, (ids, ids)).fetchall()
        else:
            rows = self.rows(sql, (ids, ids))
        indexed = {str(row['chunk_id']): row for row in rows}
        if set(indexed) != set(expected):
            raise ValueError('contextual_candidate_stale')
        for chunk_id, (material_id, revision_id) in expected.items():
            row = indexed[chunk_id]
            if row.get('material_id') != material_id or row.get('revision_id') != revision_id:
                raise ValueError('contextual_candidate_stale')
        return [indexed[chunk_id] for chunk_id in ids]

    def ingest_event(self,mid,status,detail):
        self.execute('INSERT INTO ingest_events(id,material_id,status,detail) VALUES(%s,%s,%s,%s)',(uuid.uuid4().hex,str(mid),status,Jsonb(detail)))
