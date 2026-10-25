"""Evaluate the unchanged production retriever against frozen private partial qrels.

Never exports source bodies, query vectors or model answers to public Git.
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
import math
import time
import urllib.request
from pathlib import Path

METRICS = tuple([f'known_source_hit_at_{k}' for k in (1, 5, 10)] +
                [f'known_chunk_hit_at_{k}' for k in (5, 10)] +
                ['all_expected_sources_at_5', 'reciprocal_rank'])


def score_ranking(case, items):
    if case.get('answerability') not in ('answerable', 'unsupported'):
        raise ValueError('Invalid answerability label')
    if case['answerability'] == 'unsupported':
        return None
    expected = set(case['expected_material_ids'])
    chunks = {x['chunk_id'] for x in case['expected_chunks']}
    if not expected or not chunks:
        raise ValueError('Answerable cases need independently fixed source/chunk qrels')
    positions = [i for i, x in enumerate(items, 1) if x['material_id'] in expected]
    result = {f'known_source_hit_at_{k}': int(any(x['material_id'] in expected for x in items[:k])) for k in (1, 5, 10)}
    result.update({f'known_chunk_hit_at_{k}': int(any(x['chunk_id'] in chunks for x in items[:k])) for k in (5, 10)})
    result['all_expected_sources_at_5'] = int(expected <= {x['material_id'] for x in items[:5]})
    result['reciprocal_rank'] = 1 / min(positions) if positions else 0
    return result


def validate_cases(cases):
    if not isinstance(cases, list) or any(not isinstance(c, dict) for c in cases):
        raise ValueError('Cases must be an array')
    if any(c.get('answerability') not in ('answerable', 'unsupported') for c in cases):
        raise ValueError('Invalid answerability label')
    counts = Counter(c['answerability'] for c in cases)
    if counts != {'answerable': 24, 'unsupported': 6}:
        raise ValueError('Expected exactly 24 answerable and 6 unsupported cases')
    if len({c.get('id') for c in cases}) != 30 or any(not isinstance(c.get('id'), str) or not c['id'] for c in cases):
        raise ValueError('Case IDs must be unique nonempty strings')
    for c in cases:
        if not isinstance(c.get('query'), str) or not c['query'].strip() or c.get('language') not in ('ko', 'en'):
            raise ValueError('Invalid query/language')
        if c['answerability'] == 'answerable':
            if not c.get('expected_material_ids') or not c.get('expected_chunks'):
                raise ValueError('Missing positive qrels')
            if any(e.get('material_id') not in c['expected_material_ids'] or not e.get('chunk_id') for e in c['expected_chunks']):
                raise ValueError('Chunk/material qrels mismatch')
        elif c.get('expected_behavior', {}).get('final_answer_status') != 'unknown':
            raise ValueError('Unsupported cases need an explicit unknown decision boundary')
        # Unsupported source/chunk references are boundary evidence only, never scored as answer qrels.
    positive = [c for c in cases if c['answerability'] == 'answerable']
    categories = Counter(c.get('category') for c in positive)
    if len(categories) != 9 or min(categories.values()) < 2:
        raise ValueError('Expected nine categories with at least two positives each')
    if Counter(c['language'] for c in positive) != {'ko': 12, 'en': 12}:
        raise ValueError('Expected 12 Korean and 12 English positive cases')
    if Counter(c['language'] for c in cases if c['answerability'] == 'unsupported') != {'ko': 3, 'en': 3}:
        raise ValueError('Expected three unsupported cases per language')


def metadata_items(items):
    allowed = ('chunk_id', 'material_id', 'revision_id', 'category', 'scores', 'rank')
    return [{k: item[k] for k in allowed if k in item} for item in items]


def aggregate_scores(scores):
    scores = [x for x in scores if x is not None]
    return {'denominator': len(scores), **{key: sum(x[key] for x in scores) / len(scores) if scores else None for key in METRICS}}


def latency_summary(values):
    values = sorted(values)
    return {'count': len(values), 'p50_seconds': values[math.ceil(len(values) * .5) - 1] if values else None,
            'p95_seconds': values[math.ceil(len(values) * .95) - 1] if values else None,
            'max_seconds': max(values) if values else None}


def diverse(items):
    result = []; counts = {}
    for item in items:
        mid = item['material_id']; counts[mid] = counts.get(mid, 0) + 1
        if counts[mid] <= 3:
            result.append(item)
    return result


class CaptureStore:
    def __init__(self, store):
        self.store = store; self.channels = {}; self.timings = {}

    def rows(self, sql, args=()):
        channel = ('dense' if 'ORDER BY c.embedding' in sql else
                   'lexical' if 'search_vector @@' in sql else
                   'exact' if 'm.title ILIKE' in sql else 'graph')
        start = time.monotonic(); rows = self.store.rows(sql, args)
        self.timings[channel] = time.monotonic() - start
        self.channels[channel] = rows
        return rows

    def invocation(self, *args):
        return self.store.invocation(*args)


def run(cases_path, output_path, base_url):
    from dse_knowledge.config import Settings
    from dse_knowledge.db import Store
    from dse_knowledge.pipeline import save_json
    from dse_knowledge.providers import EmbeddingClient
    from dse_knowledge.retrieval import Retriever, reciprocal_rank_fusion
    raw = cases_path.read_bytes(); loaded = json.loads(raw)
    cases = loaded['cases'] if isinstance(loaded, dict) else loaded
    validate_cases(cases)
    settings = Settings.load(); store = Store(settings); embedding = EmbeddingClient(settings)
    rows = []; http_rows = []; opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for index, case in enumerate(cases):
        capture = CaptureStore(store); retriever = Retriever(capture, embedding)
        started = time.monotonic(); error = None
        try:
            result = retriever.search(case['query'], limit=12)
            modes = {'hybrid': result['items']}
            for name, channels in [('dense', ('dense',)), ('lexical', ('lexical',)),
                                   ('dense_lexical', ('dense', 'lexical')),
                                   ('hybrid_without_graph', ('dense', 'lexical', 'exact'))]:
                modes[name] = diverse(reciprocal_rank_fusion({k: capture.channels.get(k, []) for k in channels}, 12))
        except Exception as exc:
            error = type(exc).__name__
            modes = {name: [] for name in ('hybrid', 'dense', 'lexical', 'dense_lexical', 'hybrid_without_graph')}
            result = {'channels': {}}
        elapsed = time.monotonic() - started
        row = {'case_id': case['id'], 'answerability': case['answerability'],
               'category': case['category'], 'language': case['language'], 'error_type': error,
               'latency_seconds': elapsed, 'channel_timings_seconds': capture.timings,
               'embedding_metadata': embedding.last_metadata if not error else {},
               'channels': result['channels'], 'modes': {name: metadata_items(items) for name, items in modes.items()},
               'scores': {name: score_ranking(case, items) for name, items in modes.items()}}
        rows.append(row)
        # Six real HTTP checks; this adds six separately metered embedding calls.
        if index < 24 and index % 4 == 0:
            started = time.monotonic()
            try:
                req = urllib.request.Request(base_url.rstrip('/') + '/api/search',
                    data=json.dumps({'query': case['query'], 'limit': 12}).encode(),
                    headers={'Content-Type': 'application/json'}, method='POST')
                with opener.open(req, timeout=40) as response:
                    payload = json.load(response); status = response.status
                http_rows.append({'case_id': case['id'], 'status': status,
                                  'latency_seconds': time.monotonic() - started,
                                  'known_source_score': score_ranking(case, payload['items'])})
            except Exception as exc:
                http_rows.append({'case_id': case['id'], 'error_type': type(exc).__name__,
                                  'latency_seconds': time.monotonic() - started})
        interim = {'qrels_sha256': hashlib.sha256(raw).hexdigest(), 'status': 'running', 'rows': rows, 'http_rows': http_rows}
        save_json(output_path, interim)
        print(json.dumps({'completed': len(rows), 'case_id': case['id'], 'error_type': error, 'seconds': round(elapsed, 3)}), flush=True)
    modes = ('hybrid', 'dense', 'lexical', 'dense_lexical', 'hybrid_without_graph')
    summary = {name: aggregate_scores([r['scores'][name] for r in rows]) for name in modes}
    if any(summary[name]['denominator'] != 24 for name in modes):
        raise ValueError('Positive metric denominator changed')
    breakdown = {}
    for field in ('language', 'category'):
        breakdown[field] = {value: aggregate_scores([r['scores']['hybrid'] for r in rows if r[field] == value]) for value in sorted({r[field] for r in rows})}
    report = {'qrels_sha256': hashlib.sha256(raw).hexdigest(), 'status': 'complete',
              'observations': len(rows), 'errors': sum(r['error_type'] is not None for r in rows),
              'summary': summary, 'breakdown': breakdown,
              'latency': latency_summary([r['latency_seconds'] for r in rows if not r['error_type']]),
              'http_latency': latency_summary([r['latency_seconds'] for r in http_rows if r.get('status') == 200]),
              'rows': rows, 'http_rows': http_rows,
              'limits': ['Partial qrels measure known-source/chunk hit, not exhaustive relevance precision/recall.',
                         'Failed answerable requests remain zero in the metric denominator.',
                         'Unsupported queries are excluded from source-hit denominators; retrieval is not an answerability gate.',
                         'Ablations reuse the same actual query vector and production channel candidates; full hybrid is unchanged.',
                         'Latency describes successful calls only; errors are separately counted and score zero for positive cases.',
                         'Latency is a small sequential warm-service sample, not a saturation/capacity benchmark.']}
    save_json(output_path, report)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--cases', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--base-url', default='http://127.0.0.1:8080')
    args = parser.parse_args()
    result = run(args.cases, args.output, args.base_url)
    print(json.dumps({k: result[k] for k in ('status', 'observations', 'errors', 'summary', 'latency', 'http_latency')}, ensure_ascii=False))
