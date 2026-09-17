"""Optional SlopScore gate for Mode B/C prose quality.

Vale enforces house style. ``slop_check`` is the deterministic regex floor for
AI-writing tells. This module adds a scored second opinion via
``slopscore-lint`` (transparent pattern score with evidence spans).

Gate policy (from the local trial on Mode B/C notes):
- Missing package: skip (allowed), same pattern as Harper/Vale.
- Notes under ``MIN_WORDS``: allow. Short CS notes are below SlopScore's
  reliable floor and must not fail the engine.
- Notes at/above ``MIN_WORDS`` with ``slop_score >= SCORE_THRESHOLD``: reject.

Never sends text to a hosted service.
"""

from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class SlopScoreResult:
    available: bool
    allowed: bool
    skipped: bool = False
    score: float | None = None
    word_count: int | None = None
    label: str | None = None
    messages: tuple[str, ...] = ()


SCORE_THRESHOLD = 40.0
MIN_WORDS = 80

_FENCE_RE = re.compile(r"```(?:\w+)?\n([\s\S]*?)```")


def prose_for_scoring(text: str) -> str:
    """Score the Mode B/C body, not markdown fence chrome."""
    raw = str(text or "")
    matches = list(_FENCE_RE.finditer(raw))
    if not matches:
        return raw.strip()
    first = matches[0]
    prefix = raw[: first.start()].strip()
    body = first.group(1).strip()
    if prefix:
        return f"{prefix}\n\n{body}".strip()
    return body


def run_slopscore_check(
    text: str,
    *,
    score_threshold: float = SCORE_THRESHOLD,
    min_words: int = MIN_WORDS,
) -> SlopScoreResult:
    """Score Mode B/C prose with slopscore-lint when installed."""
    try:
        from slopscore.config import Settings, Strictness
        from slopscore.core import SlopScorer
    except ImportError:
        return SlopScoreResult(
            available=False,
            allowed=True,
            skipped=True,
            messages=("slopscore-lint not installed",),
        )

    prose = prose_for_scoring(text)
    if not prose:
        return SlopScoreResult(available=True, allowed=True, skipped=True, messages=("empty prose after fence strip",))

    try:
        settings = Settings(
            profile="blog",
            strictness=Strictness.balanced,
            min_reliable_words=min_words,
        )
        report = SlopScorer(settings=settings).scan_text(prose, source="<mode-bc>")
    except Exception as exc:  # noqa: BLE001 - optional quality gate must never crash the case
        return SlopScoreResult(
            available=True,
            allowed=True,
            skipped=True,
            messages=(f"slopscore did not run: {exc}",),
        )

    score = float(report.score.slop_score)
    words = int(report.input.word_count)
    label = str(report.score.label)
    if words < min_words:
        return SlopScoreResult(
            available=True,
            allowed=True,
            score=score,
            word_count=words,
            label=label,
            messages=(f"SlopScore {score:.1f} ({label}) on {words} words; below {min_words}-word gate floor",),
        )

    if score >= score_threshold:
        evidence = tuple(
            f"{item.rule_id}: {item.span[:80]}"
            for item in report.evidence[:5]
        )
        messages = (
            f"SlopScore {score:.1f} ({label}) on {words} words exceeds threshold {score_threshold:.0f}",
            *evidence,
        )
        return SlopScoreResult(
            available=True,
            allowed=False,
            score=score,
            word_count=words,
            label=label,
            messages=messages,
        )

    return SlopScoreResult(
        available=True,
        allowed=True,
        score=score,
        word_count=words,
        label=label,
    )
