#!/usr/bin/env python3
"""Exercise actual PG leases/policy/receipt SQL in an always-rolled-back fixture.

This does not invoke providers or establish a whole-product episode result.
"""
from contextlib import contextmanager
from datetime import datetime,timezone
import argparse
import json
import uuid
from pathlib import Path
from dse_knowledge.config import Settings
from dse_knowledge.db import Store
from dse_knowledge.collection import CollectionManager
from dse_knowledge.pipeline import save_json


def run():
    settings=Settings.load();store=Store(settings);report={}
    with store.connection() as conn:
        with conn.transaction(force_rollback=True):
            @contextmanager
            def reuse():yield conn
            test=Store(settings);test.connection=reuse
            def forbidden(*args):raise AssertionError('No source/provider execution in PG contract probe')
            handlers={k:forbidden for k in ('acquire','assess','index','extract')}
            manager=CollectionManager(test,settings.data_root,handlers,{'heartbeat_interval_seconds':None,'initial_artifact_budget_bytes':256*1024**2})
            batch_id='qa-rollback-'+uuid.uuid4().hex
            initial=manager.create_batch(batch_id,[{'material_id':'probe-a'},{'material_id':'probe-b'},{'material_id':'probe-c'}],2)
            assert initial['reserved_count']==2
            restored=CollectionManager.from_batch(test,settings.data_root,handlers,batch_id,{'artifact_budget_bytes':4*1024**3,'heartbeat_interval_seconds':None})
            assert restored.artifact_budget==256*1024**2
            now=datetime.now(timezone.utc)
            row=manager.repository.claim_next(batch_id,'probe-a','probe-a:owner',now,120,manager.stage_caps,4)
            assert row is not None
            assert manager.repository.claim_next(batch_id,'probe-b','probe-b:owner',now,120,manager.stage_caps,4) is None
            assert manager.repository.complete(batch_id,row['material_id'],'wrong:owner',now,'acquired','assess',{}, {},'acquire',0) is False
            assert manager.repository.heartbeat(batch_id,row['material_id'],'probe-a:owner',now,120) is True
            assert manager.repository.complete(batch_id,row['material_id'],'probe-a:owner',now,'acquired','assess',{'source_revision_sha256':'a'*64},{'provider':'codex_cli','usage':{'input_tokens':5}},'acquire',0) is True
            receipt=conn.execute("SELECT metadata FROM invocations WHERE provider='collection_stage' AND purpose='stage_receipt' ORDER BY created_at DESC LIMIT 1").fetchone()['metadata']
            assert receipt['authoritative_provider_usage'] is False and 'usage' not in receipt
            assert manager.summary(batch_id)['reserved_count']==2
            report.update(policy_reload=True,fetch_cap_one=True,owner_fencing=True,heartbeat=True,atomic_non_provider_receipt=True)
    report['rollback_probe_rows']=store.one('SELECT count(*) n FROM collection_batches WHERE id=%s',(batch_id,))['n']
    assert report['rollback_probe_rows']==0
    report['status']='passed'
    report['scope']='Actual PostgreSQL contract checks; no provider calls; all fixture rows rolled back.'
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path)
    args=parser.parse_args();report=run()
    if args.output:save_json(args.output,report)
    print(json.dumps(report))
