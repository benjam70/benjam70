"""Run the real completion gate against a self-reported investigation state.

This exists to close a specific gap: in a live chat session (Claude Code,
Codex, or anything else reading the payment-forensics skill as prose), the
model is the only thing running. Nothing forces it through
`payment_forensics.controller.CaseController.completion_gate` the way
`HybridEngine` does for a scripted run. This script gives that same host a way
to call the real gate itself: write the case state as JSON, run this script
against it, and only write a final Mode A/B/C answer if it prints GATE: PASS.

This is not independent verification. It cannot confirm a source was actually
queried, only that the reported state is internally consistent with every
hard rule the controller enforces (every relevant source at CHECKED/N-A, every
contradiction resolved, every negative claim proven, a terminal state
established, component lifecycle and amount reconciliation resolved, at least
one approved fact backing the output). A model that reports a source as
CHECKED without having queried it will still pass. What it does catch is the
common failure this whole system exists to prevent: an investigation that
quietly skips a required source, leaves a contradiction unresolved, or
declares "done" without ever committing to a terminal funds state.

Case-state JSON shape (all fields optional except where noted; unknown fields
are ignored, missing ones default to "not yet established" so the gate fails
closed rather than open):

    {
      "case_id": "GE12345678AB",
      "identifiers": ["GE12345678AB", "pi_..."],
      "ticket_intent": "refund_status",
      "relevant_sources": ["Ticket", "Coralogix", "Gateway"],
      "coverage": {"Ticket": "CHECKED", "Coralogix": "CHECKED", "Gateway": "N/A"},
      "attachment_coverage": {"export.csv": "CHECKED"},
      "evidence": [
        {"source": "Coralogix", "source_type": "log", "event_type": "REFUND",
         "status": "REFUNDED", "amount": "10.00", "currency": "GBP",
         "order_id": "GE12345678AB", "raw_fact": "refund confirmed"}
      ],
      "negative_claims": [
        {"claim": "no chargeback found", "proven_absence": true}
      ],
      "component_lifecycle": {
        "refund": {"status": "REFUNDED", "amount": "10.00", "currency": "GBP"}
      },
      "provider_refund_results": {"refund": {"status": "REFUNDED"}},
      "amount_reconciliation": {"status": "RECONCILED"},
      "terminal_state": {"state": "refunded", "funds_location": "customer bank"},
      "identity_established": true,
      "lifecycle_checked": true,
      "retries_required": false,
      "retries_checked": true,
      "contradiction_ids_resolved": [],
      "intent_established": true
    }

Coverage values are one of CHECKED, NOT_CHECKED, N/A, PARTIAL, FAILED.
`funds_location` is one of the `TerminalFundsState` values (see
`payment_forensics/controller.py`): customer bank, merchant settlement,
Global-e balance, gateway pending state, reversed, refunded, held by dispute
process, unknown. `contradiction_ids_resolved` refers to indices the
controller assigns automatically when two pieces of submitted evidence
conflict, not something the caller invents.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from payment_forensics.controller import (  # noqa: E402
    CaseController,
    CoverageStatus,
    EvidenceItem,
    TerminalFundsState,
)


class StateError(ValueError):
    """A case-state file is malformed in a way the gate cannot evaluate."""


def _coverage_status(value: str, *, context: str) -> CoverageStatus:
    try:
        return CoverageStatus(value)
    except ValueError as exc:
        valid = ", ".join(status.value for status in CoverageStatus)
        raise StateError(f"{context}: {value!r} is not a valid coverage status ({valid})") from exc


def build_controller(state: Mapping[str, Any]) -> CaseController:
    if not isinstance(state, Mapping):
        raise StateError(f"case state must be a JSON object, got {type(state).__name__}")
    case_id = str(state.get("case_id") or "unknown-case")
    identifiers = tuple(str(value) for value in state.get("identifiers", ()))
    relevant_sources = tuple(str(value) for value in state.get("relevant_sources", ()))
    controller = CaseController(
        case_id=case_id,
        identifiers=identifiers,
        required_sources=relevant_sources,
        required_attachments=tuple(state.get("attachment_coverage", {})),
    )

    if state.get("ticket_intent"):
        controller.set_ticket_intent(str(state["ticket_intent"]))

    for source, status in state.get("coverage", {}).items():
        controller.coverage[str(source)] = _coverage_status(str(status), context=f"coverage[{source!r}]")

    for name, status in state.get("attachment_coverage", {}).items():
        controller.attachment_coverage[str(name)] = _coverage_status(str(status), context=f"attachment_coverage[{name!r}]")

    for index, item in enumerate(state.get("evidence", ())):
        if not isinstance(item, Mapping):
            raise StateError(f"evidence[{index}] must be an object")
        try:
            controller.add_evidence(EvidenceItem(**item))
        except TypeError as exc:
            raise StateError(f"evidence[{index}]: {exc}") from exc

    for claim in state.get("negative_claims", ()):
        if "proven_absence" not in claim:
            raise StateError(f"negative_claims entry missing required 'proven_absence': {claim!r}")
    controller.negative_claims = [dict(claim) for claim in state.get("negative_claims", ())]

    for component, info in state.get("component_lifecycle", {}).items():
        if "status" not in info:
            raise StateError(f"component_lifecycle[{component!r}] missing required 'status'")
        controller.record_component_state(
            str(component),
            str(info["status"]),
            amount=info.get("amount"),
            currency=info.get("currency"),
            timestamp=info.get("timestamp"),
            fact_ids=tuple(info.get("fact_ids", ())),
        )

    if "provider_refund_results" in state:
        controller.provider_refund_results = {str(k): dict(v) for k, v in state["provider_refund_results"].items()}

    if "amount_reconciliation" in state and state["amount_reconciliation"] is not None:
        controller.amount_reconciliation = dict(state["amount_reconciliation"])

    terminal_state = state.get("terminal_state")
    if terminal_state is not None:
        if "state" not in terminal_state or "funds_location" not in terminal_state:
            raise StateError("terminal_state requires 'state' and 'funds_location'")
        try:
            funds_location = TerminalFundsState(terminal_state["funds_location"])
        except ValueError as exc:
            valid = ", ".join(status.value for status in TerminalFundsState)
            raise StateError(f"terminal_state.funds_location: {terminal_state['funds_location']!r} is not valid ({valid})") from exc
        controller.set_terminal_state(
            str(terminal_state["state"]),
            funds_location=funds_location,
            lifecycle_checked=bool(terminal_state.get("lifecycle_checked", True)),
        )

    return controller


def evaluate(state: Mapping[str, Any]) -> tuple[bool, tuple[str, ...]]:
    controller = build_controller(state)
    relevant_sources = tuple(str(value) for value in state.get("relevant_sources", ()))
    try:
        contradiction_ids_resolved = tuple(int(value) for value in state.get("contradiction_ids_resolved", ()))
    except (TypeError, ValueError) as exc:
        raise StateError(f"contradiction_ids_resolved must be a list of integers: {exc}") from exc
    gate = controller.completion_gate(
        identity_established=bool(state.get("identity_established", False)),
        relevant_sources=relevant_sources,
        lifecycle_checked=state.get("lifecycle_checked"),
        retries_required=bool(state.get("retries_required", False)),
        retries_checked=bool(state.get("retries_checked", True)),
        contradiction_ids_resolved=contradiction_ids_resolved,
        intent_established=bool(state.get("intent_established", True)),
    )
    return gate.allowed, gate.reasons


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        print("usage: python tools/dudley_gate_check.py <case_state.json>", file=sys.stderr)
        return 2
    path = Path(args[0])
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"GATE: ERROR could not read case state: {exc}", file=sys.stderr)
        return 2
    try:
        allowed, reasons = evaluate(state)
    except StateError as exc:
        print(f"GATE: ERROR malformed case state: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # a malformed but valid-JSON state must never crash the caller
        print(f"GATE: ERROR malformed case state: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    if allowed:
        print("GATE: PASS")
        return 0
    print("GATE: FAIL")
    for reason in reasons:
        print(f"- {reason}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
