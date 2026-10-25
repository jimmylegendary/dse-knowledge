"""Evaluate the unchanged production retriever against frozen private partial qrels.

Never exports source bodies, query vectors or model answers to public Git.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
import time
import urllib.request
from pathlib import Path
import re
import uuid

METRICS = tuple([f'known_source_hit_at_{k}' for k in (1, 5, 10)] +
                [f'known_chunk_hit_at_{k}' for k in (5, 10)] +
                ['all_expected_sources_at_5', 'reciprocal_rank'])
PROFILES = {
    'legacy30': {'answerable': 24, 'unsupported': 6, 'unsupported_per_language': 3},
    'paired28': {'answerable': 24, 'unsupported': 4, 'unsupported_per_language': 2},
}
RETRIEVAL_CHANNELS = frozenset({'dense', 'lexical', 'exact', 'graph'})


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


def _is_opaque_uuid(value):
    if not isinstance(value, str):
        return False
    try:
        parsed=uuid.UUID(value)
        return value.lower() in (str(parsed),parsed.hex)
    except (ValueError, AttributeError, TypeError):
        return False


def validate_manifest(manifest):
    if not isinstance(manifest, dict):
        raise ValueError('paired28 requires a metadata manifest')
    if not isinstance(manifest.get('schema_version'), str) or not manifest['schema_version'].strip():
        raise ValueError('paired28 manifest needs schema_version')
    corpus_hash = manifest.get('source_corpus_sha256')
    if not isinstance(corpus_hash, str) or not re.fullmatch(r'[a-fA-F0-9]{64}', corpus_hash):
        raise ValueError('paired28 manifest needs source_corpus_sha256')
    source_commit = manifest.get('source_commit')
    if not isinstance(source_commit, str) or not re.fullmatch(r'[a-fA-F0-9]{40,64}', source_commit):
        raise ValueError('paired28 manifest needs source_commit')


def validate_cases(cases, profile='legacy30', manifest=None):
    if profile not in PROFILES:
        raise ValueError('Unknown evaluation profile')
    if not isinstance(cases, list) or any(not isinstance(c, dict) for c in cases):
        raise ValueError('Cases must be an array')
    if profile == 'paired28' and manifest is not None:
        validate_manifest(manifest)
    if any(c.get('answerability') not in ('answerable', 'unsupported') for c in cases):
        raise ValueError('Invalid answerability label')
    counts = Counter(c['answerability'] for c in cases)
    expected_counts = PROFILES[profile]
    if counts != {'answerable': expected_counts['answerable'], 'unsupported': expected_counts['unsupported']}:
        raise ValueError(f"Expected exactly 24 answerable and {expected_counts['unsupported']} unsupported cases")
    if len({c.get('id') for c in cases}) != len(cases) or any(not isinstance(c.get('id'), str) or not c['id'] for c in cases):
        raise ValueError('Case IDs must be unique nonempty strings')
    if profile == 'paired28' and any(not _is_opaque_uuid(c.get('id')) for c in cases):
        raise ValueError('paired28 case IDs must be opaque UUIDs')
    for c in cases:
        if not isinstance(c.get('query'), str) or not c['query'].strip() or c.get('language') not in ('ko', 'en'):
            raise ValueError('Invalid query/language')
        if c['answerability'] == 'answerable':
            if not c.get('expected_material_ids') or not c.get('expected_chunks'):
                raise ValueError('Missing positive qrels')
            if any(e.get('material_id') not in c['expected_material_ids'] or not e.get('chunk_id') for e in c['expected_chunks']):
                raise ValueError('Chunk/material qrels mismatch')
        else:
            behavior=c.get('expected_behavior',{})
            explicit_unknown=isinstance(behavior,dict) and behavior.get('final_answer_status')=='unknown'
            if profile=='paired28' and isinstance(behavior,str):
                # The frozen paired gold uses explicit bilingual prose, kept
                # verbatim. This adapter does not infer/change answerability.
                explicit_unknown=bool(re.match(r'^(?:unknown으로\s*답|Answer\s+unknown[.!])',behavior.strip(),re.I))
            if not explicit_unknown:raise ValueError('Unsupported cases need an explicit unknown decision boundary')
        # Unsupported source/chunk references are boundary evidence only, never scored as answer qrels.
    positive = [c for c in cases if c['answerability'] == 'answerable']
    categories = Counter(c.get('category') for c in positive)
    if len(categories) != 9 or min(categories.values()) < 2:
        raise ValueError('Expected nine categories with at least two positives each')
    if Counter(c['language'] for c in positive) != {'ko': 12, 'en': 12}:
        raise ValueError('Expected 12 Korean and 12 English positive cases')
    unsupported_each = expected_counts['unsupported_per_language']
    if Counter(c['language'] for c in cases if c['answerability'] == 'unsupported') != {'ko': unsupported_each, 'en': unsupported_each}:
        raise ValueError(f'Expected {unsupported_each} unsupported cases per language')

    if profile == 'paired28':
        groups = defaultdict(list)
        for case in cases:
            if 'pair_id' in case:
                raise ValueError('paired28 requires the paired_id field')
            paired_id = case.get('paired_id')
            if not _is_opaque_uuid(paired_id):
                raise ValueError('paired28 paired_id values must be opaque UUIDs')
            groups[paired_id].append(case)
        if len(groups) != 14:
            raise ValueError('paired28 requires exactly 14 bilingual pairs')
        positive_pairs = 0
        for paired_id, pair in groups.items():
            if len(pair) != 2 or Counter(case['language'] for case in pair) != {'ko': 1, 'en': 1}:
                raise ValueError(f'paired_id {paired_id} must contain exactly one ko and one en case')
            if len({case['answerability'] for case in pair}) != 1:
                raise ValueError(f'paired_id {paired_id} cannot mix answerability labels')
            if pair[0]['answerability'] == 'answerable':
                qrels = [set(case['expected_material_ids']) for case in pair]
                if qrels[0] != qrels[1]:
                    raise ValueError(f'paired_id {paired_id} has mismatched paired material qrels')
                positive_pairs += 1
        if positive_pairs != 12:
            raise ValueError('paired28 requires exactly 12 positive bilingual pairs')


def metadata_items(items):
    allowed = ('chunk_id', 'material_id', 'revision_id', 'category', 'scores', 'rank',
               'result_kind', 'role')
    role_policy_fields = (
        'role', 'purpose', 'weight', 'needs_review', 'is_locator', 'evidence_authority',
        'evidence_ceiling', 'use_ceiling', 'auto_uncertain', 'policy_version',
    )
    trace_fields = (
        'channel_ranks', 'role_weight', 'query_relevance', 'graph_rank', 'graph_boost',
        'graph_topic_idf', 'graph_proof_count', 'graph_discarded_link_count', 'rank_score',
        'semantic_anchors', 'query_embedding_cache_hit', 'query_embedding_task',
        'purpose_rule', 'purpose_uncertain', 'graph_truncated', 'graph_candidate_limit',
    )
    output = []
    for item in items:
        metadata = {key: item[key] for key in allowed if key in item}
        policy = item.get('role_policy')
        if isinstance(policy, dict):
            selected_policy = {key: policy[key] for key in role_policy_fields if key in policy}
            metadata['role_policy'] = selected_policy
            if 'evidence_authority' in selected_policy:
                metadata['evidence_authority'] = selected_policy['evidence_authority']
        trace = item.get('trace')
        if isinstance(trace, dict):
            metadata['trace'] = {key: trace[key] for key in trace_fields if key in trace}
        output.append(metadata)
    return output


def production_modes(result):
    source_results = result.get('source_results', [])
    evidence_items = result.get('items', [])
    return {
        'hybrid': source_results if isinstance(source_results, list) else [],
        'hybrid_evidence': evidence_items if isinstance(evidence_items, list) else [],
    }


def retrieval_provenance(result):
    provenance = {}
    policy_version = result.get('policy_version')
    if isinstance(policy_version, str):
        provenance['policy_version'] = policy_version
    purpose_trace = result.get('purpose_trace')
    if isinstance(purpose_trace, dict):
        allowed = ('requested', 'resolved', 'rule', 'uncertain', 'version')
        provenance['purpose_trace'] = {key: purpose_trace[key] for key in allowed if key in purpose_trace}
    semantic_anchors = result.get('semantic_anchors')
    if isinstance(semantic_anchors, dict):
        anchor_fields = (
            'material_id', 'chunk_id', 'original_dense_rank', 'original_hybrid_position',
            'promoted', 'selection_basis', 'authority_changed',
        )
        provenance['semantic_anchors'] = {
            stream: {key: anchor[key] for key in anchor_fields if key in anchor}
            for stream, anchor in semantic_anchors.items() if isinstance(anchor, dict)
        }
    return provenance


def mode_definitions():
    return {
        'hybrid': ('Production mixed source_results ordering. Includes evidence and locator rows; '
                   'locator evidence_authority is zero. Known-source metrics measure source lookup, '
                   'not technical assertion authority.'),
        'hybrid_evidence': ('Production items ordering with locator rows excluded; evidence-only '
                            'result class, still subject to source-role use ceilings.'),
        'dense': 'Historical dense candidate order with legacy diversity cap; retained for comparison with the previous report.',
        'lexical': 'Legacy single-channel lexical reference.',
        'dense_lexical': 'Legacy unweighted two-channel RRF reference.',
        'hybrid_without_graph': 'Legacy unweighted dense/lexical/title RRF reference; multiple policies differ from production v2.',
    }


def aggregate_scores(scores):
    scores = [x for x in scores if x is not None]
    return {'denominator': len(scores), **{key: sum(x[key] for x in scores) / len(scores) if scores else None for key in METRICS}}


def aggregate_paired_language(rows):
    groups = defaultdict(list)
    for row in rows:
        paired_id = row.get('paired_id')
        if not _is_opaque_uuid(paired_id):
            raise ValueError('Paired language aggregation needs opaque paired_id values')
        groups[paired_id].append(row)

    positive_pairs = {}
    unsupported_pairs = 0
    for paired_id, pair in groups.items():
        if len(pair) != 2 or Counter(row.get('language') for row in pair) != {'ko': 1, 'en': 1}:
            raise ValueError(f'paired_id {paired_id} must contain one case per language')
        labels = {row.get('answerability') for row in pair}
        if labels == {'unsupported'}:
            unsupported_pairs += 1
            continue
        if labels != {'answerable'}:
            raise ValueError(f'paired_id {paired_id} mixes answerability labels')
        by_language = {row['language']: row for row in pair}
        positive_pairs[paired_id] = by_language

    modes = sorted({mode for pair in positive_pairs.values()
                    for row in pair.values() for mode in row.get('scores', {})})
    output = {
        'weighting': 'equal_per_bilingual_pair',
        'paired_denominator': len(positive_pairs),
        'unsupported_pairs_excluded': unsupported_pairs,
        'modes': {},
    }
    for mode in modes:
        ko_scores, en_scores = [], []
        deltas = {metric: [] for metric in METRICS}
        for pair in positive_pairs.values():
            ko = pair['ko'].get('scores', {}).get(mode)
            en = pair['en'].get('scores', {}).get(mode)
            if ko is None or en is None:
                raise ValueError(f'Answerable pair is missing {mode} scores')
            ko_scores.append(ko)
            en_scores.append(en)
            for metric in METRICS:
                deltas[metric].append(en[metric] - ko[metric])
        denominator = len(positive_pairs)
        output['modes'][mode] = {
            'paired_denominator': denominator,
            'unsupported_pairs_excluded': unsupported_pairs,
            'ko': aggregate_scores(ko_scores),
            'en': aggregate_scores(en_scores),
            'en_minus_ko': {
                'denominator': denominator,
                **{metric: sum(values) / len(values) if values else None
                   for metric, values in deltas.items()},
            },
        }
    return output


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
        self.store = store
        self.channels = {}
        self.timings = Counter()
        self.channel_counts = Counter()

    def rows(self, sql, args=()):
        lowered = sql.lower()
        channel = ('neighbors' if 'join lateral' in lowered or 'from chunks selected' in lowered else
                   'dense' if 'c.embedding <=>' in lowered else
                   'lexical' if 'search_vector @@' in lowered else
                   'exact' if 'm.title ilike' in lowered else
                   'graph' if 'join edges e' in lowered else 'other')
        start = time.monotonic()
        try:
            rows = self.store.rows(sql, args)
        finally:
            self.timings[channel] += time.monotonic() - start
        self.channels[channel] = rows
        self.channel_counts[channel] = len(rows)
        return rows

    def context_projection(self, chunk_ids, max_per_chunk=2):
        start = time.monotonic()
        try:
            projection = self.store.context_projection(chunk_ids, max_per_chunk=max_per_chunk)
        finally:
            self.timings['context_projection'] += time.monotonic() - start
        self.channel_counts['context_projection'] = sum(
            len(items) for items in projection.values() if isinstance(items, list)
        ) if isinstance(projection, dict) else 0
        return projection

    def invocation(self, *args):
        return self.store.invocation(*args)


def run(cases_path, output_path, base_url, profile='legacy30'):
    from dse_knowledge.config import Settings
    from dse_knowledge.db import Store
    from dse_knowledge.pipeline import save_json
    from dse_knowledge.providers import EmbeddingClient
    from dse_knowledge.retrieval import Retriever, reciprocal_rank_fusion
    raw = cases_path.read_bytes(); loaded = json.loads(raw)
    cases = loaded['cases'] if isinstance(loaded, dict) else loaded
    manifest = loaded if isinstance(loaded, dict) else None
    if profile == 'paired28' and manifest is None:
        raise ValueError('paired28 requires a metadata manifest')
    validate_cases(cases, profile=profile, manifest=manifest)
    settings = Settings.load(); store = Store(settings); embedding = EmbeddingClient(settings)
    rows = []; http_rows = []; opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    positive_index = 0
    for index, case in enumerate(cases):
        capture = CaptureStore(store); retriever = Retriever(capture, embedding)
        started = time.monotonic(); error = None
        try:
            result = retriever.search(case['query'], limit=12)
            modes = production_modes(result)
            for name, channels in [('dense', ('dense',)), ('lexical', ('lexical',)),
                                   ('dense_lexical', ('dense', 'lexical')),
                                   ('hybrid_without_graph', ('dense', 'lexical', 'exact'))]:
                modes[name] = diverse(reciprocal_rank_fusion({k: capture.channels.get(k, []) for k in channels}, 12))
        except Exception as exc:
            error = type(exc).__name__
            modes = {name: [] for name in (
                'hybrid', 'hybrid_evidence', 'dense', 'lexical', 'dense_lexical', 'hybrid_without_graph',
            )}
            result = {'channels': {}}
        elapsed = time.monotonic() - started
        provenance = retrieval_provenance(result)
        row = {'case_id': case['id'], 'answerability': case['answerability'],
               'category': case['category'], 'language': case['language'], 'error_type': error,
               'latency_seconds': elapsed, 'channel_timings_seconds': dict(capture.timings),
               'captured_channel_rows': dict(capture.channel_counts),
               'embedding_metadata': embedding.last_metadata if not error else {},
               'channels': result['channels'], **provenance,
               'modes': {name: metadata_items(items) for name, items in modes.items()},
               'scores': {name: score_ranking(case, items) for name, items in modes.items()}}
        if profile == 'paired28':
            row['paired_id'] = case['paired_id']
        rows.append(row)
        # Six real HTTP checks, spaced across positive cases; negatives stay out of metric denominators.
        if case['answerability'] == 'answerable' and positive_index % 4 == 0:
            started = time.monotonic()
            try:
                req = urllib.request.Request(base_url.rstrip('/') + '/api/search',
                    data=json.dumps({'query': case['query'], 'limit': 12}).encode(),
                    headers={'Content-Type': 'application/json'}, method='POST')
                with opener.open(req, timeout=40) as response:
                    payload = json.load(response); status = response.status
                source_results = payload.get('source_results')
                source_results = source_results if isinstance(source_results, list) else []
                http_rows.append({'case_id': case['id'], 'status': status,
                                  'latency_seconds': time.monotonic() - started,
                                  **retrieval_provenance(payload),
                                  'source_results': metadata_items(source_results),
                                  'known_source_score': score_ranking(
                                      case, source_results,
                                  )})
            except Exception as exc:
                http_rows.append({'case_id': case['id'], 'error_type': type(exc).__name__,
                                  'latency_seconds': time.monotonic() - started})
        if case['answerability'] == 'answerable':
            positive_index += 1
        interim = {'profile': profile, 'qrels_sha256': hashlib.sha256(raw).hexdigest(),
                   'status': 'running', 'rows': rows, 'http_rows': http_rows}
        if profile == 'paired28':
            interim['dataset'] = {key: manifest[key] for key in ('schema_version', 'source_corpus_sha256', 'source_commit')}
        save_json(output_path, interim)
        print(json.dumps({'completed': len(rows), 'case_id': case['id'], 'error_type': error, 'seconds': round(elapsed, 3)}), flush=True)
    modes = ('hybrid', 'hybrid_evidence', 'dense', 'lexical', 'dense_lexical', 'hybrid_without_graph')
    summary = {name: aggregate_scores([r['scores'][name] for r in rows]) for name in modes}
    if any(summary[name]['denominator'] != 24 for name in modes):
        raise ValueError('Positive metric denominator changed')
    breakdown = {}
    for field in ('language', 'category'):
        breakdown[field] = {value: aggregate_scores([r['scores']['hybrid'] for r in rows if r[field] == value]) for value in sorted({r[field] for r in rows})}
    report = {'profile': profile, 'qrels_sha256': hashlib.sha256(raw).hexdigest(), 'status': 'complete',
              'observations': len(rows), 'errors': sum(r['error_type'] is not None for r in rows),
              'summary': summary, 'breakdown': breakdown,
              'latency': latency_summary([r['latency_seconds'] for r in rows if not r['error_type']]),
              'http_latency': latency_summary([r['latency_seconds'] for r in http_rows if r.get('status') == 200]),
              'rows': rows, 'http_rows': http_rows,
              'limits': ['Partial qrels measure known-source/chunk hit, not exhaustive relevance precision/recall.',
                         'Failed answerable requests remain zero in the metric denominator.',
                         'Unsupported queries are excluded from source-hit denominators; retrieval is not an answerability gate.',
                         'hybrid source-hit metrics include zero-authority locators as source lookup results; hybrid_evidence excludes them and remains bounded by role policy.',
                         'Channel subsets reuse the actual query vector and production candidates, but use legacy unweighted RRF for historical comparison.',
                         'hybrid_without_graph is a legacy three-channel RRF reference, not a controlled graph-only ablation of v2 purpose/role/weight policies.',
                         'Latency describes successful calls only; errors are separately counted and score zero for positive cases.',
                         'Latency is a small sequential warm-service sample, not a saturation/capacity benchmark.']}
    report['mode_definitions'] = mode_definitions()
    if profile == 'paired28':
        report['dataset'] = {key: manifest[key] for key in ('schema_version', 'source_corpus_sha256', 'source_commit')}
        report['paired_language'] = aggregate_paired_language(rows)
    save_json(output_path, report)
    return report


def build_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument('--cases', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--base-url', default='http://127.0.0.1:8080')
    parser.add_argument('--profile', choices=tuple(PROFILES), default='legacy30')
    return parser


def main():
    args = build_parser().parse_args()
    result = run(args.cases, args.output, args.base_url, profile=args.profile)
    output_keys = ('profile', 'status', 'observations', 'errors', 'summary', 'latency', 'http_latency')
    print(json.dumps({k: result[k] for k in output_keys}, ensure_ascii=False))


if __name__ == '__main__':
    main()
