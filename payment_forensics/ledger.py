"""Deterministic payment-event accounting used below the language-model layer."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class PaymentEvent:
    """A normalized money movement or authorization event."""

    event_type: str
    amount: str
    currency: str
    status: str = ""
    event_id: str | None = None
    timestamp: str | None = None
    source: str | None = None
    fact_id: int | None = None
    component: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EventRelation:
    left: str
    right: str
    relation: str


def validate_provider_refund_response(response: Mapping[str, Any]) -> dict[str, Any]:
    """Classify a structured provider refund response deterministically."""
    refund = response.get("refund")
    errors = response.get("userErrors", response.get("user_errors", ())) or ()
    if isinstance(errors, (str, bytes)):
        errors = (errors,)
    elif not isinstance(errors, (list, tuple)):
        errors = (errors,)
    normalized_errors = []
    for error in errors:
        if isinstance(error, Mapping):
            normalized_errors.append({"field": error.get("field"), "message": str(error.get("message", "")), "code": error.get("code")})
        else:
            normalized_errors.append({"field": None, "message": str(error), "code": None})
    if normalized_errors and refund is None:
        status, classification = "FAILED", "PROVIDER_REJECTED"
    elif normalized_errors:
        status, classification = "UNRESOLVED", "PROVIDER_RESPONSE_CONFLICT"
    elif refund is not None:
        status, classification = "REFUNDED", "PROVIDER_CONFIRMED"
    else:
        status, classification = "UNRESOLVED", "PROVIDER_RESPONSE_INCOMPLETE"
    return {
        "status": status,
        "classification": classification,
        "refund_present": refund is not None,
        "provider_refund_id": refund.get("id") if isinstance(refund, Mapping) else None,
        "errors": normalized_errors,
    }


def events_from_evidence(evidence: Iterable[Mapping[str, Any]], approved_ids: Iterable[int] | None = None) -> tuple[PaymentEvent, ...]:
    """Convert approved lifecycle evidence into normalized ledger events."""
    allowed = None if approved_ids is None else set(int(value) for value in approved_ids)
    events: list[PaymentEvent] = []
    seen: set[tuple[Any, ...]] = set()
    event_types = {"AUTHORISATION", "AUTHORIZATION", "CAPTURE", "SETTLEMENT", "PAYMENT", "REFUND", "REFUNDED"}
    for index, item in enumerate(evidence):
        if allowed is not None and index not in allowed:
            continue
        event_type = str(item.get("event_type") or "").upper()
        if event_type not in event_types or item.get("amount") is None or not item.get("currency"):
            continue
        key = (event_type, str(item.get("status") or "").upper(), str(item.get("amount")), str(item.get("currency")).upper(), item.get("timestamp"), item.get("psp_reference"), item.get("refund_id"))
        if key in seen:
            continue
        seen.add(key)
        events.append(PaymentEvent(event_type, str(item["amount"]), str(item["currency"]), str(item.get("status") or ""), event_id=str(item.get("psp_reference") or item.get("refund_id") or f"fact:{index}"), timestamp=item.get("timestamp"), source=item.get("source"), fact_id=index, component=item.get("component")))
    return tuple(events)


def _decimal(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value)) if value is not None else None
    except (InvalidOperation, ValueError):
        return None


def reconcile_events(events: Iterable[PaymentEvent], *, adjustment_amount: str | None = None) -> dict[str, Any]:
    """Reconcile normalized events without relying on labels or model prose.

    Amount arithmetic is performed here so a model cannot turn an uncaptured
    authorization into a missing refund, or silently net unrelated events.
    """
    unique: dict[str, PaymentEvent] = {}
    for item in events:
        key = item.event_id or "|".join((item.event_type.upper(), item.amount, item.currency.upper(), item.timestamp or ""))
        unique.setdefault(key, item)
    items = tuple(unique.values())
    currencies = {item.currency.upper() for item in items if item.currency}
    amounts = [_decimal(item.amount) for item in items]
    result: dict[str, Any] = {
        "events": [item.as_dict() for item in items],
        "currency": next(iter(currencies), ""),
        "status": "UNRESOLVED",
        "classification": "ambiguous",
        "reasons": [],
    }
    if len(currencies) > 1 or any(value is None for value in amounts):
        result["reasons"] = ["events have invalid or mixed-currency amounts"]
        return result

    authorized = sum((value for item, value in zip(items, amounts) if item.event_type.upper() in {"AUTHORISATION", "AUTHORIZATION"}), Decimal("0"))
    captured = sum((value for item, value in zip(items, amounts) if item.event_type.upper() in {"CAPTURE", "SETTLEMENT", "PAYMENT"} and item.status.upper() not in {"FAILED", "REFUSED", "REJECTED"}), Decimal("0"))
    refunded = sum((value for item, value in zip(items, amounts) if item.event_type.upper() in {"REFUND", "REFUNDED"} and item.status.upper() not in {"FAILED", "REFUSED", "REJECTED"}), Decimal("0"))
    adjustment = _decimal(adjustment_amount)
    gap = authorized - captured
    result.update({"authorized": str(authorized), "captured": str(captured), "refunded": str(refunded), "authorization_gap": str(gap)})
    if authorized > 0 and captured == refunded and gap > 0 and (adjustment is None or adjustment == gap):
        result.update({"status": "RECONCILED", "classification": "UNCAPTURED_AUTHORIZATION", "uncaptured_authorization": str(gap)})
    elif captured > 0 and refunded == captured:
        result.update({"status": "RECONCILED", "classification": "FULL_REFUND", "remaining": "0"})
    elif captured > 0 and refunded < captured:
        result.update({"status": "UNRESOLVED", "classification": "PARTIAL_OR_MISSING_REFUND", "remaining": str(captured - refunded), "reasons": ["captured amount is not fully mapped to refunds"]})
    else:
        result["reasons"] = ["payment lifecycle does not contain a safely reconcilable capture and refund"]
    return result


def reconcile_evidence(evidence: Iterable[Mapping[str, Any]], approved_ids: Iterable[int] | None = None, *, adjustment_amount: str | None = None) -> dict[str, Any]:
    """Derive the ledger from evidence, never from model-supplied aggregates."""
    return reconcile_events(events_from_evidence(evidence, approved_ids), adjustment_amount=adjustment_amount)
