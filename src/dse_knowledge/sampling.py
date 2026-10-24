"""Deterministic, read-only stratified sampling from the completed registry."""
from __future__ import annotations

import hashlib
import heapq
import re
import sqlite3
import unicodedata
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


CATEGORY_WEIGHTS = {
    'llm_model_workload': 18,
    'dse_optimization': 14,
    'hardware_architecture': 13,
    'simulation_measurement': 12,
    'compiler_kernel': 11,
    'memory_interconnect': 10,
    'serving_scheduling': 10,
    'power_thermal_packaging': 7,
    'provenance_experiment': 5,
}
PAPER_TYPES = frozenset({
    'research_paper', 'scholarly_work', 'preprint', 'thesis', 'book_chapter', 'conference_abstract',
})
DOCUMENT_TYPES = frozenset({
    'technical_documentation', 'technical_document', 'technical_notebook', 'technical_report', 'technical_pdf',
})
_DOCUMENT_SCOPES = frozenset({'pinned_repository_archive_member', 'public_response_body'})
_STUB_TITLE = re.compile(
    r'^(?:404(?:\s+not\s+found)?|not\s+found|page\s+not\s+found|'
    r'access\s+denied|login|log\s+in|sign\s+in|download(?:\s+now)?|'
    r'overview|readme|documentation|table\s+of\s+contents|home|index|version)$', re.I,
)
_ERROR_CONTENT = re.compile(
    r"(?:page you're seeking could not be found|page not found|access denied|"
    r'please\s+sign\s+in\s+to\s+continue|enable\s+javascript\s+to\s+continue)', re.I,
)
_CATEGORY_TERMS = {
    'llm_model_workload': {
        'large language model': 12, 'language model': 8, 'llm': 10, 'inference': 3,
        'serving': 6, 'kv cache': 12, 'pagedattention': 16, 'attention': 5,
        'decoding': 5, 'decoder': 4, 'token': 3, 'transformer': 5,
        'speculative': 5, 'agent': 3, 'workload': 3, 'quantization': 4,
        'batching': 4, 'prefill': 5,
    },
    'dse_optimization': {
        'design space exploration': 12, 'design space': 8, 'dse': 6,
        'bayesian optimization': 12, 'pareto': 8, 'autotuning': 8,
        'auto-tuning': 8, 'search': 3, 'mapping': 4, 'multi-objective': 5,
        'accelerator': 3, 'optimization': 4, 'tuning': 4,
    },
    'hardware_architecture': {
        'architecture': 6, 'accelerator': 5, 'gpu': 4, 'chiplet': 8,
        'risc-v': 8, 'microarchitecture': 8, 'isa': 5, 'npu': 5,
        'systolic': 5, 'memory hierarchy': 5,
    },
    'simulation_measurement': {
        'simulation': 8, 'simulator': 8, 'gem5': 12, 'sst': 8,
        'ramulator': 10, 'accel-sim': 10, 'gpgpu-sim': 10,
        'benchmark': 4, 'measurement': 5, 'trace': 3, 'performance': 2,
        'computing-in-memory': 5,
    },
    'compiler_kernel': {
        'compiler': 7, 'kernel': 7, 'cuda': 6, 'triton': 10,
        'cutlass': 10, 'cute': 8, 'flashattention': 12, 'mlir': 8,
        'fusion': 6, 'tensorir': 8, 'code generation': 5, 'lowering': 4,
        'gpu': 3,
    },
    'memory_interconnect': {
        'memory': 6, 'hbm': 10, 'dram': 7, 'interconnect': 8,
        'network-on-chip': 10, 'noc': 6, 'nccl': 10, 'cxl': 6,
        'bandwidth': 4, 'cache': 3, 'ramulator': 10,
    },
    'serving_scheduling': {
        'serving': 8, 'scheduler': 7, 'scheduling': 7, 'batching': 7,
        'continuous batching': 12, 'pagedattention': 12, 'sglang': 10,
        'vllm': 10, 'hicache': 10, 'kv cache': 8, 'request': 3,
        'latency': 3, 'throughput': 3, 'prefill': 4, 'decode': 4,
    },
    'power_thermal_packaging': {
        'power': 6, 'thermal': 8, 'energy efficiency': 8, 'cooling': 6,
        'packaging': 6, 'accelergy': 12, 'hotspot': 10, '3d-ice': 10,
        'mcpat': 10, 'power-thermal': 10, 'watts': 3,
    },
    'provenance_experiment': {
        'provenance': 10, 'reproducibility': 8, 'experiment tracking': 8,
        'mlflow': 12, 'opentelemetry': 10, 'openmetrics': 8,
        'croissant': 8, 'dcat': 6, 'lineage': 6, 'experiment': 4,
        'metric': 3, 'benchmark': 2, 'artifact': 2,
    },
}
_CANONICAL_TERMS = {
    'llm_model_workload': ('pagedattention', 'vllm', 'sglang', 'flashattention'),
    'dse_optimization': ('timeloop', 'autohls', 'botorch', 'pareto'),
    'hardware_architecture': ('manticore', 'risc-v chiplet', 'mi300'),
    'simulation_measurement': ('gem5', 'ramulator', 'sst simulator', 'accel-sim'),
    'compiler_kernel': ('flashattention', 'cutlass', 'cute', 'triton', 'mlir'),
    'memory_interconnect': ('nccl', 'hbm', 'network-on-chip', 'ramulator'),
    'serving_scheduling': ('pagedattention', 'sglang', 'vllm', 'hicache'),
    'power_thermal_packaging': ('accelergy', 'hotspot', 'mcpat', '3d-ice'),
    'provenance_experiment': ('mlflow', 'opentelemetry', 'openmetrics', 'croissant'),
}
_VISION_ONLY_LLM_TERMS = (
    'visual relationship', 'semantic segmentation', 'image segmentation',
    'object detection', 'visual grounding', 'point cloud', 'image classification',
)
_STRONG_LLM_TERMS = (
    'large language model', 'language model', 'llm', 'kv cache', 'pagedattention',
    'attention', 'transformer', 'text generation', 'speculative decoding', 'serving',
)


