"""Avenue checklist, triangulation, and programmatic exhaustion control.

Keeps the Hybrid Engine digging until each required investigation avenue is
SUPPORTED, CONTRADICTED, or EXHAUSTED — not merely until the model feels done.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Iterable, Mapping, Sequence


class PredicateStatus(str, Enum):
    OPEN = "OPEN"
    SUPPORTED = "SUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    EXHAUSTED = "EXHAUSTED"


class RoundVerdict(str, Enum):
    PRODUCTIVE = "PRODUCTIVE"
    QUERY_STALE = "QUERY_STALE"
    EXHAUSTED = "EXHAUSTED"


CLOSED_STATUSES = frozenset({PredicateStatus.SUPPORTED, PredicateStatus.CONTRADICTED, PredicateStatus.EXHAUSTED})


@dataclass
class AvenuePredicate:
    """One checkable investigation avenue that must be closed before completion."""

    predicate_id: str
    label: str
    status: PredicateStatus = PredicateStatus.OPEN
    event_types: tuple[str, ...] = ()
    required_sources: tuple[str, ...] = ()
    search_count: int = 0
    supporting_fact_ids: tuple[int, ...] = ()
    contradicting_fact_ids: tuple[int, ...] = ()
    exhaustion_reasons: tuple[str, ...] = ()
    pivot_hints: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status.value
        return payload

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "AvenuePredicate":
        return cls(
            predicate_id=str(raw["predicate_id"]),
            label=str(raw["label"]),
            status=PredicateStatus(str(raw.get("status", PredicateStatus.OPEN.value))),
            event_types=tuple(raw.get("event_types", ())),
            required_sources=tuple(raw.get("required_sources", ())),
            search_count=int(raw.get("search_count", 0)),
            supporting_fact_ids=tuple(int(value) for value in raw.get("supporting_fact_ids", ())),
            contradicting_fact_ids=tuple(int(value) for value in raw.get("contradicting_fact_ids", ())),
            exhaustion_reasons=tuple(raw.get("exhaustion_reasons", ())),
            pivot_hints=tuple(raw.get("pivot_hints", ())),
        )


@dataclass(frozen=True)
class TriangulationRule:
    name: str
    sources: tuple[str, ...]
    applies_to: tuple[str, ...]  # intent keywords or "always"


# Refund/dispute triangulation matrix: both members must be CHECKED or N/A.
DEFAULT_TRIANGULATION: tuple[TriangulationRule, ...] = (
    TriangulationRule("refund_gateway_coralogix", ("Gateway", "Coralogix"), ("refund", "payment", "always")),
    TriangulationRule("admin_gateway", ("Admin", "Gateway"), ("refund", "payment")),
    TriangulationRule("dispute_justt_coralogix", ("Justt", "Coralogix"), ("dispute", "chargeback")),
)


def build_avenue_checklist(
    case_input: str,
    *,
    identifiers: Iterable[str] = (),
    intent: str | None = None,
) -> list[AvenuePredicate]:
    """Derive the mandatory avenue list from case text and ticket intent."""
    lowered = case_input.casefold()
    intent_text = (intent or "").casefold()
    ids = tuple(str(value) for value in identifiers if value)
    avenues: list[AvenuePredicate] = []

    def add(predicate_id: str, label: str, **kwargs: Any) -> None:
        if any(item.predicate_id == predicate_id for item in avenues):
            return
        avenues.append(AvenuePredicate(predicate_id=predicate_id, label=label, **kwargs))

    add(
        "identity",
        "Order/payment identity established or explicitly unknown",
        pivot_hints=("search order ID", "search PSP reference", "search ARN"),
    )
    add(
        "authorisation",
        "Authorisation event checked across relevant sources",
        event_types=("AUTHORISATION", "AUTHORIZATION", "PAYMENT"),
        required_sources=("Coralogix", "Gateway"),
        pivot_hints=("AUTHORISATION eventCode", "payment_intent", "PreAuthorize"),
    )
    add(
        "capture_or_settlement",
        "Capture or settlement event checked",
        event_types=("CAPTURE", "SETTLEMENT", "PAYMENT"),
        required_sources=("Coralogix", "Gateway"),
        pivot_hints=("CAPTURE", "charge.captured", "Settle"),
    )

    if "refund" in lowered or "refund" in intent_text or intent_text in {"refund_status", "payment_investigation"}:
        add(
            "refund_execution",
            "Refund execution confirmed or proven absent",
            event_types=("REFUND", "REFUNDED", "CANCEL_OR_REFUND"),
            required_sources=("Gateway", "Coralogix"),
            pivot_hints=("REFUND event", "charge.refunded", "refund ID", "gift card refund"),
        )
        add(
            "refund_arn_or_rail",
            "ARN present or low-visibility rail disclosed",
            event_types=("REFUND", "REFUNDED"),
            required_sources=("Gateway",),
            pivot_hints=("ARN field", "gift card confirmation", "stored-value ledger"),
        )

    if any(token in lowered or token in intent_text for token in ("chargeback", "dispute")):
        add(
            "dispute_lifecycle",
            "Dispute/chargeback lifecycle checked via Justt or explicit no-path",
            event_types=("CHARGEBACK", "DISPUTE"),
            required_sources=("Justt", "Coralogix"),
            pivot_hints=("JusttNotificationHandler", "pspStatus", "dueDate", "Klarna portal no-path"),
        )

    if "gift" in lowered or "split" in lowered or "tender" in lowered:
        add(
            "split_tender",
            "Each tender leg reconciled separately",
            event_types=("REFUND", "CAPTURE", "AUTHORISATION"),
            required_sources=("Admin", "Gateway"),
            pivot_hints=("component_lifecycle", "gift card", "card leg"),
        )

    if not ids:
        add(
            "identifier_discovery",
            "Locate candidate order/PSP identifiers when none were supplied",
            pivot_hints=("shipping address token", "full name", "card last4"),
        )

    add(
        "terminal_funds",
        "Terminal funds location established or disclosed unknown",
        pivot_hints=("settlement", "refunded", "dispute held", "gateway pending"),
    )
    add(
        "disconfirm_active_hypotheses",
        "Active hypotheses each received a disconfirming search",
        pivot_hints=("search for opposing event", "search alternate PSP status"),
    )
    return avenues


def required_triangulations(case_input: str, intent: str | None = None) -> tuple[TriangulationRule, ...]:
    lowered = f"{case_input} {intent or ''}".casefold()
    selected: list[TriangulationRule] = []
    for rule in DEFAULT_TRIANGULATION:
        if "always" in rule.applies_to or any(token in lowered for token in rule.applies_to):
            selected.append(rule)
    return tuple(selected)


def triangulation_gaps(
    coverage: Mapping[str, str],
    rules: Sequence[TriangulationRule],
    *,
    available_sources: Iterable[str] | None = None,
) -> tuple[str, ...]:
    """Return unmet triangulation pairs.

    Only sources that were actually touched (CHECKED/N/A/PARTIAL/FAILED) or that
    are explicitly listed in `available_sources` participate. Untouched default
    coverage rows like Admin do not block completion.
    """
    touched = {
        key for key, value in coverage.items()
        if value not in {"NOT_CHECKED"}
    }
    if available_sources is not None:
        available = {str(source) for source in available_sources}
    else:
        available = set(touched)
    gaps: list[str] = []
    for rule in rules:
        # Enforce a rule only when every member is in the active source set for this case.
        if not all(source in available for source in rule.sources):
            continue
        members = [coverage.get(source, "NOT_CHECKED") for source in rule.sources]
        if not all(status in {"CHECKED", "N/A", "NA"} for status in members):
            gaps.append(f"triangulation incomplete: {rule.name} requires {'+'.join(rule.sources)}")
    return tuple(gaps)


def update_avenues_from_state(
    avenues: list[AvenuePredicate],
    *,
    evidence: Sequence[Mapping[str, Any]],
    searches: Sequence[Mapping[str, Any]],
    coverage: Mapping[str, str],
    identifiers: Iterable[str],
    terminal_state: str | None,
    funds_location: str | None,
    hypotheses: Sequence[Mapping[str, Any]] = (),
    negative_claims: Sequence[Mapping[str, Any]] = (),
) -> list[AvenuePredicate]:
    """Deterministically close avenues from admitted evidence and search history."""
    id_set = {str(value) for value in identifiers if value}
    event_index: dict[str, list[int]] = {}
    for index, item in enumerate(evidence):
        event_type = str(item.get("event_type") or item.get("status") or "").upper()
        if not event_type:
            continue
        event_index.setdefault(event_type, []).append(index)

    for avenue in avenues:
        if avenue.status in CLOSED_STATUSES and avenue.predicate_id != "disconfirm_active_hypotheses":
            continue

        if avenue.predicate_id == "identity":
            if id_set:
                avenue.status = PredicateStatus.SUPPORTED
                avenue.exhaustion_reasons = ()
            elif any(search.get("result_state") == "NO_RESULT" for search in searches):
                avenue.search_count = max(avenue.search_count, len(searches))
                if avenue.search_count >= 2:
                    avenue.status = PredicateStatus.EXHAUSTED
                    avenue.exhaustion_reasons = ("no identifiers found after identifier searches",)
            continue

        if avenue.predicate_id == "terminal_funds":
            if terminal_state and funds_location and str(funds_location).lower() != "unknown":
                avenue.status = PredicateStatus.SUPPORTED
            elif terminal_state and str(terminal_state).upper() == "UNKNOWN":
                avenue.status = PredicateStatus.EXHAUSTED
                avenue.exhaustion_reasons = ("terminal state explicitly unknown",)
            continue

        if avenue.predicate_id == "disconfirm_active_hypotheses":
            active = [item for item in hypotheses if str(item.get("status", "active")) == "active"]
            if not active:
                avenue.status = PredicateStatus.SUPPORTED
                continue
            with_disconfirm = [
                item for item in active
                if item.get("contradicting") or item.get("disconfirm_searched")
            ]
            if len(with_disconfirm) == len(active):
                avenue.status = PredicateStatus.SUPPORTED
            else:
                avenue.status = PredicateStatus.OPEN
                avenue.pivot_hints = ("issue disconfirm search for each active hypothesis",)
            continue

        if avenue.predicate_id == "refund_arn_or_rail":
            arn_facts = [
                index for index, item in enumerate(evidence)
                if item.get("arn") or str(item.get("payment_method", "")).casefold() in {"giftcard", "gift card", "stored value", "virtual"}
            ]
            if arn_facts:
                avenue.status = PredicateStatus.SUPPORTED
                avenue.supporting_fact_ids = tuple(arn_facts)
                continue
            refund_searches = [
                search for search in searches
                if "refund" in str(search.get("query", "")).casefold() or search.get("source") in avenue.required_sources
            ]
            avenue.search_count = len(refund_searches)
            if avenue.search_count >= 1:
                avenue.status = PredicateStatus.EXHAUSTED
                avenue.exhaustion_reasons = ("ARN not present on refund evidence; treat as low-visibility or unresolved ARN",)
            continue

        matched_ids: list[int] = []
        for event_type in avenue.event_types:
            matched_ids.extend(event_index.get(event_type.upper(), ()))
        if matched_ids:
            avenue.status = PredicateStatus.SUPPORTED
            avenue.supporting_fact_ids = tuple(sorted(set(matched_ids)))
            continue

        related_searches = [
            search for search in searches
            if search.get("source") in avenue.required_sources
            or any(token.casefold() in str(search.get("query", "")).casefold() for token in avenue.event_types)
        ]
        avenue.search_count = len(related_searches)
        required = tuple(source for source in avenue.required_sources if source in coverage) or ("Coralogix",)
        sources_checked = all(coverage.get(source) in {"CHECKED", "N/A", "NA"} for source in required)
        # Matching evidence already returned SUPPORTED above. Once required sources
        # were searched without producing that event, close as exhausted.
        if sources_checked and avenue.search_count >= max(1, len(required)):
            avenue.status = PredicateStatus.EXHAUSTED
            avenue.exhaustion_reasons = (
                f"no supporting event after {avenue.search_count} related searches",
            )
    return avenues


def open_avenues(avenues: Sequence[AvenuePredicate]) -> tuple[AvenuePredicate, ...]:
    return tuple(item for item in avenues if item.status == PredicateStatus.OPEN)


def classify_round_progress(
    *,
    previous_open: int,
    current_open: int,
    new_fact_count: int,
    duplicate_search_count_delta: int,
    consecutive_no_novelty: int,
    forced_pivot: bool,
) -> RoundVerdict:
    """Programmatic exhaustion verdict — not an LLM self-assessment."""
    if new_fact_count > 0 or current_open < previous_open:
        return RoundVerdict.PRODUCTIVE
    if consecutive_no_novelty >= 3 and current_open == 0:
        return RoundVerdict.EXHAUSTED
    if consecutive_no_novelty >= 2 or duplicate_search_count_delta > 0:
        if current_open > 0 and not forced_pivot:
            return RoundVerdict.QUERY_STALE
        if current_open == 0:
            return RoundVerdict.EXHAUSTED
        return RoundVerdict.QUERY_STALE
    if current_open == 0 and previous_open == 0:
        return RoundVerdict.EXHAUSTED
    return RoundVerdict.PRODUCTIVE


def forced_pivot_searches(avenues: Sequence[AvenuePredicate], identifiers: Iterable[str]) -> tuple[dict[str, Any], ...]:
    """Build concrete pivot search proposals for QUERY_STALE rounds."""
    ids = [str(value) for value in identifiers if value]
    pivots: list[dict[str, Any]] = []
    for avenue in open_avenues(avenues):
        source = avenue.required_sources[0] if avenue.required_sources else "Coralogix"
        hint = avenue.pivot_hints[0] if avenue.pivot_hints else avenue.label
        query_bits = [*ids[:2], hint]
        pivots.append({
            "source": source,
            "query": " ".join(str(bit) for bit in query_bits if bit),
            "identifiers": ids,
            "start_date": None,
            "end_date": None,
            "novelty": f"forced pivot for {avenue.predicate_id}",
            "predicate_id": avenue.predicate_id,
        })
    return tuple(pivots[:6])


def exhaustion_certificate(avenues: Sequence[AvenuePredicate], *, round_verdicts: Sequence[str]) -> dict[str, Any]:
    open_ids = [item.predicate_id for item in avenues if item.status == PredicateStatus.OPEN]
    return {
        "all_avenues_closed": not open_ids,
        "open_predicates": open_ids,
        "closed_predicates": {
            item.predicate_id: item.status.value for item in avenues if item.status in CLOSED_STATUSES
        },
        "round_verdicts": list(round_verdicts),
        "ready_to_report": not open_ids and (not round_verdicts or round_verdicts[-1] in {RoundVerdict.EXHAUSTED.value, RoundVerdict.PRODUCTIVE.value}),
    }


def apply_model_avenue_updates(avenues: list[AvenuePredicate], updates: Iterable[Mapping[str, Any]]) -> list[AvenuePredicate]:
    """Allow the model to mark avenues, but never reopen a stronger closed state casually."""
    by_id = {item.predicate_id: item for item in avenues}
    rank = {
        PredicateStatus.OPEN: 0,
        PredicateStatus.EXHAUSTED: 1,
        PredicateStatus.CONTRADICTED: 2,
        PredicateStatus.SUPPORTED: 3,
    }
    for update in updates:
        predicate_id = str(update.get("predicate_id", ""))
        if predicate_id not in by_id:
            continue
        avenue = by_id[predicate_id]
        try:
            new_status = PredicateStatus(str(update.get("status", avenue.status.value)))
        except ValueError:
            continue
        if rank[new_status] >= rank[avenue.status] or new_status == PredicateStatus.CONTRADICTED:
            avenue.status = new_status
        if update.get("supporting_fact_ids") is not None:
            avenue.supporting_fact_ids = tuple(int(value) for value in update.get("supporting_fact_ids", ()))
        if update.get("contradicting_fact_ids") is not None:
            avenue.contradicting_fact_ids = tuple(int(value) for value in update.get("contradicting_fact_ids", ()))
        if update.get("exhaustion_reasons") is not None:
            avenue.exhaustion_reasons = tuple(str(value) for value in update.get("exhaustion_reasons", ()))
    return avenues
