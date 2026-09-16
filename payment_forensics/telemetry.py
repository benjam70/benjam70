"""Dependency-free structured telemetry for investigation runs."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from hashlib import sha256
import json
import os
from threading import Lock
from typing import Any, Mapping


_OTEL_CONFIGURATION_LOCK = Lock()
_OTEL_CONFIGURED = False


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


def _otel_enabled() -> bool:
    """Require an explicit opt-in and destination before creating any spans.

    The OTLP SDK otherwise defaults to localhost in some configurations.  That
    is surprising in a desktop or test run and makes it too easy to export
    telemetry to an unintended collector.
    """
    return (
        os.environ.get("DUDLEY_OTEL_ENABLED") == "1"
        and bool(os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"))
    )


def _configure_otel() -> object | None:
    """Attach one OTLP/HTTP exporter to the application's tracer provider.

    All endpoint, authentication and Coralogix resource settings remain in
    standard OTEL environment variables; secrets never enter Dudley's code or
    investigation state.  Importing this module remains dependency-free.
    """
    global _OTEL_CONFIGURED
    if _OTEL_CONFIGURED:
        try:
            from opentelemetry import trace
            return trace.get_tracer_provider()
        except ImportError:
            return None
    with _OTEL_CONFIGURATION_LOCK:
        if _OTEL_CONFIGURED:
            try:
                from opentelemetry import trace
                return trace.get_tracer_provider()
            except ImportError:
                return None
        try:
            from opentelemetry import trace
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            from opentelemetry.sdk.resources import Resource, SERVICE_NAME
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            provider = trace.get_tracer_provider()
            if not hasattr(provider, "add_span_processor"):
                provider = TracerProvider(
                    resource=Resource.create(
                        {SERVICE_NAME: os.environ.get("OTEL_SERVICE_NAME", "dudley-engine")}
                    )
                )
                trace.set_tracer_provider(provider)
            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        except (ImportError, OSError, ValueError):
            return None
        _OTEL_CONFIGURED = True
        return provider


def emit_genai_spans(events: list[Mapping[str, Any]]) -> int:
    """Emit privacy-safe GenAI/tool spans when OTLP is explicitly enabled.

    The engine keeps raw prompts and queries out of these spans. Standard OTEL
    environment variables select the collector, so deployments can route them
    to Coralogix without hard-coding a vendor endpoint or secret here.
    """
    if not _otel_enabled() or not events:
        return 0
    provider = _configure_otel()
    if provider is None:
        return 0
    from opentelemetry import trace
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

