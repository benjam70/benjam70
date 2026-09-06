"""Optional Hugging Face relevance scoring for drafted CS notes and merchant emails.

This module is deliberately opt-in, same pattern as nli.py. It answers a
narrower question than request_understanding's keyword-based checks: not
"was this slot mentioned" but "does this passage actually address that
question," scored semantically rather than by keyword presence. It
supplements validate_ticket_answer / unanswered_after_draft, it does not
replace them.
"""

from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class RelevanceResult:
    score: float
    threshold: float

    @property
    def is_relevant(self) -> bool:
        return self.score >= self.threshold


class CrossEncoderRelevanceChecker:
    """Lazy, local-only wrapper around a Hugging Face cross-encoder relevance model."""

    def __init__(self, model_name: str = "cross-encoder/ms-marco-MiniLM-L6-v2", *, local_files_only: bool = True) -> None:
        try:
            from sentence_transformers import CrossEncoder
        except ImportError as exc:  # pragma: no cover - depends on optional install
            raise RuntimeError("Install the optional sentence-transformers package to enable relevance scoring") from exc
        self._model = CrossEncoder(model_name, local_files_only=local_files_only)

    def score(self, question: str, answer: str, *, threshold: float = 0.5) -> RelevanceResult:
        raw = self._model.predict([(question, answer)])
        value = float(raw[0])
        squashed = 1.0 / (1.0 + math.exp(-value))
        return RelevanceResult(squashed, threshold)
