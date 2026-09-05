"""Replayable, redacted investigation audit records."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping
import hashlib
import json

from .safety import redact_sensitive


def explain_replay_difference(left: Mapping[str, Any], right: Mapping[str, Any]) -> tuple[str, ...]:
    """Return stable top-level differences between two audit records."""
    return tuple(key for key in sorted(set(left) | set(right)) if key != "recorded_at" and left.get(key) != right.get(key))


def build_audit_record(*, case_id: str, status: str, mode: str | None, rounds: int, gate: Mapping[str, Any], state: Mapping[str, Any], output: str | None = None) -> dict[str, Any]:
    replay_material = json.dumps({"case_id": case_id, "status": status, "mode": mode, "rounds": rounds, "gate": dict(gate), "state": dict(state), "output": output}, sort_keys=True, default=str).encode("utf-8")
    return redact_sensitive({
        "case_id": case_id,
        "status": status,
        "mode": mode,
        "rounds": rounds,
        "gate": dict(gate),
        "state": dict(state),
        "output": output,
        "replay_hash": hashlib.sha256(replay_material).hexdigest(),
        "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    })
