import json

import pytest

from dse_knowledge.config import Settings
from dse_knowledge.quality import _role_reply, enrich_context


def prepared_document():
    text = (
        "Current revision states that the measured latency is 12 ms. "
        "A separate current passage describes the second claim."
    )
    return {
        "material": {
            "id": "material-resume",
            "title": "Synthetic current revision",
            "category": "compiler_kernel",
            "source": "synthetic",
            "material_type": "research_paper",
        },
        "text": text,
        "revision": {
            "sha256": "a" * 64,
            "scope": "public_fulltext",
            "url": "https://example.invalid/source",
        },
        "chunks": [{
            "id": "chunk-current",
            "text": text,
            "start": 0,
            "end": len(text),
        }],
    }


def claim_row(claim_id, revision_id, chunk_id, quote):
    return {
        "id": claim_id,
        "material_id": "material-resume",
        "revision_id": revision_id,
        "chunk_id": chunk_id,
        "kind": "source_assertion",
        "subject": "system",
        "predicate": "reports",
        "object": "latency",
        "summary": "The source reports a scoped result.",
        "quote": quote,
        "scope": "quoted configuration only",
    }


def empty_context():
    return {
        "schema_version": "claim-context/v1",
        "parameters": [],
        "conditions": [],
        "source_scope_note": "No additional explicit values or conditions in this quote.",
    }


class FakeChat:
    def __init__(self):
        self.calls = []
        self.last_metadata = {
            "provider": "fake_test_dependency",
            "model": "fake_context_model",
            "usage": {"input_tokens": 23, "output_tokens": 7},
        }

    def complete(self, prompt, schema):
        self.calls.append((prompt, schema))
        marker = "UNTRUSTED SOURCE DATA JSON:\n"
        payload = json.loads(prompt.split(marker, 1)[1])
        return {
            "claims": [
                {"claim_id": claim["claim_id"], "context": empty_context()}
                for claim in payload["claims"]
            ]
        }


class FakeStore:
    def __init__(self, claims, revision_sha_by_id, *, fail_on_put_call=None):
        self.claims = claims
        self.revision_sha_by_id = revision_sha_by_id
        self.annotations = {}
        self.put_attempts = []
        self.invocations = []
        self.events = []
        self.fail_on_put_call = fail_on_put_call
        self.failure_raised = False
        self.selected_claim_ids = []

    def one(self, sql, args=()):
        if "SELECT role FROM materials" in sql:
            return {"role": "core_technical"}
        raise AssertionError(f"Unexpected one() query: {sql}")

    def rows(self, sql, args=()):
        if "SELECT cl.* FROM claims cl" in sql:
            material_id, revision_sha256 = args
            if "r.sha256=%s" not in sql:
                selected = [claim for claim in self.claims
                            if claim["material_id"] == material_id]
            else:
                selected = [
                    claim for claim in self.claims
                    if claim["material_id"] == material_id
                    and self.revision_sha_by_id[claim["revision_id"]] == revision_sha256
                ]
            if "NOT EXISTS" in sql:
                selected = [
                    claim for claim in selected
                    if claim["id"] not in self.annotations
                ]
            self.selected_claim_ids.append([claim["id"] for claim in selected])
            return selected
        if "SELECT a.claim_id FROM claim_annotations" in sql:
            return [{"claim_id": claim_id} for claim_id in self.annotations]
        raise AssertionError(f"Unexpected rows() query: {sql}")

    def put_claim_context(self, claim_id, context_raw, metadata):
        self.put_attempts.append(claim_id)
        if (self.fail_on_put_call == len(self.put_attempts)
                and not self.failure_raised):
            self.failure_raised = True
            raise RuntimeError("simulated interruption after an earlier annotation committed")
        self.annotations[claim_id] = (context_raw, metadata)
        return f"annotation-{claim_id}"

    def invocation(self, provider, purpose, metadata):
        self.invocations.append((provider, purpose, metadata))

    def ingest_event(self, material_id, status, detail):
        self.events.append((material_id, status, detail))


def two_current_revision_claims():
    document = prepared_document()
    return document, [
        claim_row(
            "claim-current-1",
            "revision-current",
            "chunk-current",
            "measured latency is 12 ms",
        ),
        claim_row(
            "claim-current-2",
            "revision-current",
            "chunk-current",
            "describes the second claim",
        ),
    ]


def test_partial_context_write_resumes_cached_full_response_without_second_chat_call(tmp_path):
    document, claims = two_current_revision_claims()
    store = FakeStore(
        claims,
        {"revision-current": "a" * 64},
        fail_on_put_call=2,
    )
    chat = FakeChat()
    settings = Settings({"DSE_DATA_ROOT": str(tmp_path / "data")})

    with pytest.raises(RuntimeError, match="simulated interruption"):
        enrich_context(document, settings, store=store, chat=chat)

    assert set(store.annotations) == {"claim-current-1"}
    assert len(chat.calls) == 1

    result = enrich_context(document, settings, store=store, chat=chat)

    assert {k:v for k,v in result.items() if k!='provider_metadata'} == {
        "material_id": "material-resume",
        "status": "enriched",
        "annotations": 1,
    }
    assert result['provider_metadata']['cache_hit'] is True
    assert result['provider_metadata']['usage']=={}
    assert set(store.annotations) == {"claim-current-1", "claim-current-2"}
    assert store.put_attempts == [
        "claim-current-1",
        "claim-current-2",
        "claim-current-2",
    ]
    assert len(chat.calls) == 1


def test_context_enrichment_selects_only_claims_from_the_document_revision(tmp_path):
    document, current_claims = two_current_revision_claims()
    old_claim = claim_row(
        "claim-old-revision",
        "revision-old",
        "chunk-old",
        "older revision result is different",
    )
    store = FakeStore(
        [old_claim, *current_claims],
        {
            "revision-old": "b" * 64,
            "revision-current": "a" * 64,
        },
    )
    chat = FakeChat()
    settings = Settings({"DSE_DATA_ROOT": str(tmp_path / "data")})

    result = enrich_context(document, settings, store=store, chat=chat)

    assert result["annotations"] == 2
    assert store.selected_claim_ids == [[
        "claim-current-1", "claim-current-2",
    ]]
    assert set(store.annotations) == {"claim-current-1", "claim-current-2"}
    assert len(chat.calls) == 1


@pytest.mark.parametrize(
    "reply",
    [
        {},
        {"answers": {}},
        {"answers": {"role": {"choice": "unknown_role", "confidence": 0.8}}},
        {"answers": {"role": {"choice": "core_technical", "confidence": "high"}}},
        {"answers": {"role": {"choice": "core_technical"}}},
    ],
)
def test_role_reply_rejects_malformed_or_unscored_decisions(reply):
    with pytest.raises(ValueError):
        _role_reply(reply)


def test_role_reply_accepts_explicit_selected_probability_without_claiming_calibration():
    value, metadata = _role_reply({
        "requestedModel": "typesafe/jev-1.13",
        "returnedModel": "typesafe/jev-1.13",
        "usage": {"input_tokens": 11, "output_tokens": 2},
        "answers": {
            "role": {
                "choice": "supporting_method",
                "probabilities": {"supporting_method": 0.72},
            }
        },
    })

    assert value["role"] == "supporting_method"
    assert value["confidence"] == 0.72
    assert metadata["confidence_basis"] == "selected_probability_not_calibrated"