class SamplingError(ValueError):
    pass


def _normal_title(value: str) -> str:
    ascii_text = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode('ascii')
    return ' '.join(re.sub(r'[^a-z0-9]+', ' ', ascii_text.lower()).split())


def _is_stub(row: dict) -> bool:
    title = ' '.join(str(row.get('title') or '').split())
    normalized = _normal_title(title)
    if len(normalized) < 12 or _STUB_TITLE.fullmatch(normalized):
        return True
    summary = ' '.join(str(row.get('summary') or '').split())
    if summary and _ERROR_CONTENT.search(summary):
        return True
    link = str(row.get('link') or '')
    try:
        parsed = urlsplit(link)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
            return True
    except ValueError:
        return True
    return False


def _source_class(row: dict) -> str | None:
    kind = row.get('material_type')
    if kind in PAPER_TYPES:
        return 'paper'
    if kind in DOCUMENT_TYPES and row.get('access_scope') in _DOCUMENT_SCOPES:
        return 'official_doc'
    return None


def _priority(seed: int, material_id: str) -> int:
    return int.from_bytes(hashlib.sha256(f'{seed}:{material_id}'.encode()).digest(), 'big')


def _quality(row: dict) -> tuple[int, tuple[str, ...]]:
    category = row.get('category')
    title = _normal_title(str(row.get('title') or ''))
    summary = _normal_title(str(row.get('summary') or ''))
    combined = ' ' + title + ' ' + summary + ' '
    score = 0
    matched = []
    for term, weight in _CATEGORY_TERMS[category].items():
        normalized_term = _normal_title(term)
        if f' {normalized_term} ' in combined:
            score += weight * (2 if f' {normalized_term} ' in ' ' + title + ' ' else 1)
            matched.append(term)
    for term in _CANONICAL_TERMS[category]:
        normalized_term = _normal_title(term)
        if f' {normalized_term} ' in ' ' + title + ' ':
            score += 40
            matched.append('canonical:' + term)
    if category == 'llm_model_workload':
        strong_context = any(f' {_normal_title(term)} ' in combined for term in _STRONG_LLM_TERMS)
        vision_only = any(f' {_normal_title(term)} ' in combined for term in _VISION_ONLY_LLM_TERMS)
        if vision_only and not strong_context:
            score = 0
    return score, tuple(sorted(set(matched)))


def _allocate(total: int, weights: list[int], caps: list[int], floors: list[int] | None = None) -> list[int]:
    """Allocate integer quotas proportionally, honoring capacity and optional lower bounds."""
    if len(weights) != len(caps):
        raise ValueError('allocation_shape_mismatch')
    result = list(floors or [0] * len(weights))
    if len(result) != len(weights) or any(result[i] < 0 or result[i] > caps[i] for i in range(len(weights))):
        raise ValueError('allocation_bounds_invalid')
    remaining = min(max(0, total - sum(result)), max(0, sum(caps) - sum(result)))
    while remaining:
        available = [i for i in range(len(weights)) if result[i] < caps[i]]
        if not available:
            break
        chosen = max(available, key=lambda i: (weights[i] / (result[i] + 1), -i))
        result[chosen] += 1
        remaining -= 1
    return result


