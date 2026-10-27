import importlib
import hashlib
import json
import os
import stat
import subprocess
import threading
from pathlib import Path

import pytest

from dse_knowledge.config import Settings


MODEL = "typesafe/jev-1.13"
CHOICES = (
    "direct_support_candidate", "partial_support", "condition_mismatch",
    "conflicting_evidence", "no_support", "uncertain",
)


def probabilities(**overrides):
    result = {
        "direct_support_candidate": 0.70,
        "partial_support": 0.10,
        "condition_mismatch": 0.05,
        "conflicting_evidence": 0.05,
        "no_support": 0.05,
        "uncertain": 0.05,
    }
    result.update(overrides)
    return result


def reply(*, choice="direct_support_candidate", probs=None, requested=MODEL,
          returned=MODEL + "-20260917", request_id="req-1", extra=None):
    value = {
        "profile": "general", "project": "dse-knowledge", "advisoryOnly": True,
        "requestedModel": requested,
        "returnedModel": returned,
        "requestId": request_id,
        "latencyMs": 842,
        "usage": {"inputTokens": 27, "costUsd": 0.000023268},
        "answers": {"evidence_assessment": {
            "type": "choice", "choice": choice,
            "probabilities": probabilities() if probs is None else probs,
            "confidence": 0.99,
        }},
    }
    if extra:
        value.update(extra)
    return value


def settings(tmp_path, **overrides):
    values = {"DSE_DATA_ROOT": str(tmp_path / "private-data")}
    values.update(overrides)
    return Settings(values)


class ControlledPopen:
    def __init__(self, argv, *, raw, hang=False, returncode=0):
        self.argv=list(argv);self.returncode=None;self.killed=False;self.wait_calls=0
        self._stop=threading.Event();self._done=threading.Event();self._exit_code=returncode
        read_fd,self._write_fd=os.pipe()
        self.stdout=os.fdopen(read_fd,'rb',buffering=0)
        self._raw=raw;self._hang=hang
        self._thread=threading.Thread(target=self._write_output,daemon=True)
        self._thread.start()

    def _write_output(self):
        try:
            if self._hang:
                self._stop.wait()
            else:
                for start in range(0,len(self._raw),4096):
                    if self._stop.is_set():break
                    view=memoryview(self._raw[start:start+4096])
                    while view and not self._stop.is_set():
                        try:view=view[os.write(self._write_fd,view):]
                        except (BrokenPipeError,OSError):return
        finally:
            try:os.close(self._write_fd)
            except OSError:pass
            self.returncode=-9 if self.killed else self._exit_code
            self._done.set()

    def poll(self):
        return self.returncode if self._done.is_set() else None

    def wait(self,timeout=None):
        self.wait_calls+=1
        if not self._done.wait(timeout):
            raise subprocess.TimeoutExpired(self.argv,timeout)
        return self.returncode

    def kill(self):
        self.killed=True;self._stop.set()
        try:self.stdout.close()
        except OSError:pass


def install_fake_cli(monkeypatch, response=None, *, raw=None, hang=False, returncode=0):
    module = importlib.import_module("dse_knowledge.jev_advice")
    calls = []

    def popen(argv, **kwargs):
        path = Path(argv[argv.index("--file") + 1])
        request=json.loads(path.read_text())
        output=raw
        if output is None:
            output=json.dumps(response,ensure_ascii=False,separators=(",",":"),allow_nan=True).encode('utf-8')
        process=ControlledPopen(argv,raw=output,hang=hang,returncode=returncode)
        calls.append({"argv":list(argv),"kwargs":kwargs,"request":request,"process":process})
        return process

    def forbidden_run(*args,**kwargs):
        raise AssertionError("Jev adapter tests must never invoke a real provider CLI")

    monkeypatch.setattr(module.subprocess,"Popen",popen)
    monkeypatch.setattr(module.subprocess,"run",forbidden_run)
    return module, calls


def evidence(chunk_id="chunk-a", revision_id="revision-a", text="KV cache capacity is 80 GB.", **extra):
    return {
        "chunk_id": chunk_id, "material_id": "material-a", "revision_id": revision_id,
        "start_offset": 0, "end_offset": len(text), "text": text,
        "title": "GPU memory note", "role": "core_technical", "scope": "fulltext",
        "category": "memory_interconnect", **extra,
    }


