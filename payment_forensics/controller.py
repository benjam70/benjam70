"""Small deterministic controller around the existing payment-forensics prompt.

The LLM may propose facts, searches, hypotheses, and output. This module owns
acceptance of evidence, source coverage, chronology, contradictions, retries,
terminal funds state, and the final completion gate.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
import re
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping

from .safety import normalize_timestamp
from .ledger import PaymentEvent, reconcile_events, reconcile_evidence, validate_provider_refund_response
from .avenues import (
    AvenuePredicate,
    RoundVerdict,
    apply_model_avenue_updates,
    build_avenue_checklist,
    classify_round_progress,
    exhaustion_certificate,
    forced_pivot_searches,
    open_avenues,
    required_triangulations,
    triangulation_gaps,
    update_avenues_from_state,
)


class CoverageStatus(str, Enum):
    NOT_CHECKED = "NOT_CHECKED"
    CHECKED = "CHECKED"
    NA = "N/A"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class SearchResultState(str, Enum):
    RESULTS = "RESULTS"
    NO_RESULT = "NO_RESULT"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class TerminalFundsState(str, Enum):
    CUSTOMER_BANK = "customer bank"
    MERCHANT_SETTLEMENT = "merchant settlement"
    GLOBALE_BALANCE = "Global-e balance"
    GATEWAY_PENDING = "gateway pending state"
    REVERSED = "reversed"
    REFUNDED = "refunded"
    DISPUTE_HELD = "held by dispute process"
    UNKNOWN = "unknown"


class InvestigationPhase(str, Enum):
    INTAKE = "INTAKE"
    IDENTITY = "IDENTITY"
    LIFECYCLE = "LIFECYCLE"
    RECONCILIATION = "RECONCILIATION"
    VERIFICATION = "VERIFICATION"
    DRAFT = "DRAFT"
    VALIDATE = "VALIDATE"
    COMPLETE = "COMPLETE"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class EvidenceItem:
    source: str
    source_type: str
    event_type: str | None = None
    status: str | None = None
    amount: str | None = None
    currency: str | None = None
    timestamp: str | None = None
    provider: str | None = None
    order_id: str | None = None
    payment_id: str | None = None
    refund_id: str | None = None
    psp_reference: str | None = None
    arn: str | None = None
    dispute_id: str | None = None
    raw_fact: str = ""
    source_priority: int = 0
    source_freshness: str | None = None
    confidence_class: str = "CONFIRMED"
    validated: bool = True
    link_ids: tuple[int, ...] = ()
    payment_method: str | None = None
    evidence_role: str = "event"
    component: str | None = None

    @property
    def fingerprint(self) -> str:
        material = "|".join(
            str(value)
            for value in (
                self.event_type,
                self.status,
                self.amount,
                self.currency,
                self.timestamp,
                self.order_id,
                self.payment_id,
                self.refund_id,
                self.psp_reference,
                self.arn,
                self.dispute_id,
                self.raw_fact,
            )
        )
        return sha256(material.encode("utf-8")).hexdigest()

    @property
    def entity_key(self) -> tuple[str | None, str | None, str | None]:
        return (self.order_id, self.payment_id, self.psp_reference)


@dataclass(frozen=True)
class ToolResult:
    source: str
    result_state: SearchResultState
    scoped_to_case: bool
    truncated: bool = False
    error: str | None = None
    stale: bool = False
    facts: tuple[EvidenceItem, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def diagnostics(self) -> str:
        """Combine transport errors and provider warnings for coverage decisions."""
        parts = [self.error or ""]
        parts.extend(str(item) for item in self.warnings)
        return " ".join(part for part in parts if part).strip()

    @property
    def valid_for_coverage(self) -> bool:
        return (
            self.scoped_to_case
            and not self.truncated
            and self.error is None
            and not self.warnings
            and not self.stale
            and (
                self.result_state == SearchResultState.NO_RESULT
                or (self.result_state == SearchResultState.RESULTS and bool(self.facts))
            )
        )


def search_signature(source: str, query: str, identifiers: Iterable[str], start_date: str | None, end_date: str | None) -> str:
    """Fingerprint a search request so an exact repeat can be detected before re-running it."""
    normalized_query = re.sub(r"\s+", " ", query.strip().lower())
    normalized_identifiers = ",".join(sorted(set(identifiers)))
    return "|".join((source.lower(), normalized_identifiers, normalized_query, start_date or "", end_date or ""))


@dataclass(frozen=True)
class SearchRecord:
    source: str
    query: str
    identifiers: tuple[str, ...]
    start_date: str | None
    end_date: str | None
    result_state: SearchResultState
    validated: bool
    truncated: bool
    scoped_to_case: bool
    novelty: str
    error: str | None = None
    query_quality: int = 100
    query_quality_reasons: tuple[str, ...] = ()
    fact_count: int = 0

    @property
    def counts_as_checked(self) -> bool:
        return (
            self.validated
            and not self.truncated
            and self.scoped_to_case
            and self.error is None
            and (
                self.result_state == SearchResultState.NO_RESULT
                or (self.result_state == SearchResultState.RESULTS and self.fact_count > 0)
            )
        )

    @property
    def signature(self) -> str:
        return search_signature(self.source, self.query, self.identifiers, self.start_date, self.end_date)


@dataclass(frozen=True)
class Contradiction:
    left_id: int
    right_id: int
    field: str
    left_value: str | None
    right_value: str | None
    resolution: str = "UNRESOLVED"
    priority_winner: int | None = None


@dataclass(frozen=True)
class RetryLink:
    failed_id: int
    later_id: int
    relation: str
    supersedes: bool


@dataclass(frozen=True)
class GateResult:
    allowed: bool
    reasons: tuple[str, ...] = ()


class CompletionGate:
    """Named gate constants used by callers and tests."""

    IDENTITY = "identity"
    LIFECYCLE = "lifecycle"
    COVERAGE = "coverage"
    CONTRADICTIONS = "contradictions"
    RETRIES = "retries"
    NEGATIVES = "negative_claims"
    TERMINAL_STATE = "terminal_state"
    PROVENANCE = "provenance"


DEFAULT_COVERAGE_SOURCES = (
    "Ticket",
    "Order page",
    "Payment page",
    "Refund page",
    "Tax/FX page",
    "Admin",
    "Gateway",
    "Coralogix",
    "Dispute Center",
    "Settlement evidence",
    "Retry/error history",
)


class CaseController:
    """Own deterministic investigation state while preserving domain reasoning.

    The controller is intentionally provider-neutral. Existing gateway rules
    decide which sources are relevant and how native statuses map to lifecycle
    events; this class only validates and gates the resulting proposals.
    """

    CIRCUIT_BREAKER_THRESHOLD = 2

    def __init__(
        self,
        *,
        case_id: str,
        identifiers: Iterable[str] = (),
        required_sources: Iterable[str] = (),
        required_attachments: Iterable[str] = (),
    ) -> None:
        self.case_id = case_id
        self.identifiers = frozenset(identifier for identifier in identifiers if identifier)
        self.required_sources = tuple(str(source) for source in required_sources if str(source).strip())
        self.evidence: list[EvidenceItem] = []
        self.searches: list[SearchRecord] = []
        self.contradictions: list[Contradiction] = []
        self.retries: list[RetryLink] = []
        self.coverage: dict[str, CoverageStatus] = {
            source: CoverageStatus.NOT_CHECKED for source in DEFAULT_COVERAGE_SOURCES
        }
        for source in self.required_sources:
            self.coverage.setdefault(source, CoverageStatus.NOT_CHECKED)
        self.attachment_coverage: dict[str, CoverageStatus] = {
            str(name): CoverageStatus.NOT_CHECKED for name in required_attachments
        }
        self.attachments: dict[str, dict[str, Any]] = {}
        self.hypotheses: list[dict[str, Any]] = []
        self.negative_claims: list[dict[str, Any]] = []
        self.source_failures: list[dict[str, str]] = []
        self.funds_location = TerminalFundsState.UNKNOWN
        self.terminal_state: str | None = None
        self._terminal_state_unknown_explicit = False
        self._lifecycle_checked = False
        self._approved_fact_ids: set[int] = set()
        self._consecutive_no_novelty = 0
        self._replan_required = False
        self.receipt_relationships: list[dict[str, Any]] = []
        self.ticket_intent: str | None = None
        self.previously_stated_facts: list[str] = []
        self.component_lifecycle: dict[str, dict[str, Any]] = {}
        self.amount_reconciliation: dict[str, Any] | None = None
        self.provider_refund_results: dict[str, dict[str, Any]] = {}
        self.phase = InvestigationPhase.INTAKE
        self.phase_history: list[str] = [self.phase.value]
        self.event_log: list[dict[str, Any]] = []
        self.claim_ledger: list[dict[str, Any]] = []
        self.ticket_understanding: dict[str, Any] = {}
        self.provenance_edges: list[dict[str, Any]] = []
        self.review_records: list[dict[str, Any]] = []
        self._consecutive_source_failures: dict[str, int] = {}
        self.duplicate_search_count = 0
        self.avenues: list[AvenuePredicate] = []
        self.round_verdicts: list[str] = []
        self.inspected_fact_ids: set[int] = set()
        self.pending_read_fact_ids: set[int] = set()
        self.cove_answers: list[dict[str, Any]] = []
        self.verification_bundle: dict[str, Any] = {}
        self.forced_pivot_required = False
        self._previous_open_avenues = 0
        self._duplicate_search_count_at_round_start = 0

    def advance_phase(self, phase: InvestigationPhase | str) -> None:
        """Record a monotonic workflow phase for replay and diagnostics."""
        target = phase if isinstance(phase, InvestigationPhase) else InvestigationPhase(str(phase).upper())
        order = {item: index for index, item in enumerate(InvestigationPhase)}
        if order[target] < order[self.phase]:
            self._log("phase_regression_ignored", attempted=target.value, current=self.phase.value)
            return
        if target != self.phase:
            self.phase = target
            self.phase_history.append(target.value)

    def _log(self, event: str, **details: Any) -> None:
        self.event_log.append({"sequence": len(self.event_log), "event": event, **details})

    def add_provenance_edge(self, relation: str, source: str, target: str, **details: Any) -> None:
        self.provenance_edges.append({"relation": relation, "source": source, "target": target, **details})

    def record_review(self, review: Mapping[str, Any]) -> None:
        self.review_records.append(dict(review))

    def record_attachment(self, name: str, status: CoverageStatus, record: Mapping[str, Any] | None = None) -> None:
        self.attachment_coverage[name] = status
        self.attachments[name] = dict(record or {"name": name, "status": status.value})

    def set_ticket_intent(self, intent: str) -> None:
        self.ticket_intent = intent.strip() or None

    def set_ticket_understanding(self, understanding: Mapping[str, Any]) -> None:
        self.ticket_understanding = dict(understanding)
        self._log("ticket_understood", primary_intent=self.ticket_understanding.get("primary_intent"), requested_artifacts=self.ticket_understanding.get("requested_artifacts", ()))

    def initialize_avenues(self, case_input: str, *, intent: str | None = None) -> list[AvenuePredicate]:
        """Build the mandatory avenue checklist once per case."""
        if not self.avenues:
            self.avenues = build_avenue_checklist(case_input, identifiers=self.identifiers, intent=intent or self.ticket_intent)
            self._previous_open_avenues = len(open_avenues(self.avenues))
            self._log("avenues_initialized", count=len(self.avenues), open=self._previous_open_avenues)
        return self.avenues

    def mark_facts_pending_read(self, fact_ids: Iterable[int]) -> None:
        for fact_id in fact_ids:
            self.pending_read_fact_ids.add(int(fact_id))

    def mark_facts_inspected(self, fact_ids: Iterable[int]) -> None:
        for fact_id in fact_ids:
            value = int(fact_id)
            self.inspected_fact_ids.add(value)
            self.pending_read_fact_ids.discard(value)

    def begin_round_tracking(self) -> None:
        self._previous_open_avenues = len(open_avenues(self.avenues))
        self._duplicate_search_count_at_round_start = self.duplicate_search_count

    def refresh_avenues(self, *, case_input: str = "", model_updates: Iterable[Mapping[str, Any]] = ()) -> RoundVerdict:
        """Update avenues from evidence and classify round progress."""
        coverage = {key: value.value for key, value in self.coverage.items()}
        evidence = [asdict(item) for item in self.evidence]
        searches = [{**asdict(search), "result_state": search.result_state.value} for search in self.searches]
        update_avenues_from_state(
            self.avenues,
            evidence=evidence,
            searches=searches,
            coverage=coverage,
            identifiers=self.identifiers,
            terminal_state=self.terminal_state,
            funds_location=self.funds_location.value if self.funds_location else None,
            hypotheses=self.hypotheses,
            negative_claims=self.negative_claims,
        )
        if model_updates:
            apply_model_avenue_updates(self.avenues, model_updates)
        current_open = len(open_avenues(self.avenues))
        new_fact_count = len(self.pending_read_fact_ids)
        verdict = classify_round_progress(
            previous_open=self._previous_open_avenues,
            current_open=current_open,
            new_fact_count=new_fact_count,
            duplicate_search_count_delta=self.duplicate_search_count - self._duplicate_search_count_at_round_start,
            consecutive_no_novelty=self._consecutive_no_novelty,
            forced_pivot=self.forced_pivot_required,
        )
        self.round_verdicts.append(verdict.value)
        self.forced_pivot_required = verdict == RoundVerdict.QUERY_STALE and current_open > 0
        self._log("avenue_round", verdict=verdict.value, open=current_open, forced_pivot=self.forced_pivot_required)
        return verdict

    def pivot_search_proposals(self) -> tuple[dict[str, Any], ...]:
        return forced_pivot_searches(self.avenues, self.identifiers)

    def exhaustion_certificate(self) -> dict[str, Any]:
        return exhaustion_certificate(self.avenues, round_verdicts=self.round_verdicts)

    def triangulation_reasons(self, case_input: str) -> tuple[str, ...]:
        coverage = {key: value.value for key, value in self.coverage.items()}
        rules = required_triangulations(case_input, self.ticket_intent)
        active = set(self.required_sources) | {
            search.source for search in self.searches
        } | {
            key for key, value in self.coverage.items() if value != CoverageStatus.NOT_CHECKED
        }
        return triangulation_gaps(coverage, rules, available_sources=active)

    def record_previously_stated_facts(self, facts: Iterable[str]) -> None:
        for fact in facts:
            value = " ".join(str(fact).split())
            if value and value not in self.previously_stated_facts:
                self.previously_stated_facts.append(value)

    def record_claims(self, claims: Iterable[Mapping[str, Any]]) -> None:
        """Persist claim-to-evidence links for audit and replay."""
        self.claim_ledger = []
        for index, claim in enumerate(claims):
            if not isinstance(claim, Mapping):
                continue
            self.claim_ledger.append({
                "claim_id": index,
                "text": str(claim.get("text", "")),
                "fact_ids": tuple(int(value) for value in claim.get("fact_ids", ()) if str(value).lstrip("-").isdigit()),
                "field": claim.get("field"),
                "expected_value": claim.get("expected_value"),
            })
        self._log("claims_recorded", count=len(self.claim_ledger))

    def repeated_statement_reasons(self, claims: Iterable[dict]) -> tuple[str, ...]:
        prior = {self._normalize_statement(value) for value in self.previously_stated_facts}
        return tuple(
            f"claim {index} repeats a previously stated fact"
            for index, claim in enumerate(claims)
            if isinstance(claim, dict) and self._normalize_statement(str(claim.get("text", ""))) in prior
        )

    def record_component_state(self, component: str, status: str, *, amount: str | None = None, currency: str | None = None, timestamp: str | None = None, fact_ids: Iterable[int] = ()) -> None:
        normalized_timestamp = normalize_timestamp(timestamp)
        previous = self.component_lifecycle.get(component)
        if previous and previous.get("timestamp") and normalized_timestamp:
            try:
                if datetime.fromisoformat(normalized_timestamp.replace("Z", "+00:00")) < datetime.fromisoformat(str(previous["timestamp"]).replace("Z", "+00:00")):
                    self._log("stale_component_state_ignored", component=component, timestamp=normalized_timestamp)
                    return
            except ValueError:
                pass
        self.component_lifecycle[component] = {
            "component": component,
            "status": status,
            "amount": amount,
            "currency": currency,
            "timestamp": normalized_timestamp,
            "fact_ids": tuple(fact_ids),
        }

    def record_provider_refund_result(self, component: str, response: Mapping[str, Any], *, fact_ids: Iterable[int] = ()) -> dict[str, Any]:
        """Store provider truth and make it authoritative for completion gating."""
        result = validate_provider_refund_response(response)
        result.update({"component": component, "fact_ids": tuple(fact_ids)})
        self.provider_refund_results[component] = result
        self.record_component_state(component, result["status"], fact_ids=fact_ids)
        self._log("provider_refund_validated", component=component, status=result["status"], classification=result["classification"])
        return result

    def reconcile_amounts(self, *, paid_total: str, refund_total: str, transactions: Iterable[Mapping[str, Any]], currency: str, fact_ids: Iterable[int] = ()) -> dict[str, Any]:
        """Reconcile totals without treating an aggregate status as execution proof."""
        paid = self._decimal(paid_total)
        refund = self._decimal(refund_total)
        transaction_rows = [dict(row) for row in transactions]
        refunded_rows = [row for row in transaction_rows if str(row.get("status", "")).upper() in {"REFUNDED", "REFUND", "REFUNDED_COMPLETED"}]
        matching_refund = any(self._decimal(row.get("amount")) == refund for row in refunded_rows)
        unresolved = []
        if paid is None or refund is None:
            unresolved.append("amount is not numeric")
        elif refund > paid:
            unresolved.append("refund exceeds paid total")
        if not matching_refund:
            unresolved.append("refund amount is not mapped to a refunded transaction")
        result = {
            "currency": currency,
            "paid_total": paid_total,
            "refund_total": refund_total,
            "remaining": str(paid - refund) if paid is not None and refund is not None else None,
            "transactions": transaction_rows,
            "status": "RECONCILED" if not unresolved else "UNRESOLVED",
            "reasons": unresolved,
            "fact_ids": tuple(fact_ids),
        }
        self.amount_reconciliation = result
        self.advance_phase(InvestigationPhase.RECONCILIATION)
        self._log("amount_reconciled", status=result["status"], remaining=result["remaining"])
        return result

    def reconcile_authorization_gap(self, *, authorized_total: str, captured_total: str, refunded_total: str, adjustment_amount: str | None = None, currency: str) -> dict[str, Any]:
        """Classify an authorised-but-uncaptured difference without calling it a refund."""
        authorized = self._decimal(authorized_total)
        captured = self._decimal(captured_total)
        refunded = self._decimal(refunded_total)
        adjustment = self._decimal(adjustment_amount) if adjustment_amount is not None else None
        gap = authorized - captured if authorized is not None and captured is not None else None
        full_capture_refund = captured is not None and refunded is not None and captured == refunded
        uncaptured = gap is not None and gap > 0 and full_capture_refund and (adjustment is None or adjustment == gap)
        ledger = reconcile_events((
            PaymentEvent("AUTHORISATION", authorized_total, currency),
            PaymentEvent("CAPTURE", captured_total, currency),
            PaymentEvent("REFUND", refunded_total, currency),
        ), adjustment_amount=adjustment_amount)
        result = {
            "currency": currency, "authorized_total": authorized_total, "captured_total": captured_total,
            "refunded_total": refunded_total, "uncaptured_authorization": str(gap) if uncaptured else None,
            "status": "UNCAPTURED_AUTHORIZATION" if uncaptured else "UNRESOLVED",
            "bank_release_verified": False if uncaptured else None,
            "reasons": ("authorised amount exceeded capture and the captured amount was fully refunded",) if uncaptured else ("authorization gap not safely classifiable",),
            "ledger": ledger,
        }
        self.amount_reconciliation = result
        self.advance_phase(InvestigationPhase.RECONCILIATION)
        self._log("authorization_reconciled", status=result["status"], gap=result["uncaptured_authorization"])
        return result

    def add_evidence(self, item: EvidenceItem) -> int:
        """Append immutable evidence and link exact repeats across sources."""
        item = EvidenceItem(**{**asdict(item), "timestamp": normalize_timestamp(item.timestamp)})
        if not self._fact_matches_case(item):
            item = EvidenceItem(**{**asdict(item), "validated": False})
        index = len(self.evidence)
        links = tuple(i for i, existing in enumerate(self.evidence) if existing.fingerprint == item.fingerprint)
        if links:
            item = EvidenceItem(**{**asdict(item), "link_ids": links})
            for link in links:
                prior = self.evidence[link]
                self.evidence[link] = EvidenceItem(**{**asdict(prior), "link_ids": tuple(sorted(set(prior.link_ids + (index,))))})
        self.evidence.append(item)
        self._log("evidence_added", fact_id=index, fingerprint=item.fingerprint, source=item.source)
        self.add_provenance_edge("evidence_from_source", f"source:{item.source}", f"fact:{index}", fingerprint=item.fingerprint)
        if item.component:
            self.record_component_state(
                item.component,
                item.status or item.event_type or "UNKNOWN",
                amount=item.amount,
                currency=item.currency,
                timestamp=item.timestamp,
                fact_ids=(index,),
            )
        if item.validated:
            self._approved_fact_ids.add(index)
            self.mark_facts_pending_read((index,))
        self._detect_contradictions(index)
        self._update_receipt_relationships()
        return index

    def circuit_breaker_open(self, source: str, *, threshold: int | None = None) -> bool:
        """True once a source has failed consecutively enough times to stop retrying it this case.

        Mirrors the circuit-breaker pattern: past the threshold, the caller should
        stop spending real tool calls on this source and record a Data Gap instead,
        rather than retrying a call that has already failed repeatedly in a row.
        """
        limit = self.CIRCUIT_BREAKER_THRESHOLD if threshold is None else threshold
        return self._consecutive_source_failures.get(source, 0) >= limit

    def find_prior_search(self, *, source: str, query: str, identifiers: Iterable[str], start_date: str | None = None, end_date: str | None = None) -> int | None:
        """Return the index of an earlier search with an identical fingerprint, if any.

        Lets a caller check before spending a real tool call whether this exact
        search (same source, query, identifiers, and window) already ran this case.
        """
        signature = search_signature(source, query, identifiers, start_date, end_date)
        for index, existing in enumerate(self.searches):
            if existing.signature == signature:
                return index
        return None

    def note_skipped_search(self, source: str, reason: str, *, is_duplicate: bool = False) -> None:
        """Record that a proposed search was never executed, without touching coverage.

        Use this for a circuit-breaker-open or exact-duplicate search that a caller
        decided not to spend a real tool call on. Unlike `add_tool_result`, this never
        writes to `coverage`: a skip is not a new attempt and must not be able to
        overwrite an earlier genuine CHECKED or FAILED status for the same source.
        """
        if is_duplicate:
            self.duplicate_search_count += 1
        self._log("search_skipped", source=source, reason=reason, is_duplicate=is_duplicate)

    def add_tool_result(self, result: ToolResult, *, query: str, identifiers: Iterable[str], start_date: str | None = None, end_date: str | None = None, novelty: str = "new event", query_quality: int = 100, query_quality_reasons: Iterable[str] = ()) -> tuple[int, ...]:
        """Validate a tool result, update coverage, and admit only valid facts."""
        if self.find_prior_search(source=result.source, query=query, identifiers=identifiers, start_date=start_date, end_date=end_date) is not None:
            self.duplicate_search_count += 1
            self._log("duplicate_search_detected", source=result.source, query=query, duplicate_search_count=self.duplicate_search_count)
        error_text = (result.error or "").casefold()
        error_text = result.diagnostics.casefold()
        coverage_gap = any(marker in error_text for marker in ("missing data", "missingdata", "missing archive", "archive data", "rehydrat", "incomplete data"))
        if result.result_state in {SearchResultState.PARTIAL, SearchResultState.FAILED} or not result.valid_for_coverage or coverage_gap:
            status = CoverageStatus.PARTIAL if result.result_state == SearchResultState.PARTIAL else CoverageStatus.FAILED
            if coverage_gap or result.warnings:
                status = CoverageStatus.PARTIAL
            self.coverage[result.source] = status
            if result.error:
                self.source_failures.append({"source": result.source, "error": result.error})
            validated = False
        else:
            self.coverage[result.source] = CoverageStatus.CHECKED
            validated = True
        if validated:
            self._consecutive_source_failures[result.source] = 0
        else:
            failures = self._consecutive_source_failures.get(result.source, 0) + 1
            self._consecutive_source_failures[result.source] = failures
            if failures == self.CIRCUIT_BREAKER_THRESHOLD:
                self._log("circuit_breaker_opened", source=result.source, consecutive_failures=failures)
        record = SearchRecord(
            source=result.source,
            query=query,
            identifiers=tuple(identifiers),
            start_date=start_date,
            end_date=end_date,
            result_state=result.result_state,
            validated=validated,
            truncated=result.truncated,
            scoped_to_case=result.scoped_to_case,
            novelty=novelty,
            error=result.diagnostics or None,
            query_quality=query_quality,
            query_quality_reasons=tuple(query_quality_reasons),
            fact_count=len(result.facts),
        )
        self.searches.append(record)
        self._log("tool_result", source=result.source, result_state=result.result_state.value, fact_count=len(result.facts), validated=validated)
        prior_fingerprints = {item.fingerprint for item in self.evidence}
        admitted: list[int] = []
        if validated:
            for fact in result.facts:
                if fact.source == result.source and fact.validated and self._fact_matches_case(fact):
                    admitted.append(self.add_evidence(fact))
        for fact_id in admitted:
            self.add_provenance_edge("fact_retrieved_by", f"fact:{fact_id}", f"search:{len(self.searches) - 1}")
        novel = any(self.evidence[index].fingerprint not in prior_fingerprints for index in admitted)
        if novel:
            self._consecutive_no_novelty = 0
        else:
            self._consecutive_no_novelty += 1
            if self._consecutive_no_novelty >= 3:
                self._replan_required = True
        if admitted:
            self.mark_facts_pending_read(admitted)
        return tuple(admitted)

    def accept_replan(self, replanned: bool) -> None:
        """Clear a loop block only when the LLM explicitly submits a re-plan."""
        if replanned and self._replan_required:
            self._replan_required = False
            self._consecutive_no_novelty = 0

    def mark_source(self, source: str, status: CoverageStatus) -> None:
        """Mark an irrelevant or explicitly inaccessible source without hiding why."""
        self.coverage[source] = status

    def add_hypothesis(self, label: str, supporting: Iterable[int] = (), contradicting: Iterable[int] = (), *, disconfirm_searched: bool = False) -> None:
        self.hypotheses.append({
            "label": label,
            "supporting": tuple(supporting),
            "contradicting": tuple(contradicting),
            "status": "active",
            "disconfirm_searched": bool(disconfirm_searched or tuple(contradicting)),
        })

    def mark_hypothesis_disconfirmed(self, label: str) -> None:
        for hypothesis in self.hypotheses:
            if hypothesis.get("label") == label:
                hypothesis["disconfirm_searched"] = True
                hypothesis["status"] = "tested"

    def record_negative_claim(self, claim: str, *, source: str, identifiers: Iterable[str], adequate_window: bool, no_result_searches: int = 1, later_event_checked: bool = False) -> bool:
        identifiers_tuple = tuple(identifier for identifier in identifiers if identifier)
        record = {
            "claim": claim,
            "source": source,
            "identifiers": identifiers_tuple,
            "adequate_window": adequate_window,
            "no_result_searches": no_result_searches,
            "later_event_checked": later_event_checked,
            "proven_absence": False,
        }
        allowed = (
            self.coverage.get(source) == CoverageStatus.CHECKED
            and len(set(identifiers_tuple)) >= 2
            and adequate_window
            and no_result_searches >= 1
            and later_event_checked
            and not any(search.result_state in {SearchResultState.PARTIAL, SearchResultState.FAILED} for search in self.searches if search.source == source)
        )
        record["proven_absence"] = allowed
        existing = next((item for item in self.negative_claims if item["claim"] == claim and item["source"] == source), None)
        if existing is None:
            self.negative_claims.append(record)
        else:
            existing.update(record)
        return allowed

    def link_retry(self, failed_id: int, later_id: int, *, relation: str = "same payment intent") -> bool:
        failed = self.evidence[failed_id]
        later = self.evidence[later_id]
        same_entity = self._same_entity(failed, later)
        later_success = (later.status or "").upper() in {"SUCCESS", "SUCCEEDED", "CAPTURED", "REFUNDED", "SETTLED", "COMPLETED"}
        supersedes = same_entity and later_success and self._timestamp_value(later.timestamp) >= self._timestamp_value(failed.timestamp)
        self.retries.append(RetryLink(failed_id, later_id, relation, supersedes))
        return supersedes

    def resolve_contradiction(self, contradiction_id: int, resolution: str, *, priority_winner: int | None = None) -> None:
        """Record an explicit resolution instead of silently dropping a conflict."""
        contradiction = self.contradictions[contradiction_id]
        self.contradictions[contradiction_id] = Contradiction(
            contradiction.left_id,
            contradiction.right_id,
            contradiction.field,
            contradiction.left_value,
            contradiction.right_value,
            resolution=resolution,
            priority_winner=priority_winner,
        )

    def set_terminal_state(self, state: str, *, funds_location: TerminalFundsState, lifecycle_checked: bool = True) -> None:
        self.terminal_state = state
        self.funds_location = funds_location
        self._terminal_state_unknown_explicit = state.upper() == "UNKNOWN" or funds_location == TerminalFundsState.UNKNOWN
        self._lifecycle_checked = lifecycle_checked
        self.advance_phase(InvestigationPhase.VERIFICATION)
        self._log("terminal_state", state=state, funds_location=funds_location.value)

    def approve_output_facts(self, fact_ids: Iterable[int]) -> tuple[int, ...]:
        approved = tuple(fact_id for fact_id in fact_ids if fact_id in self._approved_fact_ids)
        self._approved_fact_ids.intersection_update(approved)
        return approved

    def validate_output_facts(self, fact_ids: Iterable[int]) -> GateResult:
        requested = tuple(fact_ids)
        invalid = tuple(str(fact_id) for fact_id in requested if fact_id not in self._approved_fact_ids)
        return GateResult(not invalid, tuple(f"unapproved fact: {fact_id}" for fact_id in invalid))

    def completion_gate(self, *, identity_established: bool, relevant_sources: Iterable[str], lifecycle_checked: bool | None = None, retries_required: bool = False, retries_checked: bool = True, contradiction_ids_resolved: Iterable[int] = (), intent_established: bool = True, case_input: str = "", require_avenue_exhaustion: bool = True) -> GateResult:
        reasons: list[str] = []
        if self.ticket_intent is not None and not intent_established:
            reasons.append("ticket intent not established")
        if not identity_established:
            reasons.append(f"{CompletionGate.IDENTITY} not established")
        if not (self._lifecycle_checked if lifecycle_checked is None else lifecycle_checked):
            reasons.append(f"{CompletionGate.LIFECYCLE} not checked")
        for source in relevant_sources:
            if self.coverage.get(source) not in {CoverageStatus.CHECKED, CoverageStatus.NA}:
                reasons.append(f"{CompletionGate.COVERAGE} incomplete: {source}={self.coverage.get(source, CoverageStatus.NOT_CHECKED).value}")
        for name, status in self.attachment_coverage.items():
            if status not in {CoverageStatus.CHECKED, CoverageStatus.NA}:
                reasons.append(f"attachment coverage incomplete: {name}={status.value}")
        unresolved = [c for i, c in enumerate(self.contradictions) if i not in set(contradiction_ids_resolved) and c.resolution == "UNRESOLVED"]
        if unresolved:
            reasons.append(f"{CompletionGate.CONTRADICTIONS} unresolved")
        if retries_required and not retries_checked:
            reasons.append(f"{CompletionGate.RETRIES} not checked")
        if any(not claim["proven_absence"] for claim in self.negative_claims):
            reasons.append(f"{CompletionGate.NEGATIVES} insufficient coverage")
        if self._replan_required:
            reasons.append("search novelty exhausted: explicit re-plan required")
        if self.component_lifecycle and any(str(item.get("status", "")).upper() in {"FAILED", "REJECTED", "UNKNOWN", "UNRESOLVED"} for item in self.component_lifecycle.values()):
            reasons.append("component lifecycle unresolved")
        if self.provider_refund_results and any(str(item.get("status", "")).upper() != "REFUNDED" for item in self.provider_refund_results.values()):
            reasons.append("provider refund response unresolved")
        if self.amount_reconciliation and self.amount_reconciliation.get("status") not in {"RECONCILED", "UNCAPTURED_AUTHORIZATION"}:
            reasons.append("amount reconciliation unresolved")
        if self.terminal_state is None or (self.funds_location == TerminalFundsState.UNKNOWN and not self._terminal_state_unknown_explicit):
            reasons.append(f"{CompletionGate.TERMINAL_STATE} not established")
        if not self._approved_fact_ids and self.evidence:
            reasons.append(f"{CompletionGate.PROVENANCE} missing")
        if require_avenue_exhaustion and self.avenues:
            still_open = [item.predicate_id for item in open_avenues(self.avenues)]
            if still_open:
                reasons.append(f"avenues still open: {', '.join(still_open)}")
            if self.forced_pivot_required:
                reasons.append("query stale: forced pivot required before completion")
        if case_input:
            reasons.extend(self.triangulation_reasons(case_input))
        active_without_disconfirm = [
            str(item.get("label"))
            for item in self.hypotheses
            if str(item.get("status", "active")) == "active" and not item.get("disconfirm_searched") and not item.get("contradicting")
        ]
        if active_without_disconfirm:
            reasons.append(f"hypotheses lack disconfirm search: {', '.join(active_without_disconfirm)}")
        if self.avenues and self.pending_read_fact_ids:
            reasons.append(f"read-gate: uninspected facts {sorted(self.pending_read_fact_ids)}")
        if self.verification_bundle and not self.verification_bundle.get("allowed", True):
            reasons.extend(f"accuracy: {reason}" for reason in self.verification_bundle.get("reasons", ()))
        return GateResult(not reasons, tuple(reasons))

    def snapshot(self) -> dict[str, Any]:
        derived_ledger = reconcile_evidence([asdict(item) for item in self.evidence], self._approved_fact_ids)
        return {
            "case_id": self.case_id,
            "identifiers": sorted(self.identifiers),
            "required_sources": list(self.required_sources),
            "evidence": [asdict(item) for item in self.evidence],
            "searches": [{**asdict(search), "result_state": search.result_state.value} for search in self.searches],
            "coverage": {key: value.value for key, value in self.coverage.items()},
            "attachment_coverage": {key: value.value for key, value in self.attachment_coverage.items()},
            "attachments": self.attachments,
            "contradictions": [asdict(item) for item in self.contradictions],
            "retries": [asdict(item) for item in self.retries],
            "hypotheses": self.hypotheses,
            "negative_claims": self.negative_claims,
            "source_failures": self.source_failures,
            "funds_location": self.funds_location.value,
            "terminal_state": self.terminal_state,
            "terminal_state_unknown_explicit": self._terminal_state_unknown_explicit,
            "approved_fact_ids": sorted(self._approved_fact_ids),
            "consecutive_no_novelty": self._consecutive_no_novelty,
            "replan_required": self._replan_required,
            "receipt_relationships": list(self.receipt_relationships),
            "ticket_intent": self.ticket_intent,
            "ticket_understanding": dict(self.ticket_understanding),
            "previously_stated_facts": list(self.previously_stated_facts),
            "component_lifecycle": dict(self.component_lifecycle),
            "provider_refund_results": dict(self.provider_refund_results),
            "amount_reconciliation": self.amount_reconciliation,
            "derived_ledger": derived_ledger,
            "claim_ledger": list(self.claim_ledger),
            "provenance_edges": list(self.provenance_edges),
            "review_records": list(self.review_records),
            "phase": self.phase.value,
            "phase_history": list(self.phase_history),
            "event_log": list(self.event_log),
            "search_signatures": [search.signature for search in self.searches],
            "consecutive_source_failures": dict(self._consecutive_source_failures),
            "duplicate_search_count": self.duplicate_search_count,
            "avenues": [item.as_dict() for item in self.avenues],
            "round_verdicts": list(self.round_verdicts),
            "inspected_fact_ids": sorted(self.inspected_fact_ids),
            "pending_read_fact_ids": sorted(self.pending_read_fact_ids),
            "cove_answers": list(self.cove_answers),
            "verification_bundle": dict(self.verification_bundle),
            "forced_pivot_required": self.forced_pivot_required,
            "exhaustion_certificate": self.exhaustion_certificate() if self.avenues else {},
        }

    @classmethod
    def from_snapshot(cls, snapshot: Mapping[str, Any]) -> "CaseController":
        """Restore controller state for resumable investigations."""
        controller = cls(case_id=str(snapshot["case_id"]), identifiers=snapshot.get("identifiers", ()), required_sources=snapshot.get("required_sources", ()), required_attachments=snapshot.get("attachment_coverage", {}).keys())
        controller.evidence = [EvidenceItem(**{**item, "link_ids": tuple(item.get("link_ids", ()))}) for item in snapshot.get("evidence", ())]
        controller._approved_fact_ids = set(int(value) for value in snapshot.get("approved_fact_ids", ()))
        controller.coverage = {key: CoverageStatus(value) for key, value in snapshot.get("coverage", {}).items()}
        controller.attachment_coverage = {key: CoverageStatus(value) for key, value in snapshot.get("attachment_coverage", {}).items()}
        controller.attachments = dict(snapshot.get("attachments", {}))
        controller.hypotheses = list(snapshot.get("hypotheses", ()))
        controller.negative_claims = list(snapshot.get("negative_claims", ()))
        controller.source_failures = list(snapshot.get("source_failures", ()))
        controller.funds_location = TerminalFundsState(snapshot.get("funds_location", TerminalFundsState.UNKNOWN.value))
        controller.terminal_state = snapshot.get("terminal_state")
        controller._terminal_state_unknown_explicit = bool(snapshot.get("terminal_state_unknown_explicit", False))
        controller._lifecycle_checked = controller.terminal_state is not None
        controller.ticket_intent = snapshot.get("ticket_intent")
        controller.ticket_understanding = dict(snapshot.get("ticket_understanding", {}))
        controller.previously_stated_facts = list(snapshot.get("previously_stated_facts", ()))
        controller.component_lifecycle = dict(snapshot.get("component_lifecycle", {}))
        controller.provider_refund_results = dict(snapshot.get("provider_refund_results", {}))
        controller.amount_reconciliation = snapshot.get("amount_reconciliation")
        controller.phase = InvestigationPhase(snapshot.get("phase", InvestigationPhase.INTAKE.value))
        controller.phase_history = list(snapshot.get("phase_history", (controller.phase.value,)))
        controller.event_log = list(snapshot.get("event_log", ()))
        controller.claim_ledger = list(snapshot.get("claim_ledger", ()))
        controller.provenance_edges = list(snapshot.get("provenance_edges", ()))
        controller.review_records = list(snapshot.get("review_records", ()))
        controller.searches = [
            SearchRecord(**{**search, "result_state": SearchResultState(search["result_state"])})
            for search in snapshot.get("searches", ())
        ]
        controller._consecutive_no_novelty = int(snapshot.get("consecutive_no_novelty", 0))
        controller._replan_required = bool(snapshot.get("replan_required", False))
        controller._consecutive_source_failures = dict(snapshot.get("consecutive_source_failures", {}))
        controller.duplicate_search_count = int(snapshot.get("duplicate_search_count", 0))
        controller.avenues = [AvenuePredicate.from_dict(item) for item in snapshot.get("avenues", ())]
        controller.round_verdicts = list(snapshot.get("round_verdicts", ()))
        controller.inspected_fact_ids = set(int(value) for value in snapshot.get("inspected_fact_ids", ()))
        controller.pending_read_fact_ids = set(int(value) for value in snapshot.get("pending_read_fact_ids", ()))
        controller.cove_answers = list(snapshot.get("cove_answers", ()))
        controller.verification_bundle = dict(snapshot.get("verification_bundle", {}))
        controller.forced_pivot_required = bool(snapshot.get("forced_pivot_required", False))
        controller._previous_open_avenues = len(open_avenues(controller.avenues))
        return controller

    def _update_receipt_relationships(self) -> None:
        receipts = [(i, item) for i, item in enumerate(self.evidence) if item.evidence_role in {"customer_receipt", "bank_receipt"}]
        payments = [(i, item) for i, item in enumerate(self.evidence) if item.evidence_role == "event" and item.event_type in {"AUTHORISATION", "CAPTURE", "REFUND", "CANCEL_OR_REFUND", "VOID", "PAYMENT", "SETTLEMENT"}]
        relationships: list[dict[str, Any]] = []
        for receipt_id, receipt in receipts:
            for payment_id, payment in payments:
                if not self._same_entity(receipt, payment) and receipt.order_id and payment.order_id and receipt.order_id != payment.order_id:
                    continue
                reasons: list[str] = []
                if receipt.amount and payment.amount and receipt.amount != payment.amount:
                    reasons.append("amount mismatch")
                if receipt.currency and payment.currency and receipt.currency.upper() != payment.currency.upper():
                    reasons.append("currency mismatch")
                if receipt.payment_method and payment.payment_method and receipt.payment_method.lower() != payment.payment_method.lower():
                    reasons.append("payment method mismatch")
                relationships.append({"receipt_id": receipt_id, "payment_id": payment_id, "status": "MISMATCHED" if reasons else "MATCHED", "reasons": reasons})
        self.receipt_relationships = relationships

    def _fact_matches_case(self, item: EvidenceItem) -> bool:
        if not self.identifiers:
            return True
        values = {value for value in item.__dict__.values() if isinstance(value, str)}
        return bool(values & self.identifiers)

    @staticmethod
    def _decimal(value: Any) -> Decimal | None:
        try:
            return Decimal(str(value)) if value is not None else None
        except (InvalidOperation, ValueError):
            return None

    @staticmethod
    def _normalize_statement(value: str) -> str:
        return re.sub(r"\W+", " ", value.lower()).strip()

    @staticmethod
    def _same_entity(left: EvidenceItem, right: EvidenceItem) -> bool:
        left_values = {left.order_id, left.payment_id, left.psp_reference, left.refund_id, left.dispute_id} - {None}
        right_values = {right.order_id, right.payment_id, right.psp_reference, right.refund_id, right.dispute_id} - {None}
        return bool(left_values & right_values)

    def _detect_contradictions(self, new_id: int) -> None:
        current = self.evidence[new_id]
        if not current.entity_key or current.entity_key == (None, None, None):
            return
        for prior_id, prior in enumerate(self.evidence[:-1]):
            if not self._same_entity(prior, current):
                continue
            if (
                prior.event_type == current.event_type == "CAPTURE"
                and prior.status == current.status
                and prior.amount == current.amount
                and prior.currency == current.currency
                and prior.timestamp != current.timestamp
            ):
                self.contradictions.append(
                    Contradiction(
                        prior_id,
                        new_id,
                        "duplicate_event",
                        prior.event_type,
                        current.event_type,
                    )
                )
            for field_name in ("status", "amount", "currency", "psp_reference", "refund_id", "dispute_id"):
                left = getattr(prior, field_name)
                right = getattr(current, field_name)
                if left and right and left != right:
                    winner = prior.source_priority if prior.source_priority != current.source_priority else None
                    self.contradictions.append(Contradiction(prior_id, new_id, field_name, left, right, priority_winner=winner))

    @staticmethod
    def _timestamp_value(value: str | None) -> float:
        if not value:
            return float("-inf")
        normalized = value.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.timestamp()
        except ValueError:
            return float("-inf")
