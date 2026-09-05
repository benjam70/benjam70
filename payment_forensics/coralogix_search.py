"""Deterministic Coralogix query planning and result-quality checks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re
from typing import TYPE_CHECKING, Iterable

from .controller import SearchResultState, ToolResult

if TYPE_CHECKING:
    from .engine import SearchRequest


@dataclass(frozen=True)
class QueryQuality:
    score: int
    allowed: bool
    reasons: tuple[str, ...] = ()


def assess_query(request: SearchRequest) -> QueryQuality:
    if request.source.casefold() != "coralogix":
        return QueryQuality(100, True)
    reasons: list[str] = []
    score = 100
    query = request.query
    if not query.lower().lstrip().startswith("source logs"):
        score -= 25
        reasons.append("query does not start with a logs source clause")
    if not request.identifiers:
        score -= 50
        reasons.append("no case identifier supplied")
    if request.start_date is None or request.end_date is None:
        score -= 25
        reasons.append("explicit date window missing")
    if re.search(r"\b(?:refund|capture|authori[sz]ation|cancel|chargeback|payment)\b", query, re.I) is None:
        score -= 10
        reasons.append("query has no payment-event term")
    return QueryQuality(score, score >= 50, tuple(reasons))


def time_sliced_queries(request: SearchRequest, *, max_slices: int = 12) -> tuple[SearchRequest, ...]:
    """Split a long window so archive gaps cannot hide inside one query."""
    from .engine import SearchRequest
    if request.source.casefold() != "coralogix" or not request.start_date or not request.end_date:
        return ()
    try:
        start = datetime.fromisoformat(request.start_date.replace("Z", "+00:00"))
        end = datetime.fromisoformat(request.end_date.replace("Z", "+00:00"))
    except ValueError:
        return ()
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    if end <= start or end - start <= timedelta(days=7):
        return ()
    step = max(timedelta(days=1), (end - start) / max(1, max_slices))
    slices: list[SearchRequest] = []
    cursor = start
    while cursor < end and len(slices) < max_slices:
        boundary = min(end, cursor + step)
        slices.append(SearchRequest(
            source=request.source,
            query=request.query,
            identifiers=request.identifiers,
            start_date=cursor.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            end_date=boundary.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            query_language=request.query_language,
        ))
        cursor = boundary
    return tuple(slices)


def alternate_queries(request: SearchRequest, *, events: Iterable[str] = ("AUTHORISATION", "CAPTURE", "REFUND", "CANCEL_OR_REFUND")) -> tuple[SearchRequest, ...]:
    """Build precise event queries after a valid no-result response."""
    if request.source.casefold() != "coralogix" or not request.identifiers or not request.start_date or not request.end_date:
        return ()
    identifiers = tuple(dict.fromkeys(request.identifiers))
    from .engine import SearchRequest
    variants = []
    for identifier in identifiers[:3]:
        for event in events:
            variants.append(SearchRequest(
                source=request.source,
                query=f"source logs | filter $l.applicationname == 'production' | filter $d ~ '{identifier}' | filter $d ~ 'eventCode={event}'",
                identifiers=(identifier,),
                start_date=request.start_date,
                end_date=request.end_date,
                query_language="dataprime",
            ))
    fields = ("message", "Message", "paymentId", "refundId", "transactionId", "merchantReference", "orderId")
    for identifier in identifiers[:3]:
        escaped = identifier.replace("\\", "\\\\").replace('"', '\\"')
        for field in fields:
            variants.append(SearchRequest(
                source=request.source,
                query=f'source logs | filter {field}:"{escaped}"',
                identifiers=(identifier,),
                start_date=request.start_date,
                end_date=request.end_date,
                query_language="lucene",
            ))
    return tuple(variants)


def result_quality(result: ToolResult) -> QueryQuality:
    reasons: list[str] = []
    error_text = result.diagnostics.casefold()
    if result.result_state == SearchResultState.PARTIAL or result.truncated:
        reasons.append("partial or truncated result")
    if any(marker in error_text for marker in ("missing data", "missingdata", "missing archive", "archive data", "rehydrat", "incomplete data")):
        reasons.append("archive or coverage gap reported")
    if result.result_state == SearchResultState.FAILED or result.diagnostics:
        reasons.append("failed result")
    if not result.scoped_to_case:
        reasons.append("result is not scoped to case")
    if result.result_state == SearchResultState.RESULTS and not result.facts:
        reasons.append("result has no normalized facts")
    return QueryQuality(100 if not reasons else 0, not reasons, tuple(reasons))
