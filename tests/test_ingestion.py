import hashlib
import inspect
import json
from pathlib import Path

import pytest

from dse_knowledge.config import Settings
from dse_knowledge import ingestion
from dse_knowledge.ingestion import IngestionError, extract_claims, prepare_material


REVISION = '91843b71d90737e0a9b86f7d9df213cff5a3526f'


def make_settings(tmp_path):
    return Settings({'DSE_DATA_ROOT': str(tmp_path / 'data'),
                     'DSE_ARTIFACT_ROOT': str(tmp_path / 'artifacts')})


def record(url='https://github.com/NVIDIA/cutlass/blob/' + REVISION + '/README.md'):
    return {
        'id': 'mat-cutlass-1',
        'title': 'CUTLASS CuTe Programming Guide',
        'category': 'compiler_kernel',
        'source': 'NVIDIA/cutlass',
        'link': url,
        'summary': 'A source document about GPU tensor programming and memory layouts.',
        'material_type': 'technical_documentation',
        'access_scope': 'pinned_repository_archive_member',
    }


def test_prepare_converts_pinned_github_markdown_and_writes_content_addressed_artifact(monkeypatch, tmp_path):
    body = ('# CUTLASS CuTe\n\n' + ('CuTe tensors express GPU layouts, tiled computation, and memory movement. ' * 20)).encode()
    seen = []

    def fake_fetch(url, settings):
        seen.append(url)
        return body, 'text/plain', url

    monkeypatch.setattr(ingestion, '_resolve_public_host', lambda host, port: ['93.184.216.34'])
    monkeypatch.setattr(ingestion, '_fetch_url', fake_fetch)
    settings = make_settings(tmp_path)

    first = prepare_material(record(), settings)
    second = prepare_material(record(), settings)

    expected_url = f'https://raw.githubusercontent.com/NVIDIA/cutlass/{REVISION}/README.md'
    assert seen == [expected_url, expected_url]
    assert first['material']['id'] == 'mat-cutlass-1'
    assert first['revision']['url'] == expected_url
    assert first['revision']['scope'] == 'public_fulltext'
    assert first['revision']['source_scope'] == 'pinned_repository_archive_member'
    digest = hashlib.sha256(body).hexdigest()
    assert first['revision']['sha256'] == digest
    artifact = Path(first['revision']['artifact_path'])
    assert artifact == settings.artifact_root / digest[:2] / digest
    assert artifact.read_bytes() == body
    assert first['text'] == second['text']
    assert first['revision']['artifact_path'] == second['revision']['artifact_path']
    assert first['chunks'] == second['chunks']
    assert first['chunks'] and all(chunk['end'] - chunk['start'] == len(chunk['text'])
                                   for chunk in first['chunks'])


def test_prepare_strips_active_html_and_preserves_plain_text(monkeypatch, tmp_path):
    text = 'Power telemetry captures GPU board draw and cooling response over each experiment window. ' * 12
    html = f'<html><head><script>steal()</script><style>bad</style></head><body><nav>menu</nav><main><h1>Power measurement</h1><p>{text}</p></main></body></html>'.encode()
    monkeypatch.setattr(ingestion, '_resolve_public_host', lambda host, port: ['93.184.216.34'])
    monkeypatch.setattr(ingestion, '_fetch_url', lambda url, settings: (html, 'text/html', url))

    prepared = prepare_material(record('https://docs.nvidia.com/power/guide'), make_settings(tmp_path))

    assert 'Power measurement' in prepared['text']
    assert 'steal()' not in prepared['text']
    assert 'menu' not in prepared['text']
    assert prepared['revision']['parser'] == 'html-text-v1'


def test_prepare_rejects_private_resolution_before_fetch(monkeypatch, tmp_path):
    called = []

    monkeypatch.setattr(ingestion.socket, 'getaddrinfo',
                        lambda host, port, type: [(0, 0, 0, '', ('127.0.0.1', port))])
    monkeypatch.setattr(ingestion, '_fetch_url', lambda *args: called.append(args))

    with pytest.raises(IngestionError, match='non_public_source_address'):
        prepare_material(record('https://docs.nvidia.com/power/guide'), make_settings(tmp_path))

    assert called == []


