from contextlib import contextmanager
import pytest
from dse_knowledge.config import Settings
from dse_knowledge.db import Store

class Connection:
    def __init__(self):self.inserts=[]
    def execute(self,sql,args=()):
        if sql.startswith('INSERT INTO claims'):self.inserts.append(args)
        return self
    def fetchone(self):return {'id':'c1','text':'prefix quoted source has exact whitespace suffix','revision_id':'r1','start_offset':100}


def claim():
    return dict(chunk_id='c1',quote=' quoted source has exact whitespace ',subject='GPU',predicate='supports',object='layout',summary='A supported statement',source_start=106,source_end=106+len(' quoted source has exact whitespace '))

def store():
    s=Store(Settings({}));c=Connection()
    @contextmanager
    def connection():yield c
    s.connection=connection
    return s,c

def test_quote_and_absolute_offsets_are_preserved_together():
    s,c=store();s.put_claims('m1',[claim()],{})
    args=c.inserts[0];quote=args[9];metadata=args[11].obj
    assert quote==claim()['quote']
    assert metadata['source_end']-metadata['source_start']==len(quote)

def test_inconsistent_declared_offsets_are_rejected():
    s,_=store();bad=claim();bad['source_start']=107
    with pytest.raises(ValueError):s.put_claims('m1',[bad],{})
