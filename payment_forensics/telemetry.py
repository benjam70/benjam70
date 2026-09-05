"""Dependency-free structured telemetry for investigation runs."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from hashlib import sha256
import json
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