def test_prepare_rejects_non_allowlisted_host_without_fetch(monkeypatch, tmp_path):
    called = []
    monkeypatch.setattr(ingestion, '_fetch_url', lambda *args: called.append(args))

    with pytest.raises(IngestionError, match='source_host_not_allowed'):
        prepare_material(record('https://attacker.invalid/file.md'), make_settings(tmp_path))

    assert called == []


def test_arxiv_pdf_url_preserves_the_captured_version():
    candidate = {'source': 'arXiv', 'arxiv': '2309.06180'}

    assert ingestion._arxiv_pdf_url(candidate, 'https://arxiv.org/abs/2309.06180v3') == \
        'https://arxiv.org/pdf/2309.06180v3.pdf'


def test_arxiv_catalog_version_wins_when_source_url_is_unversioned():
    candidate = {'source': 'arXiv', 'arxiv': '2309.06180v2'}

    assert ingestion._arxiv_pdf_url(candidate, 'https://arxiv.org/abs/2309.06180') == \
        'https://arxiv.org/pdf/2309.06180v2.pdf'


@pytest.mark.parametrize(('catalog_id', 'source_url', 'reason'), [
    ('2309.06180v2', 'https://arxiv.org/abs/2309.06180v1', 'arxiv_version_conflict'),
    ('2309.06180v2', 'https://arxiv.org/abs/2401.00001', 'arxiv_identifier_conflict'),
])
def test_arxiv_rejects_conflicting_catalog_and_url_identity(catalog_id, source_url, reason):
    with pytest.raises(IngestionError, match=reason):
        ingestion._arxiv_pdf_url({'source': 'arXiv', 'arxiv': catalog_id}, source_url)


def test_fetcher_revalidates_redirect_destination_before_connect(monkeypatch):
    connections = []

    class RedirectResponse:
        status = 302

        def getheader(self, name):
            return 'https://attacker.invalid/redirected' if name == 'Location' else None

        def close(self):
            pass

    class FakeConnection:
        def __init__(self, host, port, address, **kwargs):
            connections.append((host, port, address))

        def request(self, *_args, **_kwargs):
            pass

        def getresponse(self):
            return RedirectResponse()

        def close(self):
            pass

    monkeypatch.setattr(ingestion, '_PinnedHTTPSConnection', FakeConnection)
    monkeypatch.setattr(ingestion, '_resolve_public_host', lambda host, port: ['93.184.216.34'])

    with pytest.raises(IngestionError, match='source_host_not_allowed'):
        ingestion._fetch_url('https://docs.nvidia.com/power/guide', Settings({}))

    assert connections == [('docs.nvidia.com', 443, '93.184.216.34')]


def test_fetcher_connects_to_the_validated_ip_and_keeps_original_host(monkeypatch):
    connections = []

    class SuccessResponse:
        status = 200

        def getheader(self, name):
            return {'Content-Type': 'text/plain; charset=utf-8', 'Content-Length': '23'}.get(name)

        def read(self, size):
            return b'bounded public response'

        def close(self):
            pass

    class FakeConnection:
        def __init__(self, host, port, address, **kwargs):
            connections.append((host, port, address))

        def request(self, *_args, **_kwargs):
            pass

        def getresponse(self):
            return SuccessResponse()

        def close(self):
            pass

    monkeypatch.setattr(ingestion, '_PinnedHTTPSConnection', FakeConnection)
    monkeypatch.setattr(ingestion, '_resolve_public_host', lambda host, port: ['93.184.216.34'])

    raw, content_type, final_url = ingestion._fetch_url(
        'https://docs.nvidia.com/power/guide', Settings({}))

    assert raw == b'bounded public response'
    assert content_type == 'text/plain'
    assert final_url == 'https://docs.nvidia.com/power/guide'
    assert connections == [('docs.nvidia.com', 443, '93.184.216.34')]


@pytest.mark.parametrize(('status', 'content_range'), [
    (206, 'bytes 0-19/100'),
    (206, None),
    (200, 'bytes 0-19/100'),
])
def test_fetcher_rejects_unsolicited_partial_content(monkeypatch, status, content_range):
    class PartialResponse:
        def getheader(self, name):
            return {'Content-Type': 'text/plain', 'Content-Range': content_range}.get(name)

        def read(self, size):
            return b'partial representation'

        def close(self):
            pass

    PartialResponse.status = status

    class FakeConnection:
        def __init__(self, *args, **kwargs):
            pass

        def request(self, *_args, **_kwargs):
            pass

        def getresponse(self):
            return PartialResponse()

        def close(self):
            pass

    monkeypatch.setattr(ingestion, '_PinnedHTTPSConnection', FakeConnection)
    monkeypatch.setattr(ingestion, '_resolve_public_host', lambda host, port: ['93.184.216.34'])

    with pytest.raises(IngestionError, match='source_partial_response'):
        ingestion._fetch_url('https://docs.nvidia.com/power/guide', Settings({}))


