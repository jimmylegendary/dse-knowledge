"""Resumable pilot acquisition and source-grounded indexing orchestration."""
from __future__ import annotations
from collections import Counter
from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED
import hashlib
import json
import os
import re
from pathlib import Path
import secrets
import stat
import time
from .db import Store
from .sampling import CATEGORY_WEIGHTS,sample_candidates

MAX_PREPARED_CACHE_BYTES = 32 * 1024 * 1024


def safe_material_id(value):
    value=str(value)
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,159}',value):
        raise ValueError('Invalid material identifier')
    return value


def _check_private_directory(path):
    path = Path(os.path.abspath(os.fspath(path)))
    try:
        info = os.lstat(path)
        if path.resolve(strict=True) != path:
            raise ValueError
    except (OSError, ValueError):
        raise ValueError('json_output_directory_untrusted') from None
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) & 0o077):
        raise ValueError('json_output_directory_untrusted')
    return path


def _check_public_directory(path):
    path = Path(os.path.abspath(os.fspath(path)))
    try:
        info = os.lstat(path)
        if path.resolve(strict=True) != path:
            raise ValueError
    except (OSError, ValueError):
        raise ValueError('json_output_directory_untrusted') from None
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) & 0o022):
        raise ValueError('json_output_directory_untrusted')
    return path


def _ensure_output_directory(path, private):
    path = Path(os.path.abspath(os.fspath(path)))
    current = Path(path.anchor)
    try:
        for part in path.parts[1:]:
            current = current / part
            try:
                info = os.lstat(current)
            except FileNotFoundError:
                try:
                    os.mkdir(current, 0o700 if private else 0o755)
                except FileExistsError:
                    pass
                info = os.lstat(current)
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                raise ValueError
    except (OSError, ValueError):
        raise ValueError('json_output_directory_untrusted') from None
    return _check_private_directory(path) if private else _check_public_directory(path)


def _ensure_private_directory(path):
    return _ensure_output_directory(path, private=True)


def _check_output_directory_stat(info, private):
    mode = stat.S_IMODE(info.st_mode)
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or (mode & 0o077 if private else mode & 0o022)):
        raise ValueError('json_output_directory_untrusted')


