"""Structured human-review feedback for evaluation and regression mining."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


@dataclass(frozen=True)
class ReviewRecord:
    run_id: str
    accepted: bool
    original_output: str
    corrected_output: str | None = None
    error_type: str | None = None
    notes: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def classify_review(original: str, corrected: str | None, *, run_id: str, accepted: bool = False, notes: str = "") -> ReviewRecord:
    if accepted or corrected is None or corrected == original:
        error_type = None
    else:
        before = str(original).casefold()
        after = str(corrected).casefold()
        error_type = "arithmetic_or_fact" if any(token in before or token in after for token in ("arn", "refund", "capture", "settled", "amount")) else "wording_or_format"
    return ReviewRecord(run_id, accepted, original, corrected, error_type, notes)