def test_prepare_never_labels_partial_response_as_public_fulltext(monkeypatch, tmp_path):
    class PartialResponse:
        status = 206

        def getheader(self, name):
            return {'Content-Type': 'text/plain', 'Content-Range': 'bytes 0-1199/5000'}.get(name)

        def read(self, size):
            return (b'partial text about GPU kernel scheduling and memory movement. ' * 24)[:size]

        def close(self):
            pass

    class FakeConnection:
        def __init__(self, *args, **kwargs):
            pass

        def request(self, *_args, **_kwargs):
            pass

        def getresponse(self):
            return PartialResponse()

        def close(self):
            pass

    monkeypatch.setattr(ingestion, '_PinnedHTTPSConnection', FakeConnection)
    monkeypatch.setattr(ingestion, '_resolve_public_host', lambda host, port: ['93.184.216.34'])
    settings = make_settings(tmp_path)

    with pytest.raises(IngestionError, match='source_partial_response'):
        prepare_material(record('https://docs.nvidia.com/power/guide'), settings)

    assert not settings.artifact_root.exists()


class FakeChat:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def complete(self, prompt, schema):
        self.calls.append((prompt, schema))
        return self.result


def prepared_for_claims(text='Paged KV cache reuses prefix blocks to reduce request latency. The scheduler batches compatible requests for better throughput.'):
    return {
        'material': {'id': 'mat-claims-1', 'title': 'KV cache scheduling'},
        'text': text,
        'revision': {'sha256': 'a' * 64, 'url': 'https://arxiv.org/pdf/2309.06180.pdf',
                     'scope': 'public_fulltext'},
        'chunks': [{'id': 'chunk-1', 'text': text, 'start': 0, 'end': len(text),
                    'sha256': 'b' * 64}],
    }


def claim(chunk_id='chunk-1', quote='reuses prefix blocks to reduce request latency'):
    return {'chunk_id': chunk_id, 'quote': quote, 'kind': 'mechanism',
            'subject': 'Paged KV cache', 'predicate': 'reuses', 'object': 'prefix blocks',
            'summary': 'Prefix reuse lowers request latency.', 'scope': 'LLM inference'}


def assert_context_prompt_contract(prompt):
    for phrase in (
        'complete string value or complete numeric literal',
        'never take a substring from an identifier or model/part name',
        'never compute or infer a numeric value',
        'copied verbatim from the original source',
        'unique across the entire source revision and its cited chunk',
        'omit only that optional context entry',
        'broaden the claim or its scope',
    ):
        assert phrase in prompt.lower()


def test_extract_claims_exposes_structured_opt_in_without_changing_default():
    assert inspect.signature(extract_claims).parameters['structured'].default is False


def test_extract_claims_structured_mode_validates_and_returns_normalized_context():
    text = 'KV cache on V100 has request latency 6.4 ms per request.'
    doc = prepared_for_claims(text)
    quote = 'has request latency 6.4 ms per request'
    context = {
        'schema_version': 'claim-context/v1',
        'parameters': [{
            'name': 'request latency', 'value': 6.4, 'unit': 'ms',
            'evidence': {'chunk_id': 'chunk-1', 'quote': quote},
        }],
        'conditions': [{
            'dimension': 'hardware.from', 'operator': 'eq', 'value': 'V100', 'unit': None,
            'evidence': {'chunk_id': 'chunk-1', 'quote': 'on V100'},
        }],
        'source_scope_note': 'The quoted configuration only.',
    }
    extracted_claim = {
        **claim(quote=quote), 'subject': 'KV cache', 'predicate': 'has',
        'object': 'request latency 6.4 ms per request',
        'summary': 'A V100 run reports 6.4 ms request latency.', 'context': context,
    }
    chat = FakeChat({'documents': [{'material_id': 'mat-claims-1', 'claims': [extracted_claim]}]})

    result = extract_claims([doc], chat, structured=True)

    normalized = result[0]['claims'][0]['context']
    assert result[0]['claims'][0]['context_raw'] == context
    assert result[0]['material_id'] == 'mat-claims-1'
    assert normalized['parameters'][0]['value_raw'] == 6.4
    assert normalized['parameters'][0]['normalized'] == {
        'value': 0.0064, 'unit': 's', 'status': 'normalized',
    }
    assert normalized['conditions'][0]['value_raw'] == 'V100'
    assert_context_prompt_contract(chat.calls[0][0])
    claim_schema = chat.calls[0][1]['properties']['documents']['items']['properties']['claims']['items']
    assert 'context' in claim_schema['required']
    provider_context_schema = claim_schema['properties']['context']
    assert provider_context_schema == ingestion._provider_context_schema()
    emitted_json_schema = json.dumps(provider_context_schema)
    assert '"oneOf"' not in emitted_json_schema
    assert '"allOf"' not in emitted_json_schema
    assert '"if"' not in emitted_json_schema
    assert '"then"' not in emitted_json_schema
    assert '"const"' not in emitted_json_schema


