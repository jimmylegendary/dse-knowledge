from __future__ import annotations
import argparse,json
from pathlib import Path
from .config import Settings


def main():
    parser=argparse.ArgumentParser(description='DSE knowledge self-host workbench')
    sub=parser.add_subparsers(dest='command',required=True)
    serve=sub.add_parser('serve');serve.add_argument('--host');serve.add_argument('--port',type=int)
    sample=sub.add_parser('sample');sample.add_argument('--registry',type=Path,required=True);sample.add_argument('--output',type=Path,required=True);sample.add_argument('--count',type=int,default=240)
    fetch=sub.add_parser('acquire');fetch.add_argument('--candidates',type=Path,required=True)
    sub.add_parser('index');sub.add_parser('extract');sub.add_parser('status')
    manifest=sub.add_parser('manifest');manifest.add_argument('--output',type=Path,required=True)
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
    elif args.command in ('index','extract','manifest'):
        from .pipeline import load_prepared,index_materials,extract_materials,publish_manifest
        docs=load_prepared(settings)
        if args.command=='index':print(json.dumps({'written':index_materials(settings,docs)}))
        elif args.command=='extract':print(json.dumps({'claims_written':extract_materials(settings,docs)}))
        else:publish_manifest(settings,docs,args.output);print(json.dumps({'manifest':str(args.output),'count':len(docs)}))
    else:
        from .db import Store
        print(json.dumps(Store(settings).stats(),default=str))
