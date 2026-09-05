"""Optional hybrid retrieval helpers for payment-log candidate discovery.

Semantic retrieval is deliberately advisory. Exact identifiers and the
controller's evidence gates remain authoritative.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Any, Iterable, Sequence


@dataclass(frozen=True)
class CandidateDocument:
    document_id: str
    text: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class RankedCandidate:
    document: CandidateDocument
    score: float
    lexical_score: float
    dense_score: float | None = None


class HybridCandidateIndex:
    """Fuse exact lexical recall with optional BGE-M3 dense recall."""

    def __init__(self, documents: Iterable[CandidateDocument] = (), *, embedder: Any | None = None) -> None:
        self.documents = list(documents)
        self.embedder = embedder
        self._embeddings: Any | None = None
        if self.embedder is not None and self.documents:
            self._embeddings = self.embedder.encode([item.text for item in self.documents], normalize_embeddings=True)

    def add(self, documents: Iterable[CandidateDocument]) -> None:
        self.documents.extend(documents)
        if self.embedder is not None:
            self._embeddings = self.embedder.encode([item.text for item in self.documents], normalize_embeddings=True)

    def search(self, query: str, *, limit: int = 20) -> tuple[RankedCandidate, ...]:
        query_tokens = _tokens(query)
        dense_scores: list[float] | None = None
        if self.embedder is not None and self.documents:
            vector = self.embedder.encode([query], normalize_embeddings=True)[0]
            dense_scores = [_dot(vector, row) for row in self._embeddings]
        ranked = []
        for index, document in enumerate(self.documents):
            lexical = _lexical_score(query_tokens, _tokens(document.text))
            dense = dense_scores[index] if dense_scores is not None else None
            score = (0.55 * lexical) + (0.45 * max(dense, 0.0)) if dense is not None else lexical
            ranked.append(RankedCandidate(document, score, lexical, dense))
        return tuple(sorted(ranked, key=lambda item: (-item.score, item.document.document_id))[:limit])


class BGEEmbedder:
    """Lazy BGE-M3 loader. Importing this module does not download a model."""

    @classmethod
    def from_pretrained(cls, model_name: str = "BAAI/bge-m3", *, offline: bool = True, cache_folder: str | None = None) -> Any:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError("Install retrieval-requirements.txt to enable BGE-M3 retrieval") from exc
        return SentenceTransformer(model_name, local_files_only=offline, cache_folder=cache_folder)


class BGEReranker:
    """Lazy BGE multilingual reranker for already retrieved candidates."""

    def __init__(self, model: Any) -> None:
        self.model = model

    @classmethod
    def from_pretrained(cls, model_name: str = "BAAI/bge-reranker-v2-m3", *, offline: bool = True, cache_dir: str | None = None) -> "BGEReranker":
        try:
            from FlagEmbedding import FlagReranker
        except ImportError as exc:
            raise RuntimeError("Install retrieval-requirements.txt to enable BGE reranking") from exc
        return cls(FlagReranker(model_name, use_fp16=False, cache_dir=cache_dir, local_files_only=offline))

    def rank(self, query: str, candidates: Sequence[str]) -> tuple[int, ...]:
        if not candidates:
            return ()
        scores = self.model.compute_score([[query, candidate] for candidate in candidates], normalize=True)
        if not isinstance(scores, list):
            scores = [scores]
        return tuple(sorted(range(len(candidates)), key=lambda index: (-float(scores[index]), index)))


def _tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9_:-]+", value.lower()))


def _lexical_score(query: set[str], document: set[str]) -> float:
    if not query or not document:
        return 0.0
    return len(query & document) / math.sqrt(len(query) * len(document))


def _dot(left: Any, right: Any) -> float:
    return float(sum(float(a) * float(b) for a, b in zip(left, right)))