def test_extract_claims_structured_mode_rejects_missing_context():
    doc = prepared_for_claims()
    chat = FakeChat({'documents': [{'material_id': 'mat-claims-1', 'claims': [claim()]}]})

    with pytest.raises(IngestionError, match='claim_context_missing'):
        extract_claims([doc], chat, structured=True)


def test_extract_claims_provider_documents_cardinality_matches_each_batch():
    class BatchChat:
        def __init__(self):
            self.calls = []

        def complete(self, prompt, schema):
            marker = 'UNTRUSTED SOURCE DATA JSON:' + chr(10)
            prompt_documents = json.loads(prompt.split(marker, 1)[1])
            self.calls.append((prompt_documents, json.loads(json.dumps(schema))))
            return {'documents': [
                {'material_id': item['material_id'], 'claims': []}
                for item in prompt_documents
            ]}

    documents = []
    for index in range(6):
        document = prepared_for_claims()
        document['material']['id'] = f'mat-batch-{index}'
        document['chunks'][0]['id'] = f'chunk-batch-{index}'
        documents.append(document)
    chat = BatchChat()

    result = extract_claims(documents, chat, claims_per_material=1)

    assert len(result) == 6
    assert [len(prompt_documents) for prompt_documents, _ in chat.calls] == [5, 1]
    for prompt_documents, schema in chat.calls:
        cardinality = len(prompt_documents)
        documents_schema = schema['properties']['documents']
        assert documents_schema['minItems'] == cardinality
        assert documents_schema['maxItems'] == cardinality


def test_extract_claim_contexts_backfills_existing_claim_ids_without_rewriting_claims():
    text = 'Paged KV cache on V100 reports request latency of 6.4 ms.'
    doc = prepared_for_claims(text)
    quote = 'request latency of 6.4 ms'
    existing = [{
        'id': 'claim-existing-1', 'material_id': 'mat-claims-1', 'revision_id': 'rev-1',
        'chunk_id': 'chunk-1', 'kind': 'measurement', 'subject': 'KV cache',
        'predicate': 'reports', 'object': 'request latency', 'summary': 'Existing summary',
        'quote': quote, 'scope': 'source_assertion',
    }]
    context = {
        'schema_version': 'claim-context/v1',
        'parameters': [{
            'name': 'request latency', 'value': 6.4, 'unit': 'ms',
            'evidence': {'chunk_id': 'chunk-1', 'quote': quote},
        }],
        'conditions': [{
            'dimension': 'hardware.from', 'operator': 'eq', 'value': 'V100', 'unit': None,
            'evidence': {'chunk_id': 'chunk-1', 'quote': 'on V100'},
        }],
        'source_scope_note': 'The quoted run only.',
    }
    chat = FakeChat({'claims': [{'claim_id': 'claim-existing-1', 'context': context}]})

    result = ingestion.extract_claim_contexts(doc, existing, chat)

    assert result[0]['claim_id'] == 'claim-existing-1'
    assert result[0]['context_raw'] == context
    assert result[0]['context']['parameters'][0]['normalized']['value'] == 0.0064
    assert result[0]['context']['conditions'][0]['value_raw'] == 'V100'
    assert existing[0]['summary'] == 'Existing summary'
    assert_context_prompt_contract(chat.calls[0][0])
    assert chat.calls[0][1]['additionalProperties'] is False


