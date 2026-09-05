"""End-to-end hybrid orchestration for payment-forensics investigations.

The model proposes structured work. The controller validates every proposal,
executes searches through an injected adapter, and alone decides completion.
No provider-specific behavior is invented here; gateway rules remain in the
existing payment-forensics skill and tool adapters.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Any, Callable, Iterable, Mapping, Protocol

from .controller import (
    CaseController,
    CoverageStatus,
    EvidenceItem,
    GateResult,
    SearchResultState,
    TerminalFundsState,
    ToolResult,
    InvestigationPhase,
)
from .output_validator import validate_claims, validate_output
from .vale_linter import run_vale
from .audit import build_audit_record
from .coralogix_search import alternate_queries, assess_query, result_quality, time_sliced_queries
from .attachments import extract_admin_capture_facts, inspect_attachment
from .persona_eval import validate_persona_turn
from .humanize import validate_humanized_draft
from .security import screen_external_content, trust_context
from .telemetry import TelemetryEvent, query_digest, telemetry_run_id
from .request_understanding import understand_ticket, unanswered_after_draft, validate_ticket_answer
from .persona_contract import load_persona_contract, persona_hash
from .review import ReviewRecord
from .arn import assess_arn_availability

PERSONA_VERSION = load_persona_contract()["version"]
PERSONA_HASH = persona_hash()
INSTRUCTION_POLICY_VERSION = "1.1.0"


class ProposalModel(Protocol):
    """LLM adapter contract. Implementations may call any approved LLM."""

    def propose(self, context: Mapping[str, Any]) -> Mapping[str, Any]: ...

    def render(self, mode: str, context: Mapping[str, Any], fact_ids: tuple[int, ...]) -> str: ...


class SearchExecutor(Protocol):
    """Adapter contract for existing Admin, gateway, Coralogix, and other tools."""

    def search(self, request: "SearchRequest") -> ToolResult: ...


@dataclass(frozen=True)
class SearchRequest:
    source: str
    query: str
    identifiers: tuple[str, ...]
    start_date: str | None = None
    end_date: str | None = None
    query_language: str = "lucene"


@dataclass(frozen=True)
class EngineResult:
    status: str
    mode: str | None
    output: str | None
    gate: GateResult
    rounds: int
    state: dict[str, Any]
    audit: dict[str, Any] | None = None


ORDER_ID = re.compile(r"\bGE\d{8,}[A-Z]{2}\b", re.IGNORECASE)
PSP_ID = re.compile(r"\b(?:pi|ch|re|du|ca|or|tr|pay|txn|tx)_[A-Za-z0-9_-]+\b")
ARN = re.compile(r"\b\d{20,}")


def _infer_ticket_intent(case_input: str) -> str:
    """Choose a minimal deterministic intent before the model reasons."""
    lowered = case_input.lower()
    if "refund" in lowered:
        return "refund_status"
    if "chargeback" in lowered or "dispute" in lowered:
        return "dispute_status"
    if "charged" in lowered or "debit" in lowered or "payment" in lowered:
        return "payment_status"
    return "payment_investigation"


class HybridEngine:
    """Run case input through extraction, model proposals, tools, and gates."""

    def __init__(self, model: ProposalModel, search_executor: SearchExecutor, *, max_rounds: int = 8, required_sources: Iterable[str] = ("Coralogix",), humanizer: Callable[[str, str, Mapping[str, Any]], str] | None = None) -> None:
        if max_rounds < 1:
            raise ValueError("max_rounds must be positive")
        self.model = model
        self.search_executor = search_executor
        self.max_rounds = max_rounds
        self.required_sources = tuple(dict.fromkeys(str(source) for source in required_sources if str(source).strip()))
        self.humanizer = humanizer

    def investigate(self, case_input: str, attachments: Iterable[Any] = (), thread_history: Iterable[Any] = (), controller_snapshot: Mapping[str, Any] | None = None) -> EngineResult:
        identifiers = extract_identifiers(case_input)
        ticket_understanding = understand_ticket(case_input, thread_history)
        attachment_records = tuple(inspect_attachment(item, case_input=case_input) for item in attachments)
        trust_findings = screen_external_content(case_input, source="case input")
        for record in attachment_records:
            trust_findings += screen_external_content(str(record.as_dict()), source=record.name)
        required_sources = self._source_plan(case_input)
        required_attachments = tuple(record.name for record in attachment_records)
        controller = CaseController(case_id=_case_id(identifiers, case_input), identifiers=identifiers,
                                    required_sources=required_sources, required_attachments=required_attachments)
        if controller_snapshot is not None:
            controller = CaseController.from_snapshot(controller_snapshot)
        for record in attachment_records:
            status = CoverageStatus.CHECKED if record.status == "INSPECTED" else CoverageStatus.FAILED
            controller.record_attachment(record.name, status, record.as_dict())
            for fact in record.facts:
                controller.add_evidence(fact)
        for fact in extract_admin_capture_facts(case_input):
            controller.add_evidence(fact)
        arn_assessment = assess_arn_availability(case_input, [item.__dict__ for item in controller.evidence])
        controller.set_ticket_intent(ticket_understanding.primary_intent)
        controller.set_ticket_understanding(ticket_understanding.as_dict())
        controller.advance_phase(InvestigationPhase.IDENTITY)
        run_id = telemetry_run_id(controller.case_id, case_input)
        context: dict[str, Any] = {
            "case_input": case_input,
            "identifiers": sorted(identifiers),
            "controller_state": controller.snapshot(),
            "required_sources": required_sources,
            "attachments": [record.as_dict() for record in attachment_records],
            "instruction": (
                "Propose structured searches and facts. Do not declare completion until the controller gate passes. "
                "For split-tender payments, always report each tender separately in component_lifecycle, including "
                "its amount, currency, status, date, and supporting fact IDs. An aggregate Admin status never proves "
                "that every tender was refunded. Record amount_reconciliation separately and treat any failed, rejected, "
                "or unproven component as unresolved. Follow exact refund IDs, transaction IDs, and provider response "
                "errors into the relevant logs before concluding that a refund is complete."
            ),
            "dudley_persona_version": PERSONA_VERSION,
            "dudley_persona_hash": PERSONA_HASH,
            "instruction_policy_version": INSTRUCTION_POLICY_VERSION,
            "ticket_understanding": ticket_understanding.as_dict(),
            "thread_history": [str(item.get("text", "")) if isinstance(item, Mapping) else str(item) for item in thread_history],
            **trust_context(trust_findings),
        }
        last_gate = GateResult(False, ("investigation has not started",))

        for round_number in range(1, self.max_rounds + 1):
            before = controller.snapshot()
            context["controller_state"] = controller.snapshot()
            proposal = self._safe_proposal(self.model.propose(context))
            if proposal.get("ticket_intent"):
                controller.set_ticket_intent(str(proposal["ticket_intent"]))
            controller.record_previously_stated_facts(proposal.get("previously_stated_facts", ()))
            for component in proposal.get("component_lifecycle", ()):
                if isinstance(component, Mapping) and component.get("component"):
                    controller.record_component_state(
                        str(component["component"]), str(component.get("status", "UNKNOWN")),
                        amount=component.get("amount"), currency=component.get("currency"),
                        timestamp=component.get("timestamp"), fact_ids=component.get("fact_ids", ()),
                    )
            for provider_result in proposal.get("provider_refund_results", ()):
                if isinstance(provider_result, Mapping) and provider_result.get("component") and isinstance(provider_result.get("response"), Mapping):
                    controller.record_provider_refund_result(
                        str(provider_result["component"]), provider_result["response"],
                        fact_ids=provider_result.get("fact_ids", ()),
                    )
            amount_data = proposal.get("amount_reconciliation")
            if isinstance(amount_data, Mapping):
                controller.reconcile_amounts(
                    paid_total=str(amount_data.get("paid_total")),
                    refund_total=str(amount_data.get("refund_total")),
                    transactions=amount_data.get("transactions", ()),
                    currency=str(amount_data.get("currency", "")),
                    fact_ids=amount_data.get("fact_ids", ()),
                )
            authorization_data = proposal.get("authorization_reconciliation")
            if isinstance(authorization_data, Mapping):
                controller.reconcile_authorization_gap(
                    authorized_total=str(authorization_data.get("authorized_total")),
                    captured_total=str(authorization_data.get("captured_total")),
                    refunded_total=str(authorization_data.get("refunded_total")),
                    adjustment_amount=authorization_data.get("adjustment_amount"),
                    currency=str(authorization_data.get("currency", "")),
                )
            controller.accept_replan(bool(proposal.get("replan", False)))
            self._apply_hypotheses(controller, proposal.get("hypotheses", ()))
            self._run_searches(controller, proposal.get("searches", ()))
            controller.advance_phase(InvestigationPhase.LIFECYCLE)
            self._apply_retries(controller, proposal.get("retries", ()))
            self._apply_terminal_state(controller, proposal.get("terminal_state"))
            self._apply_negative_claims(controller, proposal.get("negative_claims", ()))
            after = controller.snapshot()
            context["what_changed"] = self._what_changed(before, after)

            # The model may add relevant sources, but it cannot remove the
            # deterministic source plan derived by the engine.
            relevant_sources = tuple(dict.fromkeys((*required_sources, *proposal.get("relevant_sources", ()))))
            last_gate = controller.completion_gate(
                identity_established=bool(proposal.get("identity_established", bool(identifiers))),
                relevant_sources=relevant_sources,
                lifecycle_checked=proposal.get("lifecycle_checked"),
                retries_required=bool(proposal.get("retries_required", False)),
                retries_checked=bool(proposal.get("retries_checked", True)),
                contradiction_ids_resolved=proposal.get("contradiction_ids_resolved", ()),
                intent_established=bool(proposal.get("ticket_intent_established", True)),
            )
            if last_gate.allowed:
                controller.advance_phase(InvestigationPhase.DRAFT)
            context["what_changed"]["remaining_open_questions"] = list(last_gate.reasons)
            if not proposal.get("complete", False) or not last_gate.allowed:
                context["controller_feedback"] = {
                    "status": "continue investigation",
                    "reasons": last_gate.reasons,
                    "required_sources": required_sources,
                    "attachments": [record.name for record in attachment_records],
                }
                continue

            mode = str(proposal.get("mode", "A")).upper()
            fact_ids = tuple(int(item) for item in proposal.get("fact_ids", ()))
            facts_gate = controller.validate_output_facts(fact_ids)
            if not facts_gate.allowed:
                last_gate = facts_gate
                context["controller_feedback"] = {"status": "reject output facts", "reasons": facts_gate.reasons}
                continue
            claims = tuple(proposal.get("claims", ()))
            controller.record_claims(claims)
            snapshot = controller.snapshot()
            repeated_claims = controller.repeated_statement_reasons(claims)
            if repeated_claims:
                last_gate = GateResult(False, repeated_claims)
                context["controller_feedback"] = {"status": "reject repeated claims", "reasons": repeated_claims}
                continue
            claims_gate = validate_claims(claims, snapshot["approved_fact_ids"], snapshot["evidence"])
            if not claims_gate.allowed:
                last_gate = GateResult(False, claims_gate.reasons)
                context["controller_feedback"] = {"status": "reject unsupported claims", "reasons": claims_gate.reasons}
                continue
            if mode in {"B", "C"}:
                approved_ids = set(snapshot["approved_fact_ids"])
                render_context = {
                    "mode": mode,
                    "approved_facts": [item for index, item in enumerate(snapshot["evidence"]) if index in approved_ids],
                    "approved_claims": claims,
                    "claim_ledger": snapshot.get("claim_ledger", ()),
                    "derived_ledger": snapshot.get("derived_ledger", {}),
                    "what_changed": context.get("what_changed", {}),
                    "approved_conclusion": proposal.get("conclusion"),
                    "ticket_understanding": ticket_understanding.as_dict(),
                    "arn_assessment": arn_assessment,
                    "style_rules": proposal.get("style_rules", ()),
                    "voice_profile": (
                        "Dudley is an observant, candid, calm second pair of eyes. "
                        "Use direct judgment and natural cadence. When new evidence arrives, say what changed "
                        "and what remains open. Preserve every fact and uncertainty. Avoid repeated catchphrases."
                        " Answer the explicit request first. For Mode B, omit already-known facts and discrepancies "
                        "that do not change the next action. Keep only the evidence needed to support the finding."
                    ),
                }
            else:
                render_context = {**context, "controller_state": snapshot, "approved_claims": claims}
            output = self.model.render(mode, render_context, fact_ids)
            if mode in {"B", "C"} and self.humanizer is not None:
                rewritten = self.humanizer(mode, output, render_context)
                preservation = validate_humanized_draft(output, rewritten)
                if not preservation.allowed:
                    last_gate = GateResult(False, tuple(f"Humanizer: {reason}" for reason in preservation.reasons))
                    context["controller_feedback"] = {"status": "reject fact-changing humanization", "reasons": last_gate.reasons}
                    continue
                output = rewritten
            controller.advance_phase(InvestigationPhase.VALIDATE)
            output_validation = validate_output(
                mode=mode,
                text=output,
                declared_fact_ids=fact_ids,
                approved_fact_ids=controller.snapshot()["approved_fact_ids"],
                tier=str(proposal.get("tier", "STANDARD")),
                allow_gateway_names=bool(proposal.get("allow_gateway_names", False)),
                evidence=controller.snapshot()["evidence"],
                claims=claims,
            )
            if not output_validation.allowed:
                last_gate = GateResult(False, output_validation.reasons)
                context["controller_feedback"] = {
                    "status": "reject rendered output",
                    "reasons": output_validation.reasons,
                }
                continue
            if mode in {"B", "C"}:
                vale_result = run_vale(output, mode=mode)
                if not vale_result.allowed:
                    last_gate = GateResult(False, tuple(f"Vale: {message}" for message in vale_result.messages))
                    context["controller_feedback"] = {
                        "status": "reject style output",
                        "reasons": last_gate.reasons,
                    }
                    continue
                ticket_reasons = validate_ticket_answer(ticket_understanding, output)
                if ticket_reasons:
                    last_gate = GateResult(False, tuple(f"Ticket understanding: {reason}" for reason in ticket_reasons))
                    context["controller_feedback"] = {"status": "reject incomplete ticket answer", "reasons": last_gate.reasons}
                    continue
                persona_result = validate_persona_turn(
                    output,
                    correction=bool(proposal.get("correction", False)),
                    new_evidence=bool(context.get("what_changed", {}).get("new_fact_count", 0)),
                )
                if not persona_result.allowed:
                    last_gate = GateResult(False, tuple(f"Persona: {reason}" for reason in persona_result.reasons))
                    context["controller_feedback"] = {"status": "reject persona drift", "reasons": last_gate.reasons}
                    continue
            state = controller.snapshot()
            controller.advance_phase(InvestigationPhase.COMPLETE)
            state = controller.snapshot()
            state["run_id"] = run_id
            state["ticket_understanding"]["still_unanswered"] = list(unanswered_after_draft(ticket_understanding, output))
            state["trust_findings"] = [finding.as_dict() for finding in trust_findings]
            state["telemetry"] = self._telemetry(run_id, controller, round_number, "completed")
            state.update({"dudley_persona_version": PERSONA_VERSION, "dudley_persona_hash": PERSONA_HASH, "instruction_policy_version": INSTRUCTION_POLICY_VERSION})
            return EngineResult("completed", mode, output, last_gate, round_number, state, build_audit_record(case_id=controller.case_id, status="completed", mode=mode, rounds=round_number, gate={"allowed": last_gate.allowed, "reasons": last_gate.reasons}, state=state, output=output))

        state = controller.snapshot()
        state["run_id"] = run_id
        state["trust_findings"] = [finding.as_dict() for finding in trust_findings]
        state["telemetry"] = self._telemetry(run_id, controller, self.max_rounds, "blocked")
        state.update({"dudley_persona_version": PERSONA_VERSION, "dudley_persona_hash": PERSONA_HASH, "instruction_policy_version": INSTRUCTION_POLICY_VERSION})
        return EngineResult("blocked", None, None, last_gate, self.max_rounds, state, build_audit_record(case_id=controller.case_id, status="blocked", mode=None, rounds=self.max_rounds, gate={"allowed": last_gate.allowed, "reasons": last_gate.reasons}, state=state))

    def _source_plan(self, case_input: str) -> tuple[str, ...]:
        """Return mandatory sources; provider-specific no-path cases stay explicit."""
        lowered = case_input.casefold()
        plan = list(self.required_sources)
        dispute_without_automated_path = (
            ("klarna" in lowered or "worldpay" in lowered)
            and ("dispute" in lowered or "chargeback" in lowered)
        )
        if dispute_without_automated_path:
            plan = [source for source in plan if source.casefold() != "coralogix"]
        return tuple(plan)

    @staticmethod
    def _what_changed(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, Any]:
        old_evidence = before.get("evidence", ())
        new_evidence = after.get("evidence", ())[len(old_evidence):]
        return {
            "new_evidence": [item.get("raw_fact", "") for item in new_evidence],
            "new_fact_count": len(new_evidence),
            "coverage_changed": {key: value for key, value in after.get("coverage", {}).items() if value != before.get("coverage", {}).get(key)},
            "attachment_coverage_changed": {key: value for key, value in after.get("attachment_coverage", {}).items() if value != before.get("attachment_coverage", {}).get(key)},
            "remaining_open_questions": list(after.get("gate_reasons", ())),
        }

    @staticmethod
    def _telemetry(run_id: str, controller: CaseController, round_number: int, outcome: str) -> list[dict[str, Any]]:
        events = [TelemetryEvent(run_id, controller.case_id, "tool_result", round=round_number, source=record.source, result_state=record.result_state.value, evidence_count=record.fact_count, query_hash=query_digest(record.query), details={"validated": record.validated, "query_quality": record.query_quality}).as_dict() for record in controller.searches]
        events.append(TelemetryEvent(run_id, controller.case_id, "run_finished", round=round_number, details={"outcome": outcome, "phase": controller.phase.value, "blocked_reasons": list(controller.snapshot().get("gate_reasons", ())) }).as_dict())
        return events

    def _run_searches(self, controller: CaseController, searches: Iterable[Mapping[str, Any]]) -> None:
        for raw in searches:
            request = SearchRequest(
                source=str(raw["source"]),
                query=str(raw["query"]),
                identifiers=tuple(str(value) for value in raw.get("identifiers", controller.identifiers)),
                start_date=raw.get("start_date"),
                end_date=raw.get("end_date"),
                query_language=str(raw.get("query_language", "lucene")),
            )
            self._record_search(controller, request, str(raw.get("novelty", "new event")))

    def _record_search(self, controller: CaseController, request: SearchRequest, novelty: str) -> None:
        quality = assess_query(request)
        if request.source.casefold() in {source.casefold() for source in controller.required_sources} and controller.identifiers:
            searchable = " ".join((request.query, *request.identifiers)).casefold()
            if not any(identifier.casefold() in searchable for identifier in controller.identifiers):
                result = ToolResult(request.source, SearchResultState.FAILED, False, error="tool call missing case identifier")
                controller.add_tool_result(result, query=request.query, identifiers=request.identifiers, start_date=request.start_date, end_date=request.end_date, novelty=novelty, query_quality=quality.score, query_quality_reasons=quality.reasons)
                return
        try:
            result = self.search_executor.search(request)
        except Exception as exc:
            result = ToolResult(request.source, SearchResultState.FAILED, False, error=f"{type(exc).__name__}: {exc}")
        controller.add_tool_result(result, query=request.query, identifiers=request.identifiers, start_date=request.start_date, end_date=request.end_date, novelty=novelty, query_quality=quality.score, query_quality_reasons=quality.reasons + result_quality(result).reasons)
        if result.result_state == SearchResultState.NO_RESULT and result.valid_for_coverage and request.source.casefold() == "coralogix":
            planned: list[SearchRequest] = list(alternate_queries(request)[:8])
            planned.extend(time_sliced_queries(request)[:4])
            seen: set[str] = set()
            for alternate in planned:
                if alternate.query == request.query:
                    continue
                signature = "|".join((alternate.query, alternate.start_date or "", alternate.end_date or "", alternate.query_language))
                if signature in seen:
                    continue
                seen.add(signature)
                alternate_quality = assess_query(alternate)
                try:
                    alternate_result = self.search_executor.search(alternate)
                except Exception as exc:
                    alternate_result = ToolResult(alternate.source, SearchResultState.FAILED, False, error=f"{type(exc).__name__}: {exc}")
                controller.add_tool_result(alternate_result, query=alternate.query, identifiers=alternate.identifiers, start_date=alternate.start_date, end_date=alternate.end_date, novelty="automatic event-specific re-plan", query_quality=alternate_quality.score, query_quality_reasons=alternate_quality.reasons + result_quality(alternate_result).reasons)

    @staticmethod
    def _safe_proposal(raw: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(raw, Mapping):
            raise TypeError("LLM proposal must be an object")
        proposal = dict(raw)
        for key in ("searches", "hypotheses", "retries", "component_lifecycle", "provider_refund_results", "relevant_sources", "fact_ids", "claims", "negative_claims"):
            value = proposal.get(key, ())
            if not isinstance(value, (list, tuple)):
                raise TypeError(f"proposal field {key} must be a list")
            proposal[key] = tuple(value)
        return proposal

    @staticmethod
    def _apply_hypotheses(controller: CaseController, hypotheses: Iterable[Mapping[str, Any]]) -> None:
        for hypothesis in hypotheses:
            controller.add_hypothesis(
                str(hypothesis["label"]),
                hypothesis.get("supporting", ()),
                hypothesis.get("contradicting", ()),
            )

    @staticmethod
    def _apply_retries(controller: CaseController, retries: Iterable[Mapping[str, Any]]) -> None:
        for retry in retries:
            controller.link_retry(
                int(retry["failed_id"]),
                int(retry["later_id"]),
                relation=str(retry.get("relation", "same payment intent")),
            )

    @staticmethod
    def _apply_terminal_state(controller: CaseController, proposed: Mapping[str, Any] | None) -> None:
        if not proposed:
            return
        controller.set_terminal_state(
            str(proposed["state"]),
            funds_location=TerminalFundsState(str(proposed.get("funds_location", "unknown"))),
            lifecycle_checked=bool(proposed.get("lifecycle_checked", True)),
        )

    @staticmethod
    def _apply_negative_claims(controller: CaseController, claims: Iterable[Mapping[str, Any]]) -> None:
        for claim in claims:
            controller.record_negative_claim(
                str(claim["claim"]),
                source=str(claim["source"]),
                identifiers=tuple(str(value) for value in claim.get("identifiers", ())),
                adequate_window=bool(claim.get("adequate_window", False)),
                no_result_searches=int(claim.get("no_result_searches", 0)),
                later_event_checked=bool(claim.get("later_event_checked", False)),
            )


def extract_identifiers(case_input: str) -> frozenset[str]:
    """Extract candidate identifiers without treating correlation as confirmation."""
    values = set(ORDER_ID.findall(case_input)) | set(PSP_ID.findall(case_input)) | set(ARN.findall(case_input))
    return frozenset(value for value in values if value)


def _case_id(identifiers: Iterable[str], case_input: str) -> str:
    first = sorted(identifiers)[0] if identifiers else "case-" + str(abs(hash(case_input)))
    return first
