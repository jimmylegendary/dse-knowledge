from __future__ import annotations
import argparse,json
import hashlib
import os
from pathlib import Path
import secrets
import stat
from .config import Settings


def balanced_candidates(records,exclude=()):
    """Keep within-domain quality order and interleave all nine DSE domains."""
    from collections import Counter
    from fractions import Fraction
    from .sampling import CATEGORY_WEIGHTS
    from .pipeline import safe_material_id
    counts=Counter();ranked=[];seen=set(exclude)
    for position,record in enumerate(records):
        mid=safe_material_id(record.get('id') or record.get('mid') or record.get('material_id') or '')
        if mid in seen:continue
        seen.add(mid);category=record.get('category')
        if category not in CATEGORY_WEIGHTS:raise ValueError('candidate_category_invalid')
        rank=Fraction(counts[category],CATEGORY_WEIGHTS[category]);counts[category]+=1
        ranked.append((rank,position,record))
    return [record for _,_,record in sorted(ranked,key=lambda row:(row[0],row[1]))]


def _safe_collection_batch_id(value):
    from .pipeline import safe_material_id
    return safe_material_id(value)


def _ensure_private_directory(path):
    from .pipeline import _ensure_private_directory as ensure
    return ensure(path)


def _collection_batch_paths(settings,batch_id):
    safe_id=_safe_collection_batch_id(batch_id)
    root=Path(settings.data_root)/'pilot1000'/'batches'/safe_id
    return {'root':root,'input':root/'batch-input.json','receipt':root/'batch-receipt.json','progress':root/'progress.json'}


def _save_collection_progress(settings,batch_id,summary,writer):
    paths=_collection_batch_paths(settings,batch_id)
    writer(paths['progress'],summary)
    writer(Path(settings.data_root)/'pilot1000'/'progress.json',summary)


