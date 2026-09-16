"""Dependency-free structured telemetry for investigation runs."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from hashlib import sha256
import json
import os
from typing import Any, Mapping


@dataclass(frozen=True)
class TelemetryEvent:
    run_id: str
    case_id: str
    event: str
    round: int | None = None
    source: str | None = None
    tool_call_id: str | None = None
    result_state: str | None = None
    evidence_count: int | None = None
    query_hash: str | None = None
    details: Mapping[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def query_digest(query: str) -> str:
    return sha256(" ".join(str(query).split()).encode("utf-8")).hexdigest()


def telemetry_run_id(case_id: str, case_input: str) -> str:
    return sha256(f"{case_id}|{case_input}".encode("utf-8")).hexdigest()[:24]


def export_ndjson(events: list[TelemetryEvent]) -> str:
    return "\n".join(json.dumps(event.as_dict(), sort_keys=True, default=str) for event in events)


def emit_genai_spans(events: list[Mapping[str, Any]]) -> int:
    """Emit privacy-safe GenAI/tool spans when OTLP is explicitly enabled.

    The engine keeps raw prompts and queries out of these spans. Standard OTEL
    environment variables select the collector, so deployments can route them
    to Coralogix without hard-coding a vendor endpoint or secret here.
    """
    if os.environ.get("DUDLEY_OTEL_ENABLED") != "1" or not events:
        return 0
    try:
        from opentelemetry import trace
    except ImportError:
        return 0
    tracer = trace.get_tracer("dudley.engine")
    emitted = 0
    finish = next((event for event in reversed(events) if event.get("event") == "run_finished"), {})
    with tracer.start_as_current_span("invoke_agent Dudley") as run:
        run.set_attribute("gen_ai.operation.name", "invoke_agent")
        run.set_attribute("dudley.run.id", str(finish.get("run_id") or ""))
        run.set_attribute("dudley.outcome", str((finish.get("details") or {}).get("outcome") or ""))
        for event in events:
            if event.get("event") != "tool_result":
                continue
            with tracer.start_as_current_span("execute_tool Coralogix") as tool:
                tool.set_attribute("gen_ai.operation.name", "execute_tool")
                tool.set_attribute("gen_ai.tool.name", str(event.get("source") or "search"))
                tool.set_attribute("dudley.result_state", str(event.get("result_state") or ""))
                tool.set_attribute("dudley.evidence_count", int(event.get("evidence_count") or 0))
                tool.set_attribute("dudley.query_hash", str(event.get("query_hash") or ""))
                details = event.get("details") or {}
                tool.set_attribute("dudley.query_quality", int(details.get("query_quality") or 0))
                emitted += 1
    return emitted + 1

