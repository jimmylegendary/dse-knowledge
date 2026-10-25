#!/usr/bin/env python3
"""Bounded application jobs for enriching an existing indexed pilot, never workers for Codex development."""
from __future__ import annotations
import argparse
from concurrent.futures import ProcessPoolExecutor,wait,FIRST_COMPLETED
import json
import re
from dse_knowledge.config import Settings
from dse_knowledge.db import Store
from dse_knowledge.pipeline import _read_cache_json,save_json,safe_material_id


def enrich_one(path):
    from dse_knowledge.quality import enrich_context
    document,reason=_read_cache_json(path)
    if reason:return {'status':'failed','error':reason}
    try:
        result=enrich_context(document,Settings.load());result.pop('provider_metadata',None)
        return result
    except Exception as exc:
        return {'material_id':document['material']['id'],'status':'failed','error_type':type(exc).__name__,
                'reason':getattr(exc,'reason','context_failed')}


def run(corpus,workers=4):
    if not re.fullmatch(r'pilot[0-9]{2,6}',corpus) or not 1<=workers<=4:raise ValueError('invalid_run_settings')
    settings=Settings.load();store=Store(settings);root=settings.data_root/corpus
    selected=json.loads((root/'selected.json').read_text());pending=[]
    for mid in selected:
        mid=safe_material_id(mid)
        row=store.one('SELECT role FROM materials WHERE id=%s',(mid,))
        if row and row['role'] in ('core_technical','supporting_method','integration_operations'):
            pending.append(root/'prepared'/(mid+'.json'))
    results=[];streak=0;blocked=False;active={};index=0
    report_path=settings.data_root/'qa/quality-v2'/('enrichment-'+corpus+'.json')
    with ProcessPoolExecutor(max_workers=workers) as pool:
        while active or (index<len(pending) and not blocked):
            while len(active)<workers and index<len(pending) and not blocked:
                path=pending[index];index+=1;active[pool.submit(enrich_one,path)]=path
            if not active:break
            done,_=wait(active,return_when=FIRST_COMPLETED)
            for future in done:
                active.pop(future);result=future.result();results.append(result)
                if result['status']=='failed' and 'provider_failed' in result.get('reason',''):streak+=1
                elif result['status'] in ('enriched','already_enriched'):streak=0
                if streak>=3:blocked=True
                report={'corpus':corpus,'eligible_materials':len(pending),'processed':len(results),
                        'blocked':blocked,'consecutive_provider_failures':streak,'results':results}
                save_json(report_path,report)
                print(json.dumps({k:v for k,v in report.items() if k!='results'}|{'last':result}),flush=True)
    return report_path


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--corpus',default='pilot100');parser.add_argument('--workers',type=int,default=4)
    args=parser.parse_args();run(args.corpus,args.workers)