def _write_private_json_once(path,value):
    """Atomically create an owner-only JSON file without replacing a frozen file."""
    path=Path(path)
    parent=_ensure_private_directory(path.parent)
    payload=json.dumps(value,ensure_ascii=False,indent=2,default=str).encode('utf-8')
    temp=parent/('.'+path.name+'.'+secrets.token_hex(16)+'.tmp')
    flags=os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_CLOEXEC',0)
    fd=os.open(temp,flags,0o600)
    created=False
    try:
        with os.fdopen(fd,'wb') as output:
            os.fchmod(output.fileno(),0o600)
            output.write(payload);output.flush();os.fsync(output.fileno())
        try:
            os.link(temp,path,follow_symlinks=False)
            created=True
        except FileExistsError:
            created=False
        if created:
            directory_fd=os.open(parent,os.O_RDONLY|getattr(os,'O_DIRECTORY',0)|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_CLOEXEC',0))
            try:os.fsync(directory_fd)
            finally:os.close(directory_fd)
        return created
    finally:
        try:os.unlink(temp)
        except FileNotFoundError:pass


def _read_private_json(path,max_bytes=32*1024*1024):
    path=Path(path)
    try:initial=os.lstat(path)
    except OSError:raise ValueError('collection_manifest_unreadable') from None
    if (not stat.S_ISREG(initial.st_mode) or initial.st_uid!=os.getuid()
            or stat.S_IMODE(initial.st_mode)&0o077 or initial.st_size>max_bytes):
        raise ValueError('collection_manifest_untrusted')
    fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_CLOEXEC',0))
    try:
        opened=os.fstat(fd)
        if ((opened.st_dev,opened.st_ino)!=(initial.st_dev,initial.st_ino) or not stat.S_ISREG(opened.st_mode)
                or opened.st_uid!=os.getuid() or stat.S_IMODE(opened.st_mode)&0o077 or opened.st_size>max_bytes):
            raise ValueError('collection_manifest_untrusted')
        with os.fdopen(fd,'rb') as stream:
            fd=-1;payload=stream.read(max_bytes+1)
    finally:
        if fd>=0:os.close(fd)
    if len(payload)>max_bytes:raise ValueError('collection_manifest_too_large')
    try:value=json.loads(payload.decode('utf-8'))
    except (ValueError,UnicodeDecodeError,RecursionError):raise ValueError('collection_manifest_invalid') from None
    return value,payload


def _raw_claim_context(context):
    if not isinstance(context,dict):raise ValueError('annotation_context_invalid')
    parameters=context.get('parameters');conditions=context.get('conditions')
    if not isinstance(parameters,list) or not isinstance(conditions,list):raise ValueError('annotation_context_invalid')
    def evidence(item):
        value=item.get('evidence') if isinstance(item,dict) else None
        if not isinstance(value,dict) or not isinstance(value.get('chunk_id'),str) or not isinstance(value.get('quote'),str):
            raise ValueError('annotation_evidence_invalid')
        return {'chunk_id':value['chunk_id'],'quote':value['quote']}
    raw_parameters=[]
    for item in parameters:
        if not isinstance(item,dict):raise ValueError('annotation_parameter_invalid')
        raw_parameters.append({'name':item.get('name'),'value':item.get('value_raw'),'unit':item.get('unit_raw'),'evidence':evidence(item)})
    raw_conditions=[]
    for item in conditions:
        if not isinstance(item,dict):raise ValueError('annotation_condition_invalid')
        raw_conditions.append({'dimension':item.get('dimension'),'operator':item.get('operator'),
                               'value':item.get('value_raw'),'unit':item.get('unit_raw'),'evidence':evidence(item)})
    return {'schema_version':context.get('schema_version'),'parameters':raw_parameters,'conditions':raw_conditions,
            'source_scope_note':context.get('source_scope_note')}


def _latest_key(row):
    return (str(row.get('created_at') or ''),str(row.get('id') or ''))


def _claim_is_grounded(claim,material_id,revision,chunks):
    revision_id=revision.get('id')
    if (claim.get('material_id')!=material_id or claim.get('revision_id')!=revision_id
            or not isinstance(claim.get('id'),str) or not isinstance(claim.get('quote'),str)
            or not claim.get('quote')):
        return False
    digest=revision.get('sha256')
    metadata=claim.get('metadata')
    if metadata is None:metadata={}
    if not isinstance(metadata,dict):return False
    for recorded_digest in (claim.get('revision_sha256'),metadata.get('revision_sha256')):
        if recorded_digest is not None and recorded_digest!=digest:return False
    chunk=next((row for row in chunks if row.get('id')==claim.get('chunk_id')),None)
    if (chunk is None or chunk.get('material_id')!=material_id or chunk.get('revision_id')!=revision_id
            or not isinstance(chunk.get('text'),str) or not isinstance(revision.get('content'),str)):
        return False
    chunk_start=chunk.get('start',chunk.get('start_offset'))
    chunk_end=chunk.get('end',chunk.get('end_offset'))
    if (type(chunk_start) is not int or type(chunk_end) is not int or chunk_start<0 or chunk_end<=chunk_start
            or chunk_end>len(revision['content'])
            or revision['content'][chunk_start:chunk_end]!=chunk['text']):
        return False
    quote=claim['quote']
    has_start='source_start' in metadata
    has_end='source_end' in metadata
    if has_start!=has_end:return False
    if has_start:
        source_start,source_end=metadata['source_start'],metadata['source_end']
        if (type(source_start) is not int or type(source_end) is not int
                or source_end-source_start!=len(quote)):
            return False
    else:
        source_start=chunk['text'].find(quote)
        if source_start<0 or chunk['text'].find(quote,source_start+1)>=0:return False
        source_start+=chunk_start
        source_end=source_start+len(quote)
    if (source_start<chunk_start or source_end>chunk_end
            or revision['content'][source_start:source_end]!=quote
            or chunk['text'][source_start-chunk_start:source_end-chunk_start]!=quote):
        return False
    return True


def _build_pilot_seed_records(prepared_documents,snapshot,data_root):
    from .knowledge import validate_claim_context
    materials={row.get('id'):row for row in snapshot.get('materials',[]) if isinstance(row.get('id'),str)}
    revisions_by_material={}
    for revision in snapshot.get('revisions',[]):
        material_id=revision.get('material_id')
        if not isinstance(material_id,str):continue
        old=revisions_by_material.get(material_id)
        if old is None or _latest_key(revision)>_latest_key(old):revisions_by_material[material_id]=revision
    chunks_by_revision={}
    for chunk in snapshot.get('chunks',[]):
        chunks_by_revision.setdefault((chunk.get('material_id'),chunk.get('revision_id')),[]).append(chunk)
    claims_by_revision={}
    for claim in snapshot.get('claims',[]):
        claims_by_revision.setdefault((claim.get('material_id'),claim.get('revision_id')),[]).append(claim)
    annotations_by_claim={}
    for annotation in snapshot.get('annotations',[]):
        if annotation.get('version')!='claim-context/v1':continue
        if annotation.get('revision_id')!=annotation.get('claim_revision_id',annotation.get('revision_id')):continue
        annotations_by_claim.setdefault((annotation.get('claim_id'),annotation.get('revision_id')),[]).append(annotation)

    records=[];seen=set()
    for prepared in prepared_documents:
        if not isinstance(prepared,dict) or not isinstance(prepared.get('material'),dict):
            raise ValueError('pilot100_prepared_document_invalid')
        material_id=_safe_collection_batch_id(str(prepared['material'].get('id') or ''))
        if material_id in seen:continue
        seen.add(material_id)
        material=materials.get(material_id)
        if material is None:raise ValueError('pilot100_seed_material_missing')
        revision=revisions_by_material.get(material_id)
        role=material.get('role') or 'unclassified'
        current_revision_id=revision.get('id') if revision else None
        revision_sha256=revision.get('sha256') if revision else None
        current_chunks=chunks_by_revision.get((material_id,current_revision_id),[])
        current_claims=claims_by_revision.get((material_id,current_revision_id),[])
        document=None
        if revision is not None:
            document={'material':{'id':material_id},'text':revision.get('content'),
                      'revision':{'id':current_revision_id,'sha256':revision_sha256},
                      'chunks':[{'id':chunk.get('id'),'material_id':chunk.get('material_id'),
                                 'revision_id':chunk.get('revision_id'),'text':chunk.get('text'),
                                 'start':chunk.get('start',chunk.get('start_offset')),
                                 'end':chunk.get('end',chunk.get('end_offset'))} for chunk in current_chunks]}
        valid_annotation_count=0
        grounded_claim_ids=set()
        for claim in current_claims:
            if not _claim_is_grounded(claim,material_id,revision or {},current_chunks):continue
            grounded_claim_ids.add(claim.get('id'))
            key=(claim.get('id'),current_revision_id)
            candidates=annotations_by_claim.get(key,[])
            latest=max(candidates,key=_latest_key) if candidates else None
            if latest is None or document is None:continue
            try:
                normalized=validate_claim_context(_raw_claim_context(latest.get('context')),document)
            except (ValueError,KeyError,TypeError,IndexError):
                continue
            if normalized==latest.get('context'):
                valid_annotation_count+=1
        prepared_revision=(prepared.get('revision') or {}).get('sha256')
        revision_matches=bool(revision_sha256 and prepared_revision==revision_sha256)
        if role in ('source_navigation','out_of_scope'):
            state='reference_only'
        elif (role in ('core_technical','supporting_method','integration_operations') and revision_matches
              and current_claims and valid_annotation_count==len(current_claims)
              and len(grounded_claim_ids)==len(current_claims)):
            state='complete'
        else:
            state='needs_review'
        records.append({**prepared['material'],'material_id':material_id,'state':state,'metadata':{
            'prepared_path':str(Path(data_root)/'pilot100'/'prepared'/(material_id+'.json')),
            'source_revision_sha256':revision_sha256,'role':role,'indexed':True,
            'claim_count':len(current_claims),'annotation_count':valid_annotation_count,
            'extraction_version':'knowledge-quality/v2'}})
    return records


def _load_pilot_seed_snapshot(store,material_ids):
    if not material_ids:return {'materials':[],'revisions':[],'chunks':[],'claims':[],'annotations':[]}
    with store.connection() as connection:
        connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        materials=connection.execute("SELECT id,role FROM materials WHERE status='ingested' AND id=ANY(%s) ORDER BY id",(material_ids,)).fetchall()
        revisions=connection.execute('''SELECT DISTINCT ON(r.material_id) r.id,r.material_id,r.sha256,r.content,r.created_at
            FROM revisions r JOIN materials m ON m.id=r.material_id
            WHERE m.status='ingested' AND r.material_id=ANY(%s)
            ORDER BY r.material_id,r.created_at DESC,r.id DESC''',(material_ids,)).fetchall()
        revision_ids=[row['id'] for row in revisions]
        chunks=connection.execute('''SELECT id,material_id,revision_id,text,start_offset AS start,end_offset AS end
            FROM chunks WHERE material_id=ANY(%s) AND revision_id=ANY(%s)
            ORDER BY material_id,revision_id,start_offset,id''',(material_ids,revision_ids)).fetchall()
        claims=connection.execute('''SELECT id,material_id,revision_id,chunk_id,quote,metadata
            FROM claims WHERE material_id=ANY(%s) AND revision_id=ANY(%s)
            ORDER BY material_id,revision_id,id''',(material_ids,revision_ids)).fetchall()
        annotations=connection.execute('''SELECT a.id,a.claim_id,a.revision_id,a.version,a.context,a.created_at,
                cl.revision_id AS claim_revision_id
            FROM claim_annotations a JOIN claims cl ON cl.id=a.claim_id
            WHERE cl.material_id=ANY(%s) AND cl.revision_id=ANY(%s)
              AND a.revision_id=cl.revision_id AND a.version='claim-context/v1'
            ORDER BY a.claim_id,a.created_at,a.id''',(material_ids,revision_ids)).fetchall()
    return {'materials':materials,'revisions':revisions,'chunks':chunks,'claims':claims,'annotations':annotations}


def main():
    parser=argparse.ArgumentParser(description='DSE knowledge self-host workbench')
    sub=parser.add_subparsers(dest='command',required=True)
    serve=sub.add_parser('serve');serve.add_argument('--host');serve.add_argument('--port',type=int)
    sample=sub.add_parser('sample');sample.add_argument('--registry',type=Path,required=True);sample.add_argument('--output',type=Path,required=True);sample.add_argument('--count',type=int,default=240)
    fetch=sub.add_parser('acquire');fetch.add_argument('--candidates',type=Path,required=True)
    sub.add_parser('index');sub.add_parser('extract');sub.add_parser('status')
    manifest=sub.add_parser('manifest');manifest.add_argument('--output',type=Path,required=True)
    create=sub.add_parser('collection-create');create.add_argument('--id',required=True);create.add_argument('--candidates',type=Path,required=True);create.add_argument('--target',type=int,default=1000)
    run=sub.add_parser('collection-run');run.add_argument('--id',required=True);run.add_argument('--workers',type=int,default=4);run.add_argument('--max-seconds',type=int,default=86400)
    status=sub.add_parser('collection-status');status.add_argument('--id',required=True)
    resume=sub.add_parser('collection-resume');resume.add_argument('--id',required=True);resume.add_argument('--reason',required=True)
    args=parser.parse_args();settings=Settings.load()
    if args.command=='serve':
        import uvicorn
        from .app import create_app
        uvicorn.run(create_app(settings),host=args.host or settings.get('DSE_BIND_HOST','127.0.0.1'),port=args.port or int(settings.get('DSE_HTTP_PORT','8080')),workers=1,log_level='info')
    elif args.command=='sample':
        from .sampling import sample_candidates
        from .pipeline import save_json
        records=sample_candidates(args.registry,limit=args.count,seed=20261025);save_json(args.output,records);print(json.dumps({'count':len(records)}))
    elif args.command=='acquire':
        from .pipeline import acquire
        docs=acquire(settings,json.loads(args.candidates.read_text()));print(json.dumps({'fulltext_materials':len(docs)}))
    elif args.command.startswith('collection-'):
        from .collection import CollectionManager
        from .expansion import make_handlers,freeze_artifact_baseline,add_artifact_inventory_summary,DEFAULT_COLLECTION_POLICY
        from .db import Store
        from .pipeline import load_prepared
        batch_id=_safe_collection_batch_id(args.id)
        store=Store(settings)
        manager=CollectionManager(store,settings.data_root,make_handlers(settings,store),dict(DEFAULT_COLLECTION_POLICY))
        if args.command=='collection-create':
            paths=_collection_batch_paths(settings,batch_id)
            if store.one('SELECT id FROM collection_batches WHERE id=%s',(batch_id,)):
                print(json.dumps(add_artifact_inventory_summary(manager.summary(batch_id),settings),default=str));return
            _ensure_private_directory(paths['root'])
            freeze_artifact_baseline(settings)
            if paths['input'].exists() or paths['input'].is_symlink():
                records,manifest_bytes=_read_private_json(paths['input'])
                if not isinstance(records,list) or len(records)>10000 or any(not isinstance(row,dict) for row in records):
                    raise ValueError('candidate_manifest_invalid')
            else:
                candidates,_=_read_private_json(args.candidates)
                if not isinstance(candidates,list) or len(candidates)>10000 or any(not isinstance(row,dict) for row in candidates):
                    raise ValueError('candidate_manifest_invalid')
                prepared=load_prepared(settings)
                seed_ids=[_safe_collection_batch_id(document['material']['id']) for document in prepared]
                snapshot=_load_pilot_seed_snapshot(store,seed_ids)
                records=_build_pilot_seed_records(prepared,snapshot,settings.data_root)
                records+=balanced_candidates(candidates,exclude={row['material_id'] for row in records})
                created=_write_private_json_once(paths['input'],records)
                if not created:
                    records,manifest_bytes=_read_private_json(paths['input'])
                    if not isinstance(records,list) or len(records)>10000 or any(not isinstance(row,dict) for row in records):
                        raise ValueError('candidate_manifest_invalid')
                else:
                    _,manifest_bytes=_read_private_json(paths['input'])
            receipt=manager.create_batch(batch_id,records,args.target)
            store.ingest_event('batch:'+batch_id,'candidate_manifest_frozen',{'sha256':hashlib.sha256(manifest_bytes).hexdigest(),
                'candidate_count':len(records),'policy':'weighted-category-fair/v1','target_includes_pilot100':True})
            receipt=add_artifact_inventory_summary(receipt,settings)
            _write_private_json_once(paths['receipt'],receipt)
            print(json.dumps(receipt,default=str))
        elif args.command=='collection-status':
            manager=CollectionManager.from_batch(store,settings.data_root,make_handlers(settings,store),batch_id)
            print(json.dumps(add_artifact_inventory_summary(manager.summary(batch_id),settings),default=str))
        elif args.command=='collection-resume':
            manager=CollectionManager.from_batch(store,settings.data_root,make_handlers(settings,store),batch_id)
            print(json.dumps({'resumed':manager.resume_batch(batch_id,args.reason)},default=str))
        else:run_collection(settings,batch_id,args.workers,args.max_seconds)
    elif args.command in ('index','extract','manifest'):
        from .pipeline import load_prepared,index_materials,extract_materials,publish_manifest
        docs=load_prepared(settings)
        if args.command=='index':print(json.dumps({'written':index_materials(settings,docs)}))
        elif args.command=='extract':print(json.dumps({'claims_written':extract_materials(settings,docs)}))
        else:publish_manifest(settings,docs,args.output);print(json.dumps({'manifest':str(args.output),'count':len(docs)}))
    else:
        from .db import Store
        print(json.dumps(Store(settings).stats(),default=str))


def _collection_process(batch_id,worker_id):
    from .expansion import run_one_worker
    return run_one_worker(Settings.load(),batch_id,worker_id,max_steps=10)


def run_collection(settings,batch_id,workers=4,max_seconds=86400):
    """Supervise bounded application processes; durable PG leases own the work."""
    from concurrent.futures import ProcessPoolExecutor,wait,FIRST_COMPLETED
    import time
    from .collection import CollectionManager
    from .db import Store
    from .expansion import make_handlers,add_artifact_inventory_summary
    from .pipeline import save_json
    batch_id=_safe_collection_batch_id(batch_id)
    paths=_collection_batch_paths(settings,batch_id)
    if not 1<=workers<=4 or not 1<=max_seconds<=172800:raise ValueError('collection_run_limits_invalid')
    manager=CollectionManager.from_batch(Store(settings),settings.data_root,make_handlers(settings),batch_id)
    started=time.monotonic();active={};available=list(range(workers));last=None
    with ProcessPoolExecutor(max_workers=workers) as pool:
        while time.monotonic()-started<max_seconds:
            summary=add_artifact_inventory_summary(manager.summary(batch_id),settings)
            _save_collection_progress(settings,batch_id,summary,save_json)
            status=(summary['batch_state'],summary['indexed_count'],summary['completed_count'],summary['failed_count'],summary['excluded_count'],summary['needs_review_count'])
            if status!=last:print(json.dumps(summary,default=str),flush=True);last=status
            if summary['batch_state'] in ('blocked','complete','incomplete') and not active:break
            if summary['batch_state']=='running':
                while available:
                    slot=available.pop();active[pool.submit(_collection_process,batch_id,'collector-'+str(slot))]=slot
            if not active:break
            done,_=wait(active,timeout=5,return_when=FIRST_COMPLETED)
            for future in done:
                slot=active.pop(future);future.result();available.append(slot)
            if done:time.sleep(1)
    return add_artifact_inventory_summary(manager.summary(batch_id),settings)


if __name__=='__main__':main()
