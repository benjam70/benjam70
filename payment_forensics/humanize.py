"""Deterministic safety checks for a constrained humanization pass."""

from __future__ import annotations

from dataclasses import dataclass
import re
from collections import Counter


@dataclass(frozen=True)
class HumanizationValidation:
    allowed: bool
    reasons: tuple[str, ...] = ()


# These spans carry identity, money, chronology, or source provenance.
_PROTECTED_PATTERNS = (
    re.compile(r"https?://[^\s)]+", re.IGNORECASE),
    re.compile(r"\b(?:GE\d{6,}|pi_[A-Za-z0-9_]+|ch_[A-Za-z0-9_]+|[A-Z]{2,8}-\d{3,})\b"),
    re.compile(r"\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:?\d{2})?)?\b"),
    re.compile(r"\b(?:ARN|ID|id|refund|payment|dispute)[ :#-]*[A-Za-z0-9_./-]{3,}\b"),
    re.compile(r"(?<!\w)(?:[A-Z]{1,4}\$|[$€£¥]|\b[A-Z]{1,3}\b)\s?\d+(?:[.,]\d{2})?(?!\w)"),
    re.compile(r"\[[^\]\n]{1,120}\]"),
)


def protected_spans(text: str) -> tuple[str, ...]:
    """Return normalized high-signal spans that a rewrite must preserve."""
    found: list[str] = []
    for pattern in _PROTECTED_PATTERNS:
        found.extend(match.group(0) for match in pattern.finditer(text))
    return tuple(found)


def validate_humanized_draft(original: str, rewritten: str) -> HumanizationValidation:
    """Reject rewrites that alter or drop protected factual spans."""
    if not isinstance(original, str) or not isinstance(rewritten, str):
        return HumanizationValidation(False, ("original and rewritten text must be strings",))
    original_spans = Counter(protected_spans(original))
    rewritten_spans = Counter(protected_spans(rewritten))
    reasons = []
    for span, count in original_spans.items():
        if rewritten_spans[span] < count:
            reasons.append(f"protected span changed or removed: {span}")
    return HumanizationValidation(not reasons, tuple(reasons))
