"""Small, dependency-free confidence calibration helpers."""

from __future__ import annotations

from typing import Iterable, Mapping, Any


def calibration_report(records: Iterable[Mapping[str, Any]], *, bins: int = 5) -> dict[str, Any]:
    """Compare predicted confidence with binary outcomes using fixed bins."""
    groups = [{"count": 0, "confidence": 0.0, "accuracy": 0.0} for _ in range(bins)]
    brier_total = 0.0
    count = 0
    for record in records:
        confidence = min(1.0, max(0.0, float(record.get("confidence", 0.0))))
        outcome = 1.0 if bool(record.get("correct", False)) else 0.0
        index = min(bins - 1, int(confidence * bins))
        group = groups[index]
        group["count"] += 1
        group["confidence"] += confidence
        group["accuracy"] += outcome
        brier_total += (confidence - outcome) ** 2
        count += 1
    for group in groups:
        if group["count"]:
            group["confidence"] /= group["count"]
            group["accuracy"] /= group["count"]
    return {"bins": groups, "brier_score": brier_total / count if count else None, "count": count}