def _canonical_keys(row: dict) -> list[tuple[int, str]]:
    keys = []
    doi = str(row.get('doi') or '').strip().lower()
    doi = re.sub(r'^https?://(?:dx\.)?doi\.org/', '', doi)
    if doi:
        keys.append((0, 'doi:' + doi))
    arxiv = str(row.get('arxiv') or '').strip().lower()
    arxiv = re.sub(r'^arxiv:', '', arxiv)
    arxiv = re.sub(r'v\d+$', '', arxiv)
    if arxiv:
        keys.append((1, 'arxiv:' + arxiv))
    content_hash = str(row.get('head_sha256') or '').strip().lower()
    if content_hash:
        keys.append((2, 'content:' + content_hash))
    link = str(row.get('link') or '').strip()
    if link:
        try:
            parsed = urlsplit(link)
            path = re.sub(r'(?<=/abs/)\d+(?:\.\d+)?v\d+$', lambda match: match.group(0).split('v')[0], parsed.path)
            canonical = urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path.rstrip('/'), '', ''))
        except ValueError:
            canonical = link
        keys.append((3, 'url:' + canonical))
    title = _normal_title(str(row.get('title') or ''))
    if title and row.get('material_type') in PAPER_TYPES:
        keys.append((4, 'paper-title:' + title))
    return keys


