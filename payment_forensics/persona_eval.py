"""Small advisory probes for Dudley's conversational identity."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping


@dataclass(frozen=True)
class PersonaValidation:
    allowed: bool
    reasons: tuple[str, ...] = ()


def validate_persona_turn(text: str, *, correction: bool = False, new_evidence: bool = False) -> PersonaValidation:
    value = " ".join(str(text).split()).casefold()
    reasons: list[str] = []
    if not value:
        reasons.append("empty response")
    if correction and not any(marker in value for marker in ("right", "correct", "changes", "update", "good catch")):
        reasons.append("correction was not acknowledged")
    if new_evidence and not any(marker in value for marker in ("new evidence", "changes", "now", "adds", "updated")):
        reasons.append("new evidence was not connected to the finding")
    if value.count("second pair of eyes") > 1:
        reasons.append("persona label repeated mechanically")
    return PersonaValidation(not reasons, tuple(reasons))


def validate_persona_trajectory(turns: Iterable[Mapping[str, object]]) -> PersonaValidation:
    reasons: list[str] = []
    for index, turn in enumerate(turns):
        result = validate_persona_turn(str(turn.get("text", "")), correction=bool(turn.get("correction")), new_evidence=bool(turn.get("new_evidence")))
        reasons.extend(f"turn {index}: {reason}" for reason in result.reasons)
    return PersonaValidation(not reasons, tuple(reasons))
