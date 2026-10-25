#!/usr/bin/env python3
"""Exercise actual PG leases/policy/receipt SQL in an always-rolled-back fixture.

This does not invoke providers or establish a whole-product episode result.
"""
from contextlib import contextmanager
from datetime import datetime,timezone,timedelta
import argparse
import json
import uuid
from pathlib import Path
from dse_knowledge.config import Settings
from dse_knowledge.db import Store
from dse_knowledge.collection import CollectionManager,RetryableCollectionError
from dse_knowledge.pipeline import save_json


def check_provider_attempt_cap(test,settings,conn):
    """Exercise real PG leases with injected errors; never call a provider."""
    now=[datetime.now(timezone.utc)]
    def forbidden(*args):raise AssertionError('No source/provider execution in PG contract probe')
    handlers={k:forbidden for k in ('acquire','assess','index','extract')}
    policy={'heartbeat_interval_seconds':None,'initial_artifact_budget_bytes':256*1024**2,
            'retry_max_attempts':3,'clock':lambda:now[0]}
    manager=CollectionManager(test,settings.data_root,handlers,policy)
    batch_ids=[]
    def seed(suffix,count):
        batch_id='qa-provider-cap-'+uuid.uuid4().hex
        ids=[suffix+'-failed']+[suffix+'-good-'+str(i) for i in range(count-1)]
        manager.create_batch(batch_id,[{'material_id':mid} for mid in ids],count)
        conn.execute("""UPDATE collection_items SET state='indexed',next_stage='extract',
                     metadata='{"indexed":true,"role":"core_technical"}'::jsonb
                     WHERE batch_id=%s""",(batch_id,))
        batch_ids.append(batch_id)
        return batch_id,ids
    def lease(batch_id,expected,owner):
        row=manager.repository.claim_next(batch_id,'qa-provider-cap',owner,now[0],120,manager.stage_caps,4,manager.retry_max_attempts)
        assert row and row['material_id']==expected
        return row
    def failure(batch_id,row,owner):
        manager._record_retry(batch_id,row,owner,'extract',
                              RetryableCollectionError('probe_timeout',provider='codex_cli'),'qa-provider-cap')
    def item(batch_id,mid):
        return test.one('SELECT state,next_stage,attempts,next_attempt_at,last_error,lease_owner FROM collection_items WHERE batch_id=%s AND material_id=%s',(batch_id,mid))
    def next_time(row):
        now[0]=max(now[0]+timedelta(seconds=1),row['next_attempt_at']+timedelta(seconds=1))

    # Successful other items reset the streak, but must not reset this item's cap.
    batch_id,ids=seed('qa-alternating',3)
    for attempt in range(1,4):
        owner='qa-provider-cap:alternating-'+str(attempt)
        row=lease(batch_id,ids[0],owner)
        assert row['attempts']==attempt
        if attempt==3:
            before=item(batch_id,ids[0])
            streak=test.one('SELECT provider_failures FROM collection_batches WHERE id=%s',(batch_id,))
            failure(batch_id,row,'stale-owner')
            assert item(batch_id,ids[0])==before
            assert test.one('SELECT provider_failures FROM collection_batches WHERE id=%s',(batch_id,))==streak
        failure(batch_id,row,owner)
        failed=item(batch_id,ids[0])
        if attempt<3:
            assert failed['state']=='retry_wait'
            good_owner='qa-provider-cap:good-'+str(attempt)
            good=lease(batch_id,ids[attempt],good_owner)
            assert manager.repository.complete(batch_id,good['material_id'],good_owner,now[0],
                   'complete',None,good['metadata'],{'provider':'codex_cli'},'extract',0)
            assert not test.one('SELECT provider_failures FROM collection_batches WHERE id=%s',(batch_id,))['provider_failures']
            next_time(failed)
    assert failed['state']=='failed' and failed['next_stage'] is None and failed['attempts']==3
    assert failed['last_error']['code']=='provider_retry_exhausted'
    assert failed['last_error']['cause_code']=='probe_timeout'
    assert manager.repository.claim_next(batch_id,'qa-no-fourth','qa-no-fourth:owner',now[0],120,manager.stage_caps,4,manager.retry_max_attempts) is None

    # Exhaustion still increments the provider circuit on the same third failure.
    batch_id,ids=seed('qa-consecutive',1)
    for attempt in range(1,4):
        owner='qa-provider-cap:consecutive-'+str(attempt)
        row=lease(batch_id,ids[0],owner)
        failure(batch_id,row,owner)
        failed=item(batch_id,ids[0])
        if attempt<3:next_time(failed)
    batch=test.one('SELECT state,provider_failures FROM collection_batches WHERE id=%s',(batch_id,))
    assert batch['state']=='blocked' and batch['provider_failures']['extract:codex_cli']==3
    assert failed['state']=='failed' and failed['attempts']==3
    before=failed
    now[0]+=timedelta(seconds=manager.provider_cooldown_seconds+1)
    manager.resume_batch(batch_id,'QA rollback: verify exhausted item is not resurrected')
    assert item(batch_id,ids[0])==before
    assert manager.repository.claim_next(batch_id,'qa-after-resume','qa-after-resume:owner',now[0],120,manager.stage_caps,4,manager.retry_max_attempts) is None

    # Expired attempt at the limit may have no committable provider outcome.
    # Reclaiming that row must clean it up without a new attempt or handler call.
    for known_prior,cap in [(True,3),(False,3),(False,2)]:
        manager=CollectionManager(test,settings.data_root,handlers,dict(policy,retry_max_attempts=cap))
        batch_id,ids=seed('qa-expired-'+str(int(known_prior))+'-'+str(cap),1)
        if known_prior:
            for attempt in range(1,cap):
                owner='qa-provider-cap:known-prior-'+str(attempt)
                row=lease(batch_id,ids[0],owner)
                failure(batch_id,row,owner)
                next_time(item(batch_id,ids[0]))
        else:
            conn.execute('UPDATE collection_items SET attempts=%s WHERE batch_id=%s',(cap-1,batch_id))
        owner='qa-provider-cap:will-expire'
        row=lease(batch_id,ids[0],owner)
        assert row['attempts']==cap
        now[0]+=timedelta(seconds=121)
        before=item(batch_id,ids[0])
        streak=test.one('SELECT provider_failures FROM collection_batches WHERE id=%s',(batch_id,))
        failure(batch_id,row,owner)
        assert item(batch_id,ids[0])==before
        manager.run_worker(batch_id,'qa-recovery-worker',max_steps=1)
        cleaned=item(batch_id,ids[0])
        assert cleaned['state']=='failed' and cleaned['next_stage'] is None
        assert cleaned['attempts']==cap and cleaned['lease_owner'] is None
        assert cleaned['last_error']['code']==('provider_retry_exhausted' if known_prior else 'retry_exhausted')
        assert cleaned['last_error']['cause_code']==('provider_attempt_outcome_unknown' if known_prior else 'attempt_outcome_unknown')
        assert test.one('SELECT provider_failures FROM collection_batches WHERE id=%s',(batch_id,))==streak
        receipt_id=manager.repository._event_id('collection-stage-receipt',batch_id,ids[0],'extract')
        assert test.one('SELECT count(*) AS n FROM invocations WHERE id=%s',(receipt_id,))['n']==0
        assert manager.repository.complete(batch_id,ids[0],owner,now[0],
               'complete',None,row['metadata'],{'provider':'codex_cli'},'extract',0) is False
        assert item(batch_id,ids[0])==cleaned
        assert test.one('SELECT count(*) AS n FROM invocations WHERE id=%s',(receipt_id,))['n']==0
    return batch_ids


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
            row=manager.repository.claim_next(batch_id,'probe-a','probe-a:owner',now,120,manager.stage_caps,4,manager.retry_max_attempts)
            assert row is not None
            assert manager.repository.claim_next(batch_id,'probe-b','probe-b:owner',now,120,manager.stage_caps,4,manager.retry_max_attempts) is None
            assert manager.repository.complete(batch_id,row['material_id'],'wrong:owner',now,'acquired','assess',{}, {},'acquire',0) is False
            assert manager.repository.heartbeat(batch_id,row['material_id'],'probe-a:owner',now,120) is True
            assert manager.repository.complete(batch_id,row['material_id'],'probe-a:owner',now,'acquired','assess',{'source_revision_sha256':'a'*64},{'provider':'codex_cli','usage':{'input_tokens':5}},'acquire',0) is True
            receipt=conn.execute("SELECT metadata FROM invocations WHERE provider='collection_stage' AND purpose='stage_receipt' ORDER BY created_at DESC LIMIT 1").fetchone()['metadata']
            assert receipt['authoritative_provider_usage'] is False and 'usage' not in receipt
            assert manager.summary(batch_id)['reserved_count']==2
            report.update(policy_reload=True,fetch_cap_one=True,owner_fencing=True,heartbeat=True,atomic_non_provider_receipt=True)
            provider_batches=check_provider_attempt_cap(test,settings,conn)
            report.update(provider_attempt_cap=True,alternating_success_does_not_reset_item=True,
                          exhausted_failure_updates_circuit=True,exhausted_stale_owner_fenced=True,
                          exhausted_item_stays_terminal_after_resume=True,
                          expired_last_attempt_never_invokes_next_handler=True,
                          late_stage_completion_fenced_after_cleanup=True,
                          unknown_outcome_does_not_fabricate_provider_failure=True,
                          configured_nondefault_attempt_cap=True)
    report['rollback_probe_rows']=store.one('SELECT count(*) n FROM collection_batches WHERE id=%s',(batch_id,))['n']
    assert report['rollback_probe_rows']==0
    report['provider_rollback_probe_rows']=store.one('SELECT count(*) n FROM collection_batches WHERE id=ANY(%s)',(provider_batches,))['n']
    assert report['provider_rollback_probe_rows']==0
    report['status']='passed'
    report['scope']='Actual PostgreSQL contract checks; no provider calls; all fixture rows rolled back.'
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path)
    args=parser.parse_args();report=run()
    if args.output:save_json(args.output,report)
    print(json.dumps(report))
