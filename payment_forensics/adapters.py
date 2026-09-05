"""Adapters that connect the hybrid engine to existing LLM and MCP clients.

The repository owns the validation boundary. Applications own transport and
credentials, and provide callables backed by their already-approved clients.
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable, Mapping

import httpx

from .controller import SearchResultState, ToolResult
from .engine import SearchExecutor, SearchRequest


class JsonProposalModel:
    """Adapt a JSON-producing LLM client to the engine's proposal contract."""

    def __init__(self, propose_json: Callable[[Mapping[str, Any]], str | Mapping[str, Any]], render_text: Callable[[str, Mapping[str, Any], tuple[int, ...]], str]) -> None:
        self._propose_json = propose_json
        self._render_text = render_text

    def propose(self, context: Mapping[str, Any]) -> Mapping[str, Any]:
        raw = self._propose_json(context)
        proposal = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(proposal, Mapping):
            raise TypeError("LLM proposal must decode to a JSON object")
        return proposal

    def render(self, mode: str, context: Mapping[str, Any], fact_ids: tuple[int, ...]) -> str:
        output = self._render_text(mode, context, fact_ids)
        if not isinstance(output, str) or not output.strip():
            raise ValueError("LLM renderer returned empty output")
        return output


class OpenAIResponsesModel:
    """OpenAI Responses API adapter with strict JSON proposal output.

    The API key is read from `OPENAI_API_KEY`. The model is configurable so
    deployment policy, model access, and data-retention choices stay external.
    """

    PROPOSAL_SCHEMA = {
        "type": "object",
        "properties": {
            "searches": {"type": "array", "items": {"type": "object", "properties": {
                "source": {"type": "string"}, "query": {"type": "string"},
                "identifiers": {"type": "array", "items": {"type": "string"}},
                "start_date": {"type": ["string", "null"]}, "end_date": {"type": ["string", "null"]},
                "novelty": {"type": "string"},
            }, "required": ["source", "query", "identifiers", "start_date", "end_date", "novelty"], "additionalProperties": False}},
            "hypotheses": {"type": "array", "items": {"type": "object", "properties": {
                "label": {"type": "string"}, "supporting": {"type": "array", "items": {"type": "integer"}},
                "contradicting": {"type": "array", "items": {"type": "integer"}},
            }, "required": ["label", "supporting", "contradicting"], "additionalProperties": False}},
            "retries": {"type": "array", "items": {"type": "object", "properties": {
                "failed_id": {"type": "integer"}, "later_id": {"type": "integer"}, "relation": {"type": "string"},
            }, "required": ["failed_id", "later_id", "relation"], "additionalProperties": False}},
            "component_lifecycle": {"type": "array", "items": {"type": "object", "properties": {
                "component": {"type": "string"}, "status": {"type": "string"},
                "amount": {"type": ["string", "null"]}, "currency": {"type": ["string", "null"]},
                "timestamp": {"type": ["string", "null"]},
                "fact_ids": {"type": "array", "items": {"type": "integer"}},
            }, "required": ["component", "status", "amount", "currency", "timestamp", "fact_ids"], "additionalProperties": False}},
            "provider_refund_results": {"type": "array", "items": {"type": "object", "properties": {
                "component": {"type": "string"}, "response": {"type": "object", "additionalProperties": True},
                "fact_ids": {"type": "array", "items": {"type": "integer"}},
            }, "required": ["component", "response", "fact_ids"], "additionalProperties": False}},
            "amount_reconciliation": {"type": ["object", "null"], "properties": {
                "paid_total": {"type": "string"}, "refund_total": {"type": "string"},
                "currency": {"type": "string"},
                "transactions": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
                "fact_ids": {"type": "array", "items": {"type": "integer"}},
            }, "required": ["paid_total", "refund_total", "currency", "transactions", "fact_ids"], "additionalProperties": False},
            "relevant_sources": {"type": "array", "items": {"type": "string"}},
            "identity_established": {"type": "boolean"},
            "lifecycle_checked": {"type": "boolean"},
            "retries_required": {"type": "boolean"},
            "retries_checked": {"type": "boolean"},
            "contradiction_ids_resolved": {"type": "array", "items": {"type": "integer"}},
            "terminal_state": {"type": ["object", "null"], "properties": {
                "state": {"type": "string"}, "funds_location": {"type": "string"}, "lifecycle_checked": {"type": "boolean"},
            }, "required": ["state", "funds_location", "lifecycle_checked"], "additionalProperties": False},
            "fact_ids": {"type": "array", "items": {"type": "integer"}},
            "claims": {"type": "array", "items": {"type": "object", "properties": {
                "text": {"type": "string"}, "fact_ids": {"type": "array", "items": {"type": "integer"}},
                "field": {"type": ["string", "null"]}, "expected_value": {"type": ["string", "number", "boolean", "null"]},
            }, "required": ["text", "fact_ids", "field", "expected_value"], "additionalProperties": False}},
            "negative_claims": {"type": "array", "items": {"type": "object", "properties": {
                "claim": {"type": "string"}, "source": {"type": "string"}, "identifiers": {"type": "array", "items": {"type": "string"}},
                "adequate_window": {"type": "boolean"}, "no_result_searches": {"type": "integer"}, "later_event_checked": {"type": "boolean"},
            }, "required": ["claim", "source", "identifiers", "adequate_window", "no_result_searches", "later_event_checked"], "additionalProperties": False}},
            "authorization_reconciliation": {"type": ["object", "null"], "properties": {
                "authorized_total": {"type": "string"}, "captured_total": {"type": "string"},
                "refunded_total": {"type": "string"}, "adjustment_amount": {"type": ["string", "null"]}, "currency": {"type": "string"},
            }, "required": ["authorized_total", "captured_total", "refunded_total", "adjustment_amount", "currency"], "additionalProperties": False},
            "replan": {"type": "boolean"},
            "mode": {"type": "string", "enum": ["A", "B", "C"]},
            "tier": {"type": "string", "enum": ["FAST", "STANDARD", "DEEP"]},
            "allow_gateway_names": {"type": "boolean"},
            "complete": {"type": "boolean"},
        },
        "required": [
            "searches", "hypotheses", "retries", "relevant_sources",
            "component_lifecycle", "provider_refund_results", "amount_reconciliation",
            "identity_established", "lifecycle_checked", "retries_required",
            "retries_checked", "contradiction_ids_resolved", "terminal_state", "fact_ids", "claims", "negative_claims", "authorization_reconciliation", "replan", "mode", "tier",
            "allow_gateway_names", "complete",
        ],
        "additionalProperties": False,
    }

    def __init__(self, *, instructions: str, model: str | None = None, api_key: str | None = None, base_url: str = "https://api.openai.com/v1", timeout: float = 120.0) -> None:
        self.instructions = instructions
        self.model = model or os.environ.get("OPENAI_MODEL", "gpt-5.2")
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY is required")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _request(self, *, input_text: str, structured: bool) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "instructions": self.instructions,
            "input": input_text,
            "store": False,
            "temperature": 0,
        }
        if structured:
            payload["text"] = {"format": {"type": "json_schema", "name": "dudley_proposal", "strict": True, "schema": self.PROPOSAL_SCHEMA}}
        response = httpx.post(
            f"{self.base_url}/responses",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()
        body = response.json()
        if body.get("status") not in {None, "completed"}:
            raise RuntimeError(f"OpenAI response not completed: {body.get('status')}")
        return body

    @staticmethod
    def _output_text(body: Mapping[str, Any]) -> str:
        text = body.get("output_text")
        if isinstance(text, str) and text.strip():
            return text
        chunks: list[str] = []
        for item in body.get("output", ()):
            for content in item.get("content", ()) if isinstance(item, Mapping) else ():
                if isinstance(content, Mapping) and content.get("type") == "output_text":
                    chunks.append(str(content.get("text", "")))
        result = "".join(chunks)
        if not result.strip():
            raise RuntimeError("OpenAI response contained no output text")
        return result

    def propose(self, context: Mapping[str, Any]) -> Mapping[str, Any]:
        return json.loads(self._output_text(self._request(input_text=json.dumps(context, default=str), structured=True)))

    def render(self, mode: str, context: Mapping[str, Any], fact_ids: tuple[int, ...]) -> str:
        prompt = json.dumps({"mode": mode, "context": context, "approved_fact_ids": fact_ids}, default=str)
        return self._output_text(self._request(input_text=prompt, structured=False))


class RegistrySearchExecutor(SearchExecutor):
    """Dispatch source requests to existing MCP connector functions.

    Each registered function receives a `SearchRequest` and returns a validated
    `ToolResult`. Transport errors are converted into FAILED results so the
    completion gate can reject them instead of losing the failure state.
    """

    def __init__(self, handlers: Mapping[str, Callable[[SearchRequest], ToolResult]]) -> None:
        self._handlers = dict(handlers)

    def search(self, request: SearchRequest) -> ToolResult:
        handler = self._handlers.get(request.source)
        if handler is None:
            return ToolResult(request.source, SearchResultState.FAILED, False, error="no handler registered")
        try:
            result = handler(request)
        except Exception as exc:  # transport/auth failures must enter controller state
            return ToolResult(request.source, SearchResultState.FAILED, False, error=f"{type(exc).__name__}: {exc}")
        if not isinstance(result, ToolResult):
            return ToolResult(request.source, SearchResultState.FAILED, False, error="handler returned invalid result type")
        return result


class RerankingSearchExecutor(SearchExecutor):
    """Reorder valid, case-scoped facts using an optional BGE reranker.

    This wrapper never filters facts, changes coverage, or admits new facts.
    It only improves the order in which an existing adapter's candidates are
    presented to the controller.
    """

    def __init__(self, base: SearchExecutor, reranker: Any) -> None:
        self.base = base
        self.reranker = reranker

    def search(self, request: SearchRequest) -> ToolResult:
        result = self.base.search(request)
        if not result.facts:
            return result
        order = self.reranker.rank(request.query, tuple(fact.raw_fact for fact in result.facts))
        return ToolResult(
            source=result.source,
            result_state=result.result_state,
            scoped_to_case=result.scoped_to_case,
            truncated=result.truncated,
            error=result.error,
            stale=result.stale,
            facts=tuple(result.facts[index] for index in order),
            warnings=result.warnings,
        )
