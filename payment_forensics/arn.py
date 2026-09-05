"""Deterministic ARN availability guidance for payment-forensics drafts."""

from __future__ import annotations

from typing import Any, Iterable, Mapping


def assess_arn_availability(case_input: str, evidence: Iterable[Mapping[str, Any]] = ()) -> dict[str, str]:
    """Explain a missing ARN when the captured method and status support it."""
    text = case_input.casefold()
    method = "american express" if "american express" in text else ("amex" if "amex" in text else "")
    external = "refundedexternally" in text or "external acquirer" in text
    for item in evidence:
        values = " ".join(str(item.get(key, "")) for key in ("payment_method", "raw_fact", "status", "event_type")).casefold()
        if not method and "american express" in values:
            method = "american express"
        external = external or "refundedexternally" in values or "external acquirer" in values
    if method == "american express" and external:
        return {
            "status": "NOT_EXPECTED",
            "reason": "American Express payments do not receive an ARN in this payment system, and this refund was processed through an external acquirer.",
            "next_step": "Use the refund reference, amount, and timestamp for tracing, or contact the external acquirer if an ARN is required.",
        }
    return {"status": "UNRESOLVED", "reason": "No deterministic payment-method rule explains the missing ARN.", "next_step": "Continue checking the payment events, provider logs, and acquiring partner records."}
