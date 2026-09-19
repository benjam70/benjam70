"""Real edit-distance fuzzy matching for Coralogix field values.

Coralogix's own "fuzzy" search (``$d ~~ 'term'`` / ``wildfind``) is plain
substring matching, not edit-distance tolerant, confirmed against both
Coralogix's own docs and live testing documented in the payment-forensics
skill. The ``matches()`` function is strict regex, also not typo-tolerant.
There is no server-side fix for a misspelled or uncertain search term.

This module closes that gap client-side: given a term and a list of real
candidate values already pulled from Coralogix (e.g. the ``examples``
column of a ``system/engine.schema_fields`` row, or a
``coralogix_search_fields`` value-mode result), it ranks the candidates by
actual edit distance, so a typo like "AuthorizationFailed" surfaces the
real value "AutherizationFailed" instead of a silent, wrong zero.

Requires the optional ``rapidfuzz`` package. Without it, callers should
fall back to the schema_fields catalog lookup already documented in the
skill; a missing install is not a data gap.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FuzzyMatch:
    value: str
    score: float


def rank_similar(
    term: str,
    candidates: list[str] | tuple[str, ...],
    *,
    limit: int = 5,
    score_cutoff: float = 60.0,
) -> tuple[FuzzyMatch, ...]:
    """Rank candidate field values by true edit-distance similarity to `term`.

    Uses rapidfuzz's WRatio, which blends whole-string and
    partial/token matching, so both a whole-value typo
    (AuthorizationFailed vs AutherizationFailed) and a substring match
    inside a longer value are caught by the same ranking. Results below
    `score_cutoff` are dropped rather than returned as weak noise.
    """
    try:
        from rapidfuzz import fuzz, process
    except ImportError as exc:  # pragma: no cover - depends on optional install
        raise RuntimeError(
            "Install the optional rapidfuzz package to enable fuzzy field-value matching"
        ) from exc
    deduped = list(dict.fromkeys(candidates))
    if not term or not deduped:
        return ()
    results = process.extract(
        term, deduped, scorer=fuzz.WRatio, limit=limit, score_cutoff=score_cutoff
    )
    return tuple(FuzzyMatch(value=value, score=score) for value, score, _ in results)