def test_extract_claim_contexts_empty_input_does_not_call_provider():
    chat = FakeChat(None)

    assert ingestion.extract_claim_contexts(prepared_for_claims(), [], chat) == []
    assert chat.calls == []


def test_extract_claims_validates_exact_quote_and_adds_offsets():
    doc = prepared_for_claims()
    chat = FakeChat({'documents': [{'material_id': 'mat-claims-1', 'claims': [claim()]}]})

    result = extract_claims([doc], chat)

    text = doc['text']
    start = text.index(claim()['quote'])
    assert result == [{'material_id': 'mat-claims-1', 'claims': [
        {**claim(), 'source_start': start, 'source_end': start + len(claim()['quote'])}
    ]}]
    prompt, schema = chat.calls[0]
    assert 'untrusted source data' in prompt.lower()
    assert schema['additionalProperties'] is False
    assert schema['properties']['documents']['items']['properties']['claims']['maxItems'] == 3


@pytest.mark.parametrize('bad_claim', [
    claim(chunk_id='not-in-this-document'),
    claim(quote='a quote that is not present in the source'),
    claim(quote='short'),
])
def test_extract_claims_rejects_bad_ids_and_unverifiable_quotes(bad_claim):
    with pytest.raises(IngestionError):
        extract_claims([prepared_for_claims()], FakeChat({'documents': [
            {'material_id': 'mat-claims-1', 'claims': [bad_claim]},
        ]}))


def test_extract_claims_rejects_ambiguous_quote_occurrences():
    text = 'A stable source sentence says prefix blocks reduce latency. Another sentence says prefix blocks reduce latency too.'
    exact = 'prefix blocks reduce latency'
    with pytest.raises(IngestionError, match='ambiguous_claim_quote'):
        extract_claims([prepared_for_claims(text)], FakeChat({'documents': [
            {'material_id': 'mat-claims-1', 'claims': [claim(quote=exact)]},
        ]}))


def test_extract_claims_rejects_quotes_outside_the_bounded_prompt_snippet():
    quote = 'evidence hidden beyond the provided snippet'
    text = ('x' * 1600) + quote + (' y' * 50)

    with pytest.raises(IngestionError, match='ambiguous_claim_quote'):
        extract_claims([prepared_for_claims(text)], FakeChat({'documents': [
            {'material_id': 'mat-claims-1', 'claims': [claim(quote=quote)]},
        ]}))


def test_extract_claims_rejects_more_than_three_claims():
    with pytest.raises(IngestionError, match='too_many_claims'):
        extract_claims([prepared_for_claims()], FakeChat({'documents': [
            {'material_id': 'mat-claims-1', 'claims': [claim()] * 4},
        ]}))


def test_json_escaped_snippets_fit_budget_without_rejecting_real_document():
    text=('GPU "layout" \\ stage\n' * 2000)
    doc={'material':{'id':'mat-budget'},'text':text,
         'chunks':ingestion._chunk_text(text,'mat-budget','r')}
    snippets,_=ingestion._document_snippets(doc)
    import json
    assert len(snippets)==8
    assert len(json.dumps(snippets,ensure_ascii=False,separators=(',',':'))) <= ingestion.MAX_PROMPT_CHARS_PER_DOCUMENT
    assert all(s['text'] and text[s['start']:].startswith(s['text']) for s in snippets)


def test_requested_claim_resolution_is_bounded():
    doc=prepared_for_claims()
    chat=FakeChat({'documents':[{'material_id':'mat-claims-1','claims':[claim(),claim()]}]})
    with pytest.raises(IngestionError,match='too_many_claims'):
        extract_claims([doc],chat,claims_per_material=1)


def test_thin_extraction_preserves_uniform_source_positions():
    text=('distinct GPU pipeline source. ' * 2000)
    doc={'material':{'id':'mat-thin'},'text':text,'chunks':ingestion._chunk_text(text,'mat-thin','r')}
    snippets,_=ingestion._document_snippets(doc,max_snippets=4,max_chars=900)
    assert len(snippets)==4 and all(0<len(x['text'])<=900 for x in snippets)
    assert snippets[0]['start']==0 and snippets[-1]['start']==doc['chunks'][-1]['start']
