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


_FUZZY_TILDE_RE = re.compile(r"~~")
_LUCENE_FUZZY_SUFFIX_RE = re.compile(r'''["']?\w+["']?~\d*(?=\s|\)|"|'|$)''')
_COMPOUND_NEGATED_REGEX_RE = re.compile(r"(?:\|\||&&).*!~|!~.*(?:\|\||&&)")
_GE_CORRELATION_ID_RE = re.compile(r"\bGECorrelationId\b", re.I)
_NESTED_DOTTED_PATH_RE = re.compile(r"\$d\.\w+\.\w+")
_NEO_SOURCE_RE = re.compile(r"\bneo\b", re.I)


def assess_query(request: SearchRequest) -> QueryQuality:
    is_coralogix_source = request.source.casefold() == "coralogix" or "coralogix" in request.source.casefold()
    if is_coralogix_source and _NEO_SOURCE_RE.search(request.source):
        return QueryQuality(
            0,
            False,
            (
                "Neo-routed Coralogix search is banned here: confirmed to return a "
                "false empty result on a real case that the direct connector answered "
                "immediately on the identical query and window; use the direct "
                "Coralogix connector instead",
            ),
        )
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
    if _FUZZY_TILDE_RE.search(query):
        score -= 30
        reasons.append(
            "fuzzy operator ~~ is unsupported here (it's plain substring matching, "
            "not edit-distance tolerant); use coralogix_search_fields to find the "
            "real spelling instead of a fuzzy guess"
        )
    if request.query_language == "lucene" and _LUCENE_FUZZY_SUFFIX_RE.search(query):
        score -= 30
        reasons.append(
            "lucene's native fuzzy suffix (term~, term~1) returns a hard 400 here; "
            "drop the suffix and match the exact term"
        )
    if _COMPOUND_NEGATED_REGEX_RE.search(query):
        score -= 25
        reasons.append(
            "a compound filter mixing ||/&& with a negated regex (!~) returns a hard "
            "400; split into two plain single-condition filters instead"
        )
    if _GE_CORRELATION_ID_RE.search(query):
        score -= 15
        reasons.append(
            "GECorrelationId is a batch-job run ID spanning many unrelated orders, "
            "not a per-order correlation key; use entityId instead"
        )
    if _NESTED_DOTTED_PATH_RE.search(query):
        reasons.append(
            "nested dotted path into the JSON body (e.g. $d.userData.foo) fails "
            "silently on a wrong guess (zero rows, no error); confirm the path via "
            "coralogix_search_fields first"
        )
    return QueryQuality(max(score, 0), score >= 50, tuple(reasons))


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