def _open_readonly(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise SamplingError('registry_unavailable')
    uri = path.resolve().as_uri() + '?mode=ro'
    try:
        connection = sqlite3.connect(uri, uri=True)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA query_only=ON')
        return connection
    except sqlite3.Error:
        raise SamplingError('registry_unavailable') from None


def _candidate_pool(connection: sqlite3.Connection, seed: int, limit: int) -> list[dict]:
    # Keep a bounded deterministic reservoir in every category/source stratum.
    pool_size = max(500, limit * 10)
    heaps: dict[tuple[str, str], list] = {}
    query = "SELECT * FROM materials WHERE decision='eligible' AND category IS NOT NULL"
    try:
        cursor = connection.execute(query)
        columns = [column[0] for column in cursor.description]
        while batch := cursor.fetchmany(1000):
            for values in batch:
                row = dict(zip(columns, values))
                category = row.get('category')
                if category not in CATEGORY_WEIGHTS or _is_stub(row):
                    continue
                source_class = _source_class(row)
                if source_class is None:
                    continue
                quality_score, quality_terms = _quality(row)
                if quality_score <= 0:
                    continue
                row['_quality_score'] = quality_score
                row['_quality_terms'] = quality_terms
                material_id = str(row.get('id') or '')
                if not material_id:
                    continue
                score = _priority(seed, material_id)
                bucket = (category, source_class)
                heap = heaps.setdefault(bucket, [])
                entry = (quality_score, -score, material_id, row)
                if len(heap) < pool_size:
                    heapq.heappush(heap, entry)
                elif entry > heap[0]:
                    heapq.heapreplace(heap, entry)
    except sqlite3.Error:
        raise SamplingError('registry_schema_invalid') from None
    return [entry[3] for heap in heaps.values() for entry in heap]


def _alias_mids(connection: sqlite3.Connection, rows: list[dict]) -> dict[str, list[tuple[int, str]]]:
    key_to_records: dict[str, list[tuple[str, int]]] = {}
    for row in rows:
        material_id = str(row.get('id') or '')
        for priority, key in _canonical_keys(row):
            key_to_records.setdefault(key, []).append((material_id, priority))
    if not key_to_records:
        return {}
    result: dict[str, list[tuple[int, str]]] = {}
    keys = list(key_to_records)
    try:
        for offset in range(0, len(keys), 900):
            batch = keys[offset:offset + 900]
            placeholders = ','.join('?' for _ in batch)
            found = connection.execute(
                f'SELECT key,mid FROM aliases WHERE key IN ({placeholders})', batch
            )
            for key, mid in found:
                for material_id, priority in key_to_records[key]:
                    result.setdefault(material_id, []).append((priority, str(mid)))
        return result
    except sqlite3.Error:
        # Canonical fields still provide a deterministic dedup fallback.
        return {}


def _fallback_dedup_key(row: dict) -> str:
    keys = _canonical_keys(row)
    return keys[0][1] if keys else 'id:' + str(row.get('id'))


def _record_quality(row: dict, canonical_mid: str) -> tuple[int, int, int, str]:
    material_id = str(row.get('id') or '')
    source_class = _source_class(row)
    scope = row.get('access_scope')
    access = 0 if scope == 'pinned_repository_archive_member' else 1
    source = str(row.get('source') or '').lower()
    direct = 0 if source == 'arxiv' else 1
    return (0 if material_id == canonical_mid else 1, access if source_class == 'official_doc' else direct,
            0 if row.get('head_kind') in ('document_head', 'abstract_head', 'pdf_opening_pages') else 1,
            material_id)


def _deduplicate(rows: list[dict], aliases: dict[str, list[tuple[int, str]]]) -> list[dict]:
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        material_id = str(row.get('id') or '')
        matches = aliases.get(material_id, [])
        canonical_mid = min(matches, default=(99, _fallback_dedup_key(row)))[1]
        row['_canonical_mid'] = canonical_mid
        grouped.setdefault(canonical_mid, []).append(row)
    unique = []
    for canonical_mid, group in grouped.items():
        unique.append(min(group, key=lambda row: _record_quality(row, canonical_mid)))
    return unique


def sample_candidates(registry_path, limit: int = 100, seed: int = 20261025) -> list[dict]:
    """Return at most ``limit`` eligible candidates without network access.

    The 100-item allocation is 60 paper-like records and 40 official documentation
    records, stratified by the nine DSE categories. Callers may request a larger
    candidate pool to replace later fetch failures.
    """
    if type(limit) is not int or limit <= 0 or limit > 10_000:
        raise SamplingError('sampling_limit_out_of_range')
    if type(seed) is not int:
        raise SamplingError('sampling_seed_invalid')
    connection = _open_readonly(Path(registry_path))
    try:
        pool = _candidate_pool(connection, seed, limit)
        aliases = _alias_mids(connection, pool)
        candidates = _deduplicate(pool, aliases)
    finally:
        connection.close()

    by_category: dict[str, list[dict]] = {category: [] for category in CATEGORY_WEIGHTS}
    by_type: dict[tuple[str, str], list[dict]] = {}
    for row in candidates:
        category = row.get('category')
        source_class = _source_class(row)
        if category in by_category and source_class:
            by_category[category].append(row)
            by_type.setdefault((category, source_class), []).append(row)
    total_available = sum(map(len, by_category.values()))
    total = min(limit, total_available)
    if total == 0:
        return []

    category_names = list(CATEGORY_WEIGHTS)
    category_caps = [len(by_category[name]) for name in category_names]
    category_weights = [CATEGORY_WEIGHTS[name] for name in category_names]
    category_counts = _allocate(total, category_weights, category_caps)
    paper_caps = [len(by_type.get((name, 'paper'), [])) for name in category_names]
    doc_caps = [len(by_type.get((name, 'official_doc'), [])) for name in category_names]
    min_docs = [max(0, category_counts[i] - paper_caps[i]) for i, name in enumerate(category_names)]
    max_docs = [min(category_counts[i], doc_caps[i]) for i, name in enumerate(category_names)]
    target_docs = int(total * 0.4 + 0.5)
    target_docs = max(sum(min_docs), min(target_docs, sum(max_docs)))
    doc_counts = _allocate(target_docs, category_weights, max_docs, floors=min_docs)
    paper_counts = [category_counts[i] - doc_counts[i] for i in range(len(category_names))]
    actual_docs, actual_papers = sum(doc_counts), sum(paper_counts)
    quotas = dict(zip(category_names, category_counts))
    output = []
    for index, category in enumerate(category_names):
        for source_class, count in (('official_doc', doc_counts[index]), ('paper', paper_counts[index])):
            bucket = sorted(by_type.get((category, source_class), []),
                            key=lambda row: (-row.get('_quality_score', 0),
                                             _priority(seed, str(row.get('id') or '')),
                                             str(row.get('id') or '')))
            for row in bucket[:count]:
                selected = dict(row)
                selected.pop('_canonical_mid', None)
                quality_score = selected.pop('_quality_score', 0)
                quality_terms = list(selected.pop('_quality_terms', ()))
                selected['sampling_metadata'] = {
                    'seed': seed,
                    'requested_limit': limit,
                    'category_quotas': dict(quotas),
                    'source_quotas': {'paper': actual_papers, 'official_doc': actual_docs},
                    'source_class': source_class,
                    'quality_score': quality_score,
                    'quality_terms': quality_terms,
                }
                output.append(selected)
    output.sort(key=lambda row: (-row['sampling_metadata']['quality_score'],
                                 _priority(seed, str(row.get('id') or '')),
                                 str(row.get('id') or '')))
    return output[:limit]
