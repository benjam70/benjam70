"""Small deterministic checks for agent trajectories and source coverage."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping


@dataclass(frozen=True)
class TrajectoryValidation:
    allowed: bool
    reasons: tuple[str, ...] = ()


def validate_trajectory(
    steps: Iterable[Mapping[str, object]],
    *,
    required_sources: Iterable[str] = (),
    completion_claimed: bool = False,
    required_identifiers: Iterable[str] = (),
) -> TrajectoryValidation:
    """Check that required sources were actually queried before completion."""
    steps_list = tuple(steps)
    required = {str(source).casefold() for source in required_sources}
    queried = {
        str(step.get("source", step.get("tool", ""))).casefold()
        for step in steps_list
        if step.get("source", step.get("tool")) is not None
    }
    missing = sorted(required - queried)
    failures = sorted(
        str(step.get("source", step.get("tool", "")))
        for step in steps_list
        if str(step.get("result_state", "")).upper() in {"FAILED", "PARTIAL"}
        and str(step.get("source", step.get("tool", ""))).casefold() in required
    )
    reasons = [f"required source was not queried: {source}" for source in missing]
    reasons.extend(f"required source returned incomplete result: {source}" for source in failures)
    identifiers = tuple(str(value) for value in required_identifiers if str(value).strip())
    for step in steps_list:
        source = str(step.get("source", step.get("tool", "")))
        if not source or source.casefold() not in required:
            continue
        searchable = " ".join((str(step.get("query", "")), *(str(value) for value in step.get("identifiers", ()))))
        missing_ids = [identifier for identifier in identifiers if identifier.casefold() not in searchable.casefold()]
        reasons.extend(f"tool call missing case identifier: {identifier} ({source})" for identifier in missing_ids)
    if completion_claimed and reasons:
        reasons.append("completion cannot be claimed with incomplete required-source coverage")
    return TrajectoryValidation(not reasons, tuple(reasons))
