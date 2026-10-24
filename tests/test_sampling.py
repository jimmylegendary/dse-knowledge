import hashlib
import sqlite3
from collections import Counter

from dse_knowledge.sampling import sample_candidates


CATEGORIES = {
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


def make_registry(path):
    conn = sqlite3.connect(path)
    conn.execute('''CREATE TABLE materials (
        id TEXT PRIMARY KEY, source_id TEXT, source TEXT, title TEXT, category TEXT,
        summary TEXT, link TEXT, material_type TEXT, decision TEXT, decision_method TEXT,
        decision_reason TEXT, access_status TEXT, access_scope TEXT, head_kind TEXT,
        head_length INTEGER, head_sha256 TEXT, doi TEXT, arxiv TEXT,
        evidence_file TEXT, evidence_key TEXT, rank INTEGER
    )''')
    conn.execute('CREATE TABLE aliases (key TEXT PRIMARY KEY, mid TEXT NOT NULL)')
    conn.execute('''CREATE TABLE observations (
        id TEXT PRIMARY KEY, mid TEXT, source_id TEXT, evidence_file TEXT,
        evidence_key TEXT, head_sha256 TEXT, decision TEXT
    )''')
    rows = []
    for category_index, category in enumerate(CATEGORIES):
        slug = category.replace('_', '-')
        for index in range(35):
            arxiv = f'2300.{category_index:02d}{index:03d}'
            material_id = f'paper-{category}-{index}'
            rows.append((material_id, None, 'arXiv',
                         f'An Identified Research Study about {slug} {index}', category,
                         f'This paper evaluates {slug} methods and reports measured outcomes. ' * 3,
                         f'https://arxiv.org/abs/{arxiv}v1', 'research_paper', 'eligible', 'fixture',
                         '', 'public_head_observed', 'public_official_metadata_snapshot_member',
                         'abstract_head', 900, hashlib.sha256(material_id.encode()).hexdigest(), None, arxiv, 'fixture', str(index), index))
        for index in range(20):
            material_id = f'doc-{category}-{index}'
            rows.append((material_id, None, f'example/{slug}',
                         f'Official {slug} Technical Guide section {index}', category,
                         f'This official guide explains {slug}, configuration, and validation. ' * 3,
                         f'https://github.com/example/{slug}/blob/{"a" * 40}/docs/guide-{index}.md',
                         'technical_documentation', 'eligible', 'fixture', '',
                         'public_head_observed', 'pinned_repository_archive_member',
                         'document_head', 800, hashlib.sha256(material_id.encode()).hexdigest(), None, None, 'fixture', str(index), index))
    rows.extend([
        ('paper-duplicate', None, 'Semantic Scholar', 'An Identified Research Study about llm-model-workload 0',
         'llm_model_workload', 'duplicate metadata record', 'https://arxiv.org/abs/2300.99999v1',
         'scholarly_work', 'eligible', 'fixture', '', 'public_head_observed',
         'title+abstract_from_bulk_search_response', 'abstract_head', 900, 'd' * 64,
         '10.5555/duplicate', '2300.99999', 'fixture', 'duplicate', 0),
        ('paper-duplicate-copy', None, 'arXiv', 'An Identified Duplicate Paper about llm workload',
         'llm_model_workload', 'duplicate canonical item', 'https://arxiv.org/abs/2300.99999v2',
         'research_paper', 'eligible', 'fixture', '', 'public_head_observed',
         'public_official_metadata_snapshot_member', 'abstract_head', 900, 'e' * 64,
         '10.5555/duplicate', '2300.99999', 'fixture', 'duplicate-copy', 0),
        ('doc-duplicate', None, 'example/compiler-kernel', 'Official compiler guide duplicate',
         'compiler_kernel', 'duplicate document revision',
         f'https://github.com/example/compiler-kernel/blob/{"a" * 40}/docs/guide-0.md',
         'technical_documentation', 'eligible', 'fixture', '', 'public_head_observed',
         'pinned_repository_archive_member', 'document_head', 800, 'f' * 64,
         None, None, 'fixture', 'duplicate-doc', 0),
        ('stub-404', None, 'arXiv', '404 Not Found', 'compiler_kernel', 'not an identifiable material',
         'https://arxiv.org/abs/2300.77777', 'research_paper', 'eligible', 'fixture', '',
         'public_head_observed', 'public_official_metadata_snapshot_member', 'abstract_head',
         0, '0' * 64, None, '2300.77777', 'fixture', 'stub', 0),
        ('pending-paper', None, 'arXiv', 'A Pending Research Paper about DSE', 'dse_optimization',
         'not eligible', 'https://arxiv.org/abs/2300.88888', 'research_paper', 'pending', 'fixture', '',
         'public_head_observed', 'public_official_metadata_snapshot_member', 'abstract_head',
         900, '1' * 64, None, '2300.88888', 'fixture', 'pending', 0),
        ('llm-pagedattention-seed', None, 'arXiv',
         'Efficient Memory Management for Large Language Model Serving with PagedAttention',
         'llm_model_workload', 'This paper studies KV cache management and serving.',
         'https://arxiv.org/abs/2309.06180v1', 'research_paper', 'eligible', 'fixture', '',
         'public_head_observed', 'public_official_metadata_snapshot_member', 'abstract_head',
         900, '2' * 64, None, '2309.06180', 'fixture', 'pagedattention', 0),
        ('llm-cv-irrelevant', None, 'arXiv',
         'Visual Relationship Detection and Semantic Segmentation for Images',
         'llm_model_workload', 'Visual relationship detection and image segmentation methods.',
         'https://arxiv.org/abs/2300.77778v1', 'research_paper', 'eligible', 'fixture', '',
         'public_head_observed', 'public_official_metadata_snapshot_member', 'abstract_head',
         900, '3' * 64, None, '2300.77778', 'fixture', 'vision', 0),
    ])
    conn.executemany('INSERT INTO materials VALUES (' + ','.join('?' for _ in range(21)) + ')', rows)
    conn.executemany('INSERT INTO aliases VALUES (?,?)', [
        ('arxiv:2300.99999', 'paper-duplicate-copy'),
        ('doi:10.5555/duplicate', 'paper-duplicate-copy'),
        ('url:https://github.com/example/compiler-kernel/blob/' + 'a' * 40 + '/docs/guide-0.md',
         'doc-compiler-kernel-0'),
    ])
    conn.commit()
    conn.close()


def test_sampling_balances_categories_and_document_paper_mix_deterministically(tmp_path):
    path = tmp_path / 'registry.sqlite'
    make_registry(path)

    first = sample_candidates(path, limit=100, seed=20261025)
    second = sample_candidates(path, limit=100, seed=20261025)

    assert len(first) == 100
    assert [record['id'] for record in first] == [record['id'] for record in second]
    assert Counter(record['category'] for record in first) == CATEGORIES
    docs = [record for record in first if record['material_type'].startswith('technical_')]
    papers = [record for record in first if not record['material_type'].startswith('technical_')]
    assert len(docs) == 40
    assert len(papers) == 60
    assert all(record['decision'] == 'eligible' for record in first)
    assert all(record['title'] != '404 Not Found' for record in first)
    assert 'llm-cv-irrelevant' not in {record['id'] for record in first}
    assert 'llm-pagedattention-seed' in {record['id'] for record in first}
    assert all(record['sampling_metadata']['quality_score'] > 0 for record in first)
    assert all(record['sampling_metadata']['category_quotas'] == CATEGORIES for record in first)


def test_sampling_deduplicates_aliases_and_returns_only_available_records(tmp_path):
    path = tmp_path / 'registry.sqlite'
    make_registry(path)

    records = sample_candidates(path, limit=1000, seed=7)
    ids = {record['id'] for record in records}

    assert 'paper-duplicate-copy' in ids
    assert 'paper-duplicate' not in ids
    assert not ({'doc-compiler-kernel-0', 'doc-duplicate'} <= ids)
    assert 'stub-404' not in ids
    assert 'pending-paper' not in ids
    assert len(records) == len(ids)
    assert all(record['sampling_metadata']['seed'] == 7 for record in records)
