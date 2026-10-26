"""Bounded external relevance reranking; scores are never answerability claims."""
from __future__ import annotations

import json
import math
import re
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Sequence

from .providers import ProviderError, _NoRedirect


RERANK_PROVIDER = "deepinfra"
RERANK_MODEL = "Qwen/Qwen3-Reranker-4B"
RERANK_TIMEOUT_SECONDS = 120
RERANK_MAX_TIMEOUT_SECONDS = 600
RERANK_MAX_CANDIDATES = 40
RERANK_MAX_QUERY_CHARS = 2_000
RERANK_MAX_DOCUMENT_CHARS = 32_768
RERANK_MAX_REQUEST_BYTES = 2 * 1024 * 1024
RERANK_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_DEEPINFRA_MODELS = frozenset({"Qwen/Qwen3-Reranker-4B", "Qwen/Qwen3-Reranker-8B"})


def _setting(settings, name: str, default: str) -> str:
    value = settings.get(name, default)
    if not isinstance(value, str) or not value.strip():
        raise ProviderError("rerank_configuration_invalid")
    return value.strip()


def _timeout(settings) -> int:
    value = _setting(settings, "DSE_RERANK_TIMEOUT_SECONDS", str(RERANK_TIMEOUT_SECONDS))
    if not re.fullmatch(r"\d+", value):
        raise ProviderError("rerank_timeout_configuration_invalid")
    seconds = int(value)
    if not 1 <= seconds <= RERANK_MAX_TIMEOUT_SECONDS:
        raise ProviderError("rerank_timeout_configuration_invalid")
    return seconds


def _endpoint(provider: str, model: str, configured: str, *, allow_http: bool = False) -> str:
    if not configured and provider == "deepinfra":
        configured = "https://api.deepinfra.com/v1/inference/" + model
    try:
        parsed = urllib.parse.urlsplit(configured)
        secure_https = parsed.scheme == "https"
        opted_in_cohere_http = provider == "cohere-compatible" and allow_http and parsed.scheme == "http"
        if (not (secure_https or opted_in_cohere_http) or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment):
            raise ValueError
        if provider == "deepinfra":
            expected_path = "/v1/inference/" + model
            if parsed.hostname != "api.deepinfra.com" or parsed.path.rstrip("/") != expected_path:
                raise ValueError
        return configured
    except Exception:
        raise ProviderError("rerank_endpoint_configuration_invalid") from None