def save_json(path,value, *, private=True):
    path = Path(os.path.abspath(os.fspath(path)))
    parent = _ensure_output_directory(path.parent, private=private)
    directory_flags = os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0) | getattr(os, 'O_NOFOLLOW', 0)
    directory_flags |= getattr(os, 'O_CLOEXEC', 0)
    directory_fd = os.open(parent, directory_flags)
    temp_name = None
    temp_fd = None
    replaced = False
    try:
        directory_info = os.fstat(directory_fd)
        _check_output_directory_stat(directory_info, private)
        try:
            target_info = os.stat(path.name, dir_fd=directory_fd, follow_symlinks=False)
        except FileNotFoundError:
            target_info = None
        if target_info is not None and (
                not stat.S_ISREG(target_info.st_mode) or target_info.st_uid != os.getuid()):
            raise ValueError('json_output_target_untrusted')

        temp_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0)
        temp_flags |= getattr(os, 'O_CLOEXEC', 0)
        for _attempt in range(8):
            temp_name = '.dse-json-' + secrets.token_hex(16) + '.tmp'
            try:
                temp_fd = os.open(temp_name, temp_flags, 0o600, dir_fd=directory_fd)
                break
            except FileExistsError:
                temp_name = None
        if temp_fd is None or temp_name is None:
            raise OSError('unique_json_temp_unavailable')
        os.fchmod(temp_fd, 0o600)
        with os.fdopen(temp_fd, 'w', encoding='utf-8') as output:
            temp_fd = None
            json.dump(value, output, ensure_ascii=False, indent=2, default=str)
            output.flush()
            os.fsync(output.fileno())
            if not private:
                os.fchmod(output.fileno(), 0o644)
                os.fsync(output.fileno())
        os.replace(temp_name, path.name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
        replaced = True
        os.fsync(directory_fd)
    finally:
        if temp_fd is not None:
            os.close(temp_fd)
        if temp_name is not None and not replaced:
            try:
                os.unlink(temp_name, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
        os.close(directory_fd)


def _read_cache_json(path):
    try:
        initial = os.lstat(path)
    except FileNotFoundError:
        return None, 'cache_unreadable'
    except OSError:
        return None, 'cache_unreadable'
    if (not stat.S_ISREG(initial.st_mode) or initial.st_uid != os.getuid()
            or stat.S_IMODE(initial.st_mode) & 0o077):
        return None, 'cache_file_untrusted'
    if initial.st_size > MAX_PREPARED_CACHE_BYTES:
        return None, 'cache_too_large'
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_CLOEXEC', 0)
    try:
        fd = os.open(path, flags)
        try:
            opened = os.fstat(fd)
            if ((opened.st_dev, opened.st_ino) != (initial.st_dev, initial.st_ino)
                    or not stat.S_ISREG(opened.st_mode) or opened.st_uid != os.getuid()
                    or stat.S_IMODE(opened.st_mode) & 0o077
                    or opened.st_size > MAX_PREPARED_CACHE_BYTES):
                return None, 'cache_file_untrusted'
            with os.fdopen(fd, 'rb') as stream:
                fd = -1
                raw = stream.read(MAX_PREPARED_CACHE_BYTES + 1)
        finally:
            if fd >= 0:
                os.close(fd)
        if len(raw) > MAX_PREPARED_CACHE_BYTES:
            return None, 'cache_too_large'
        document = json.loads(raw.decode('utf-8'))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        return None, 'cache_unreadable'
    if not isinstance(document, dict):
        return None, 'cache_shape_invalid'
    return document, None


def _cached_material_reason(record, document, settings):
    material = document.get('material')
    revision = document.get('revision')
    if not isinstance(material, dict) or not isinstance(revision, dict):
        return 'cache_shape_invalid'
    try:
        material_id = safe_material_id(record.get('id') or record.get('mid') or '')
    except (TypeError, ValueError):
        return 'cache_identity_mismatch'
    if material.get('id') != material_id or material.get('category') != record.get('category'):
        return 'cache_identity_mismatch'
    source_url = record.get('url') or record.get('link')
    cached_source_url = material.get('url') or material.get('link')
    if (not isinstance(source_url, str) or not source_url
            or cached_source_url != source_url or revision.get('source_url') != source_url
            or material.get('head_sha256') != record.get('head_sha256')):
        return 'cache_identity_mismatch'
    if revision.get('scope') != 'public_fulltext':
        return 'cache_scope_invalid'

    digest = revision.get('sha256')
    byte_count = revision.get('bytes')
    artifact_path = revision.get('artifact_path')
    if (not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest)
            or type(byte_count) is not int or byte_count <= 0):
        return 'cache_content_hash_mismatch'
    try:
        from .ingestion import MAX_SOURCE_BYTES, _chunk_text
        if byte_count > MAX_SOURCE_BYTES:
            return 'cache_content_hash_mismatch'
        artifact_root = Path(os.path.abspath(os.fspath(settings.artifact_root)))
        expected_path = artifact_root / digest[:2] / digest
        if not isinstance(artifact_path, str) or Path(os.path.abspath(artifact_path)) != expected_path:
            return 'cache_content_hash_mismatch'
        _check_private_directory(artifact_root)
        _check_private_directory(expected_path.parent)
        artifact_info = os.lstat(expected_path)
        if (not stat.S_ISREG(artifact_info.st_mode) or artifact_info.st_uid != os.getuid()
                or stat.S_IMODE(artifact_info.st_mode) & 0o077
                or artifact_info.st_size != byte_count or artifact_info.st_size > MAX_SOURCE_BYTES):
            return 'cache_content_hash_mismatch'
        flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_CLOEXEC', 0)
        fd = os.open(expected_path, flags)
        try:
            opened = os.fstat(fd)
            if ((opened.st_dev, opened.st_ino) != (artifact_info.st_dev, artifact_info.st_ino)
                    or not stat.S_ISREG(opened.st_mode) or opened.st_uid != os.getuid()
                    or opened.st_size != byte_count or stat.S_IMODE(opened.st_mode) & 0o077):
                return 'cache_content_hash_mismatch'
            hasher = hashlib.sha256()
            with os.fdopen(fd, 'rb') as artifact:
                fd = -1
                while chunk := artifact.read(64 * 1024):
                    hasher.update(chunk)
        finally:
            if fd >= 0:
                os.close(fd)
        if hasher.hexdigest() != digest:
            return 'cache_content_hash_mismatch'

        text = document.get('text')
        chunks = document.get('chunks')
        if not isinstance(text, str) or len(text) < 500 or not isinstance(chunks, list):
            return 'cache_chunk_span_mismatch'
        expected_chunks = _chunk_text(text, material_id, digest)
        fields = ('id', 'text', 'start', 'end', 'sha256')
        if (len(chunks) != len(expected_chunks)
                or any(not isinstance(actual, dict)
                       or any(type(actual.get(field)) is not type(expected.get(field)) for field in fields)
                       or any(actual.get(field) != expected.get(field) for field in fields)
                       for actual, expected in zip(chunks, expected_chunks))):
            return 'cache_chunk_span_mismatch'
    except (OSError, TypeError, ValueError):
        return 'cache_content_hash_mismatch'
    return None


def acquire(settings,records,target=100):
    from .ingestion import prepare_material
    root=_ensure_private_directory(settings.data_root/'pilot100')
    prepared=_ensure_private_directory(root/'prepared')
    quota=CATEGORY_WEIGHTS if target==100 else {k:max(1,round(v*target/100)) for k,v in CATEGORY_WEIGHTS.items()}
    counts=Counter();selected=[];events=[];pending={};inflight=Counter();seen=set();index=0
    def persist_state():
        save_json(root/'acquisition-state.json',{'target':target,'selected':len(selected),'categories':dict(counts),'attempts':len(events),'events':events,'material_ids':[x['material']['id'] for x in selected]})
    with ThreadPoolExecutor(max_workers=2,thread_name_prefix='dse-source') as pool:
        while len(selected)<target:
            while len(pending)<2 and index<len(records):
                record=records[index];index+=1;cat=record['category'];mid=safe_material_id(record.get('id') or record.get('mid') or '')
                if mid in seen or counts[cat]+inflight[cat]>=quota.get(cat,0):continue
                seen.add(mid);cache=prepared/(safe_material_id(mid)+'.json')
                try:
                    os.lstat(cache)
                    cache_exists=True
                except FileNotFoundError:
                    cache_exists=False
                except OSError:
                    cache_exists=True
                if cache_exists:
                    doc,read_reason=_read_cache_json(cache)
                    reason=read_reason or _cached_material_reason(record,doc,settings)
                    if reason is None:
                        selected.append(doc);counts[cat]+=1
                        continue
                    events.append({'id':mid,'category':cat,'status':'cache_rejected','reason':reason})
                    persist_state()
                    if reason=='cache_file_untrusted':continue
                pending[pool.submit(prepare_material,record,settings)]=record;inflight[cat]+=1
            if not pending:break
            done,_=wait(pending,return_when=FIRST_COMPLETED)
            for future in done:
                record=pending.pop(future);cat=record['category'];inflight[cat]-=1;mid=safe_material_id(record.get('id') or record.get('mid') or '')
                try:
                    doc=future.result()
                    if doc['revision']['scope']!='public_fulltext':raise ValueError('abstract_only_excluded_from_fulltext_pilot')
                    if len(doc['text'])<500:raise ValueError('body_too_short')
                    save_json(prepared/(safe_material_id(mid)+'.json'),doc);selected.append(doc);counts[cat]+=1
                    events.append({'id':mid,'category':cat,'status':'fulltext_acquired','chars':len(doc['text'])})
                except Exception as exc:events.append({'id':mid,'category':cat,'status':'failed','reason':getattr(exc,'reason',str(exc))[:120],'http_status':getattr(exc,'http_status',None)})
                persist_state()
                print(json.dumps({'stage':'acquire','selected':len(selected),'target':target,'attempted':len(events),'category':cat,'status':events[-1]['status']}),flush=True)
    selected=selected[:target]
    save_json(root/'selected.json',[d['material']['id'] for d in selected]);persist_state()
    return selected


def load_prepared(settings):
    root=settings.data_root/'pilot100'
    ids=json.loads((root/'selected.json').read_text())
    return [json.loads((root/'prepared'/(safe_material_id(mid)+'.json')).read_text()) for mid in ids]


def index_materials(settings,documents,store=None):
    from .providers import EmbeddingClient
    store=store or Store(settings);embedding=EmbeddingClient(settings);written=0
    for d in documents:
        mid=d['material']['id']
        if store.has_material(mid):continue
        vectors=[]
        for start in range(0,len(d['chunks']),8):
            texts=[d['material']['title']+'\n'+x['text'] for x in d['chunks'][start:start+8]]
            vectors.extend(embedding.embed(texts,task='document'))
            store.invocation('deepinfra','ingest_embedding',getattr(embedding,'last_metadata',{}))
        store.put_material(d,vectors);written+=1
        store.ingest_event(mid,'indexed',{'chunks':len(d['chunks']),'scope':d['revision']['scope'],'sha256':d['revision']['sha256']})
        print(json.dumps({'stage':'index','written':written,'id':mid,'chunks':len(d['chunks'])}),flush=True)
    return written


def _extraction_batch_size(settings):
    value = settings.get('DSE_EXTRACTION_BATCH_SIZE', '1')
    if type(value) is int:
        batch_size = value
    elif isinstance(value, str) and re.fullmatch(r'\d+', value.strip()):
        batch_size = int(value)
    else:
        raise ValueError('invalid_extraction_batch_size')
    if not 1 <= batch_size <= 5:
        raise ValueError('invalid_extraction_batch_size')
    return batch_size


def extract_materials(settings,documents,store=None):
    batch_size=_extraction_batch_size(settings)
    from .providers import ChatClient
    from .ingestion import extract_claims
    store=store or Store(settings);chat=ChatClient(settings)
    needed=[d for d in documents if store.has_material(d['material']['id']) and not store.one('SELECT id FROM claims WHERE material_id=%s LIMIT 1',(d['material']['id'],))]
    written=0
    try:
        for start in range(0,len(needed),batch_size):
            batch=needed[start:start+batch_size]
            try:
                extracted=extract_claims(batch,chat,claims_per_material=int(settings.get('DSE_EXTRACTION_CLAIMS_PER_MATERIAL','1')),max_snippets=int(settings.get('DSE_EXTRACTION_SNIPPETS','4')),max_snippet_chars=int(settings.get('DSE_EXTRACTION_SNIPPET_CHARS','900')))
                for item in extracted:
                    mid=item['material_id']
                    written+=store.put_claims(mid,item['claims'],{'provider':'codex_cli','model':settings.get('CHAT_MODEL_ID'),'epistemic_state':'source_assertion','requested_claims_per_material':int(settings.get('DSE_EXTRACTION_CLAIMS_PER_MATERIAL','1')),'requested_snippets_per_material':int(settings.get('DSE_EXTRACTION_SNIPPETS','4')),'requested_snippet_chars':int(settings.get('DSE_EXTRACTION_SNIPPET_CHARS','900')),'extraction_coverage':'bounded_snippets','independent_validations':0,'model_metadata':getattr(chat,'last_metadata',{})})
                    store.ingest_event(mid,'claims_extracted',{'count':len(item['claims']),'coverage':'bounded_snippets'})
                store.invocation('codex_cli','claim_extraction',getattr(chat,'last_metadata',{}))
                print(json.dumps({'stage':'claims','batch':start//batch_size+1,'materials':min(start+batch_size,len(needed)),'written':written}),flush=True)
            except Exception as exc:
                for doc in batch:store.ingest_event(doc['material']['id'],'extraction_failed',{'error_type':type(exc).__name__,'reason':getattr(exc,'reason','extraction_failed')[:120],'model_metadata':getattr(chat,'last_metadata',{})})
                print(json.dumps({'stage':'claims','batch':start//batch_size+1,'error_type':type(exc).__name__,'reason':getattr(exc,'reason','extraction_failed')[:120],'model_metadata':getattr(chat,'last_metadata',{})}),flush=True)
    finally:chat.close()
    return written


def publish_manifest(settings,documents,path):
    items=[]
    for d in documents:
        m=d['material'];rev=d['revision']
        items.append({'id':m['id'],'title':m['title'],'source':m['source'],'category':m['category'],'summary':m.get('summary',''),'link':m.get('link') or m.get('url'),'material_type':m.get('material_type','document'),
                      'body_sha256':rev['sha256'],'acquired_url':rev['url'],'scope':rev['scope'],'parser':rev['parser'],'characters':len(d['text']),'chunks':len(d['chunks'])})
    save_json(path,{'schema_version':'pilot-material-manifest/v1','seed':20261025,'count':len(items),'categories':dict(Counter(x['category'] for x in items)),'items':items},private=False)