def test_advisor_builds_bounded_unicode_projection_without_truncating_query_or_rules(tmp_path, monkeypatch):
    module, calls = install_fake_cli(monkeypatch, reply())
    advisor = module.JevEvidenceAdvisor(settings(tmp_path))
    query = "GPU memory 조건 확인 — " + "Q" * 300
    rules = [{"id": "capacity", "rule": "must cover 80 GB", "unit": "GB"}]
    source_text = ("한글 조건 " * 2000) + "tail-source-sentinel"

    result = advisor.assess(query, [evidence(text=source_text)], kind="hardware", required_rules=rules)

    request = calls[0]["request"]
    state = request["state"]
    item = state["evidence"][0]
    assert state["query"] == query
    assert state["kind"] == "hardware"
    assert state["required_rules"] == rules
    assert item["text"] != source_text
    assert item["text_truncated"] is True
    assert item["source_text_bytes"] == len(source_text.encode("utf-8"))
    assert item["excerpt_text_bytes"] == len(item["text"].encode("utf-8"))
    assert result["projection"]["state_bytes"] <= 24_000
    assert result["projection"]["request_bytes"] <= 30_000
    state_wire = json.dumps(state, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
    request_wire = json.dumps(request, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
    assert result["projection"]["state_bytes"] == len(state_wire)
    assert result["projection"]["request_bytes"] == len(request_wire)
    assert result["metadata"]["request_state_sha256"] == hashlib.sha256(state_wire).hexdigest()
    assert result["metadata"]["request_sha256"] == hashlib.sha256(request_wire).hexdigest()
    assert result["projection"]["truncated_evidence"] == 1
    assert result["projection"]["excerpt_only"] is True
    assert result["evidence_ids"] == ["chunk-a"]
    assert result["support_score"] == pytest.approx(0.70)
    assert result["status"] == "assessed"
    assert set(result["projection"]) == {
        "total_evidence", "selected_evidence", "omitted_evidence", "truncated_evidence",
        "state_bytes", "request_bytes", "excerpt_only", "items",
    }
    assert result["projection"]["items"] == [{
        "chunk_id": "chunk-a", "revision_id": "revision-a",
        "source_text_bytes": len(source_text.encode("utf-8")),
        "excerpt_text_bytes": len(item["text"].encode("utf-8")), "truncated": True,
    }]
    assert result["metadata"]["usage"] == {"input_tokens":27,"cost_usd":0.000023268}
    assert result["metadata"]["latency_ms"] == 842
    assert len(calls) == 1


def test_projection_caps_evidence_and_reports_omitted_sources_without_reordering(tmp_path, monkeypatch):
    module, calls = install_fake_cli(monkeypatch, reply())
    advisor = module.JevEvidenceAdvisor(settings(tmp_path))
    sources = [evidence(f"chunk-{index}", f"revision-{index}", f"Evidence text {index}.") for index in range(14)]

    result = advisor.assess("Which evidence applies?", sources)

    assert result["projection"]["total_evidence"] == 14
    assert result["projection"]["selected_evidence"] == 12
    assert result["projection"]["omitted_evidence"] == 2
    assert result["evidence_ids"] == [f"chunk-{index}" for index in range(12)]
    assert [item["chunk_id"] for item in calls[0]["request"]["state"]["evidence"]] == result["evidence_ids"]


def test_long_excerpt_selects_a_query_condition_window_away_from_the_prefix(tmp_path, monkeypatch):
    module, calls = install_fake_cli(monkeypatch, reply())
    advisor = module.JevEvidenceAdvisor(settings(tmp_path))
    filler = "This unrelated background paragraph describes other GPU observations. " * 900
    source_text = filler + "\n\nH100 batch size 1 migration requires 80 GB capacity.\n\n" + filler

    result = advisor.assess(
        "H100 batch size 1 migration capacity", [evidence(text=source_text)],
        required_rules=[{"id":"r1","rule":"80 GB capacity for batch size 1"}],
    )

    projected = calls[0]["request"]["state"]["evidence"][0]
    assert projected["text_truncated"] is True
    assert projected["excerpt_start_byte"] > 0
    assert "H100 batch size 1 migration" in projected["text"]
    assert projected["excerpt_end_byte"] <= len(source_text.encode("utf-8"))
    assert result["projection"]["truncated_evidence"] == 1


def test_cache_identity_covers_full_query_rules_revision_and_source_tail(tmp_path, monkeypatch):
    module, calls = install_fake_cli(monkeypatch, reply())
    advisor = module.JevEvidenceAdvisor(settings(tmp_path))
    original = evidence(text="A" * 9000)
    rules = [{"id": "r1", "rule": "match source condition"}]

    first = advisor.assess("query one", [original], required_rules=rules)
    repeated = advisor.assess("query one", [original], required_rules=rules)
    changed_tail = dict(original, text=("A" * 8999) + "B")
    tail_result = advisor.assess("query one", [changed_tail], required_rules=rules)
    revision_result = advisor.assess("query one", [dict(original, revision_id="revision-new")], required_rules=rules)
    query_result = advisor.assess("query two", [original], required_rules=rules)
    rule_result = advisor.assess("query one", [original], required_rules=[{"id": "r1", "rule": "different"}])

    assert first["metadata"]["cache_hit"] is False and first["metadata"]["provider_calls"] == 1
    assert repeated["metadata"]["cache_hit"] is True and repeated["metadata"]["provider_calls"] == 0
    assert tail_result["metadata"]["input_sha256"] != first["metadata"]["input_sha256"]
    assert revision_result["metadata"]["input_sha256"] != first["metadata"]["input_sha256"]
    assert query_result["metadata"]["input_sha256"] != first["metadata"]["input_sha256"]
    assert rule_result["metadata"]["input_sha256"] != first["metadata"]["input_sha256"]
    assert len(calls) == 5
    cache_dir = tmp_path / "private-data" / "jev-advice-cache"
    assert stat.S_IMODE(cache_dir.stat().st_mode) == 0o700
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in cache_dir.glob("*.json"))


def test_explicit_condition_mismatch_and_missing_condition_are_separate_choices(tmp_path, monkeypatch):
    module, calls = install_fake_cli(monkeypatch, reply(
        choice="condition_mismatch",
        probs=probabilities(condition_mismatch=0.8, direct_support_candidate=0.05,
                            partial_support=0.05, conflicting_evidence=0.03,
                            no_support=0.04, uncertain=0.03),
    ))
    result = module.JevEvidenceAdvisor(settings(tmp_path)).assess(
        "Check H100 capacity at batch 1", [evidence(text="A100 capacity is 80 GB.")],
    )

    question = calls[0]["request"]["questions"]["evidence_assessment"]
    assert "condition_mismatch" in question["criteria"]
    assert "partial_support" in question["criteria"]
    assert "explicitly states a different" in question["criteria"]["condition_mismatch"]
    assert "not mentioned" in question["criteria"]["partial_support"]
    assert result["choice"] == "condition_mismatch"
    assert result["support_score"] == pytest.approx(0.05)


@pytest.mark.parametrize("bad_reply", [
    reply(returned="other-model"),
    reply(returned=MODEL + "-preview"),
    reply(returned=MODEL + "-20261399"),
    reply(returned="typesafe/jev-1.14"),
    reply(choice="made_up_choice"),
    reply(probs={"direct_support_candidate": 1.0}),
    reply(probs=probabilities(direct_support_candidate=float("nan"))),
    reply(probs=probabilities(direct_support_candidate=0.80)),
    reply(probs=probabilities(direct_support_candidate=10**400)),
    reply(extra={"usage": {"inputTokens": 3, "costUsd": 10**400}}),
])
def test_malformed_model_or_probability_is_unavailable_with_null_score(tmp_path, monkeypatch, bad_reply):
    module, calls = install_fake_cli(monkeypatch, bad_reply)

    result = module.JevEvidenceAdvisor(settings(tmp_path)).assess("query", [evidence()])

    assert result["status"] == "unavailable"
    assert result["support_score"] is None
    assert result["choice"] is None
    assert result["metadata"]["provider_calls"] == 1
    assert result["metadata"]["error_code"] in {
        "model_mismatch", "choice_invalid", "probabilities_invalid", "usage_invalid",
    }
    assert len(calls) == 1


def test_timeout_and_missing_cli_are_nonfatal_safe_provider_failures(tmp_path, monkeypatch):
    module,calls=install_fake_cli(monkeypatch,reply(),hang=True)
    timed_out = module.JevEvidenceAdvisor(settings(
        tmp_path / "timeout", DSE_JEV_TIMEOUT_SECONDS="1",
    )).assess("query", [evidence()])

    def missing(argv, **kwargs):
        raise FileNotFoundError("private-cli-path")

    monkeypatch.setattr(module.subprocess,"Popen",missing)
    missing_cli = module.JevEvidenceAdvisor(settings(
        tmp_path / "missing", DSE_DECISION_MODEL_CLI="/private/path/decision-model",
    )).assess("query", [evidence()])

    assert timed_out["status"] == "unavailable" and timed_out["support_score"] is None
    assert timed_out["metadata"]["error_code"] == "timeout"
    assert missing_cli["status"] == "unavailable" and missing_cli["support_score"] is None
    assert missing_cli["metadata"]["error_code"] == "cli_unavailable"
    assert timed_out["metadata"]["provider_calls"] == 1
    assert missing_cli["metadata"]["provider_calls"] == 0
    assert len(calls) == 1
    assert calls[0]["process"].killed is True
    serialized = json.dumps([timed_out, missing_cli], ensure_ascii=False)
    assert "private-stderr" not in serialized and "private-cli-path" not in serialized
    assert "/private/path/decision-model" not in serialized
    assert calls[0]["kwargs"]["stdin"] == module.subprocess.DEVNULL
    assert calls[0]["kwargs"]["stderr"] == module.subprocess.DEVNULL
    assert calls[0]["kwargs"]["stdout"] == module.subprocess.PIPE
    assert calls[0]["kwargs"]["shell"] is False


def test_returned_model_revision_is_a_real_calendar_date_and_large_numbers_fail_closed():
    module=importlib.import_module("dse_knowledge.jev_advice")
    invalid_date=reply(returned=MODEL+"-20261399")
    with pytest.raises(ValueError,match="model_mismatch"):
        module._validated_response(invalid_date)

    huge_probability=reply(probs=probabilities(direct_support_candidate=10**400))
    with pytest.raises(ValueError,match="probabilities_invalid"):
        module._validated_response(huge_probability)

    huge_usage=reply(extra={"usage":{"inputTokens":4,"costUsd":10**400}})
    with pytest.raises(ValueError,match="usage_invalid"):
        module._validated_response(huge_usage)


def test_cli_capture_stops_at_max_response_plus_one_and_kills_provider(tmp_path, monkeypatch):
    module, calls = install_fake_cli(monkeypatch, raw=b"x" * 20_000)
    monkeypatch.setattr(module,"MAX_RESPONSE_BYTES",64)
    read_sizes=[]
    original_read=module.os.read
    def bounded_read(descriptor,size):
        read_sizes.append(size)
        return original_read(descriptor,size)
    monkeypatch.setattr(module.os,"read",bounded_read)

    result=module.JevEvidenceAdvisor(settings(tmp_path)).assess("query",[evidence()])

    assert result["status"]=="unavailable"
    assert result["support_score"] is None
    assert result["metadata"]["error_code"]=="response_too_large"
    assert result["metadata"]["provider_calls"]==1
    assert calls[0]["process"].killed is True
    assert max(read_sizes)<=65
    assert calls[0]["process"].stdout.closed is True


def test_stdout_oserror_is_normalized_after_kill_reap_and_close(tmp_path, monkeypatch):
    module,calls=install_fake_cli(monkeypatch,reply())
    def broken_read(*args,**kwargs):
        raise OSError("private stdout read failure")
    monkeypatch.setattr(module.os,"read",broken_read)

    result=module.JevEvidenceAdvisor(settings(tmp_path)).assess("query",[evidence()])

    assert result["status"]=="unavailable"
    assert result["support_score"] is None
    assert result["metadata"]["error_code"]=="provider_failed"
    process=calls[0]["process"]
    assert process.killed is True
    assert process.wait_calls>=1
    assert process.stdout.closed is True


def test_over_budget_rules_are_not_truncated_or_sent(tmp_path, monkeypatch):
    module, calls = install_fake_cli(monkeypatch, reply())
    rules = [{"id": "huge", "rule": "MUST PRESERVE " + ("x" * 27_000)}]

    result = module.JevEvidenceAdvisor(settings(tmp_path)).assess("query", [evidence()], required_rules=rules)

    assert result["status"] == "skipped_over_budget"
    assert result["support_score"] is None
    assert result["choice"] is None
    assert result["metadata"]["error_code"] == "jev_state_over_budget"
    assert result["metadata"]["provider_calls"] == 0
    assert calls == []


def test_advice_envelope_has_allowlisted_metadata_and_unassessed_score_is_null(tmp_path, monkeypatch):
    module, _ = install_fake_cli(monkeypatch, reply())
    result = module.JevEvidenceAdvisor(settings(tmp_path)).assess("query", [evidence()])

    assert set(result["metadata"]) == {
        "provider", "model_selected", "model_reported", "request_id", "latency_ms",
        "cache_hit", "usage", "error_code", "request_state_sha256", "request_sha256",
        "input_sha256", "provider_calls",
    }
    assert result["status"] == "assessed"
    assert result["support_score"] is not None
    assert result["consumed_by_generator"] is False
    disabled = module.empty_advice("disabled")
    assert disabled["status"] == "disabled"
    assert disabled["support_score"] is None
    assert disabled["choice"] is None
    assert disabled["consumed_by_generator"] is False
