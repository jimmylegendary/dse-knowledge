"""Reciprocal rank fusion across lexical, dense and source-linked graph channels."""
from __future__ import annotations
import uuid
from .db import vector_literal


def reciprocal_rank_fusion(channels,limit=12):
    merged={}
    for channel,rows in channels.items():
        for rank,row in enumerate(rows,1):
            item=merged.setdefault(row['chunk_id'],dict(row,scores={},rank=0))
            item['scores'][channel]=1/(60+rank)
            item['rank']+=1/(60+rank)
    return sorted(merged.values(),key=lambda x:(-x['rank'],x['chunk_id']))[:limit]


class Retriever:
    def __init__(self,store,embedding):self.store=store;self.embedding=embedding

    def search(self,query,category='',limit=12):
        limit=max(1,min(int(limit),30));query=query.strip()[:2000]
        if not query:raise ValueError('Query required')
        emb=self.embedding.embed([query],task='search_query')[0]
        fields='c.id AS chunk_id,c.material_id,c.revision_id,c.text,m.title,m.url,m.category,m.scope'
        common=' FROM chunks c JOIN materials m ON m.id=c.material_id '
        args=(category,category)
        dense=self.store.rows('SELECT '+fields+common+"WHERE (%s='' OR m.category=%s) ORDER BY c.embedding <=> %s::extensions.vector LIMIT 40",(*args,vector_literal(emb)))
        lexical=self.store.rows('SELECT '+fields+common+"WHERE (%s='' OR m.category=%s) AND c.search_vector @@ websearch_to_tsquery('english',%s) ORDER BY ts_rank_cd(c.search_vector,websearch_to_tsquery('english',%s)) DESC LIMIT 40",(*args,query,query))
        exact=self.store.rows('SELECT '+fields+common+"WHERE (%s='' OR m.category=%s) AND m.title ILIKE %s ORDER BY m.title,c.start_offset LIMIT 20",(*args,'%'+query+'%'))
        tokens=[x for x in query.split() if len(x)>2][:8]
        graph=self.store.rows('SELECT DISTINCT '+fields+common+''' JOIN claims cl ON cl.chunk_id=c.id JOIN edges e ON e.claim_id=cl.id
            JOIN entities s ON s.id=e.source JOIN entities t ON t.id=e.target
            WHERE (%s='' OR m.category=%s) AND EXISTS (SELECT 1 FROM unnest(%s::text[]) word WHERE s.normalized LIKE '%%'||lower(word)||'%%' OR t.normalized LIKE '%%'||lower(word)||'%%')
            ORDER BY c.id LIMIT 30''',(*args,tokens)) if tokens else []
        items=reciprocal_rank_fusion({'lexical':lexical,'dense':dense,'graph':graph,'exact':exact},limit)
        # Avoid a long source monopolising the evidence bundle.
        diverse=[];per_material={}
        for x in items:
            n=per_material.get(x['material_id'],0)
            if n<3:diverse.append(x);per_material[x['material_id']]=n+1
        self.store.invocation('embedding','query',getattr(self.embedding,'last_metadata',{}))
        return {'query':query,'items':diverse,'channels':{k:len(v) for k,v in {'lexical':lexical,'dense':dense,'graph':graph,'exact':exact}.items()},'trace_id':uuid.uuid4().hex,
                'limitations':['Retrieval ranks source evidence; it does not establish physical buildability or measured performance.']}