def _score(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProviderError("rerank_score_invalid")
    try:
        score = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ProviderError("rerank_score_invalid") from None
    if not math.isfinite(score):
        raise ProviderError("rerank_score_invalid")
    return score


class QwenReranker:
    """DeepInfra Qwen3 4B/8B or an explicitly configured Cohere-compatible service."""

    def __init__(self, settings, *, opener=None):
        self.settings = settings
        self.opener = opener or urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            _NoRedirect(),
            urllib.request.HTTPSHandler(context=ssl.create_default_context()),
        )
        self._metadata_local = threading.local()

    @property
    def last_metadata(self) -> dict[str, Any]:
        """Latest request receipt in this thread, avoiding cross-query metadata races."""
        return getattr(self._metadata_local, "value", {})

    @last_metadata.setter
    def last_metadata(self, value: dict[str, Any]) -> None:
        self._metadata_local.value = value

    def __repr__(self) -> str:
        provider = self.settings.get("DSE_RERANK_PROVIDER", RERANK_PROVIDER)
        model = self.settings.get("DSE_RERANK_MODEL", RERANK_MODEL)
        return f"QwenReranker(provider={provider!r}, model={model!r}, settings=<redacted>)"

    def rerank(self, query: str, documents: Sequence[str]) -> list[float]:
        started = time.monotonic()
        provider = _setting(self.settings, "DSE_RERANK_PROVIDER", RERANK_PROVIDER)
        model = _setting(self.settings, "DSE_RERANK_MODEL", RERANK_MODEL)
        self.last_metadata = {
            "provider": provider, "model": model, "http_status": None,
            "latency_seconds": None, "input_tokens": None, "inference_status": {},
            "score_semantics": "relevance_not_answerability",
        }
        try:
            return self._rerank(query, documents, provider, model)
        except ProviderError:
            raise
        except Exception:
            raise ProviderError("rerank_request_failed") from None
        finally:
            self.last_metadata["latency_seconds"] = round(time.monotonic() - started, 3)

    def _rerank(self, query: str, documents: Sequence[str], provider: str, model: str) -> list[float]:
        if provider not in ("deepinfra", "cohere-compatible"):
            raise ProviderError("rerank_provider_unsupported")
        if provider == "deepinfra" and model not in _DEEPINFRA_MODELS:
            raise ProviderError("rerank_model_unsupported")
        if (not isinstance(query, str) or not query.strip() or len(query) > RERANK_MAX_QUERY_CHARS
                or not isinstance(documents, (list, tuple)) or not documents
                or len(documents) > RERANK_MAX_CANDIDATES
                or any(not isinstance(text, str) or not text.strip() or len(text) > RERANK_MAX_DOCUMENT_CHARS
                       for text in documents)):
            raise ProviderError("rerank_input_out_of_range")
        try:
            api_key = self.settings.require("DSE_RERANK_API_KEY")
        except Exception:
            raise ProviderError("rerank_api_key_missing") from None
        if not isinstance(api_key, str) or not api_key.strip():
            raise ProviderError("rerank_api_key_missing")
        raw_allow_http = self.settings.get("DSE_RERANK_ALLOW_HTTP", "false")
        if not isinstance(raw_allow_http, str) or raw_allow_http.strip().casefold() not in ("true", "false"):
            raise ProviderError("rerank_http_opt_in_configuration_invalid")
        allow_http = raw_allow_http.strip().casefold() == "true"
        endpoint = _endpoint(
            provider, model, self.settings.get("DSE_RERANK_ENDPOINT", ""),
            allow_http=allow_http,
        )
        timeout = _timeout(self.settings)
        if provider == "deepinfra":
            payload = {"queries": [query] * len(documents), "documents": list(documents)}
        else:
            payload = {"model": model, "query": query, "documents": list(documents), "return_documents": False}
        try:
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        except (TypeError, UnicodeEncodeError):
            raise ProviderError("rerank_request_invalid") from None
        if len(body) > RERANK_MAX_REQUEST_BYTES:
            raise ProviderError("rerank_request_too_large")
        request = urllib.request.Request(
            endpoint, data=body, method="POST",
            headers={"Authorization": "Bearer " + api_key.strip(), "Content-Type": "application/json", "Accept": "application/json"},
        )
        try:
            with self.opener.open(request, timeout=timeout) as response:
                status = getattr(response, "status", None)
                self.last_metadata["http_status"] = status
                if status != 200:
                    raise ProviderError("rerank_unexpected_http_status", status)
                raw = response.read(RERANK_MAX_RESPONSE_BYTES + 1)
                if len(raw) > RERANK_MAX_RESPONSE_BYTES:
                    raise ProviderError("rerank_response_too_large", status)
        except ProviderError:
            raise
        except urllib.error.HTTPError as exc:
            self.last_metadata["http_status"] = exc.code
            raise ProviderError("rerank_http_error", exc.code) from None
        except (TimeoutError, urllib.error.URLError, OSError):
            raise ProviderError("rerank_transport_error") from None
        try:
            result = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ProviderError("rerank_response_invalid_json", self.last_metadata.get("http_status")) from None
        if not isinstance(result, dict):
            raise ProviderError("rerank_response_schema_invalid")
        if provider == "deepinfra":
            scores = self._deepinfra_result(result, len(documents))
        else:
            scores = self._cohere_result(result, len(documents))
        return scores

    def _deepinfra_result(self, result: dict[str, Any], expected_count: int) -> list[float]:
        raw_scores = result.get("scores")
        if not isinstance(raw_scores, list) or len(raw_scores) != expected_count:
            raise ProviderError("rerank_score_count_mismatch")
        scores = [_score(value) for value in raw_scores]
        input_tokens = result.get("input_tokens")
        status = result.get("inference_status")
        if type(input_tokens) is not int or input_tokens < 0 or not isinstance(status, dict):
            raise ProviderError("rerank_response_schema_invalid")
        clean_status = {}
        for key in ("runtime_ms", "tokens_input"):
            value = status.get(key)
            if value is not None:
                if type(value) is not int or value < 0:
                    raise ProviderError("rerank_inference_status_invalid")
                clean_status[key] = value
        cost = status.get("cost")
        if cost is not None:
            if isinstance(cost, bool) or not isinstance(cost, (int, float)) or not math.isfinite(float(cost)) or cost < 0:
                raise ProviderError("rerank_inference_status_invalid")
            clean_status["cost"] = float(cost)
            self.last_metadata["estimated_cost"] = float(cost)
            self.last_metadata["cost_is_estimate"] = True
        self.last_metadata["input_tokens"] = input_tokens
        self.last_metadata["inference_status"] = clean_status
        return scores

    def _cohere_result(self, result: dict[str, Any], expected_count: int) -> list[float]:
        raw_results = result.get("results")
        if not isinstance(raw_results, list) or len(raw_results) != expected_count:
            raise ProviderError("rerank_score_count_mismatch")
        indexed = {}
        for item in raw_results:
            if not isinstance(item, dict):
                raise ProviderError("rerank_response_schema_invalid")
            index = item.get("index")
            if type(index) is not int or not 0 <= index < expected_count or index in indexed:
                raise ProviderError("rerank_index_set_mismatch")
            indexed[index] = _score(item.get("relevance_score"))
        if set(indexed) != set(range(expected_count)):
            raise ProviderError("rerank_index_set_mismatch")
        return [indexed[index] for index in range(expected_count)]
