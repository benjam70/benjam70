"""Optional Hugging Face consistency checking for proposed claim wording.

This module is deliberately opt-in. The controller and ledger remain the
source of truth; NLI can only flag a likely contradiction in generated text.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class NLIResult:
    label: str
    scores: dict[str, float]

    @property
    def is_contradiction(self) -> bool:
        return self.label.lower() in {"contradiction", "contradict"}


class HFNLIConsistencyChecker:
    """Lazy, local-only wrapper around a Hugging Face NLI pipeline."""

    def __init__(self, model_name: str = "cross-encoder/nli-deberta-v3-base", *, local_files_only: bool = True) -> None:
        try:
            from transformers import pipeline
        except ImportError as exc:  # pragma: no cover - depends on optional install
            raise RuntimeError("Install the optional transformers package to enable Hugging Face NLI") from exc
        self._pipeline = pipeline(
            "text-classification",
            model=model_name,
            tokenizer=model_name,
            local_files_only=local_files_only,
        )

    def check(self, premise: str, hypothesis: str) -> NLIResult:
        result: Any = self._pipeline({"text": premise, "text_pair": hypothesis})
        if isinstance(result, list):
            result = result[0]
        return NLIResult(str(result.get("label", "unknown")), {str(result.get("label", "unknown")): float(result.get("score", 0.0))})
