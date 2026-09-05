"""Deterministic understanding of payment-ticket requests."""

from __future__ import annotations

from dataclasses import dataclass, asdict
import re
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class TicketUnderstanding:
    primary_intent: str
    secondary_intents: tuple[str, ...] = ()
    requested_artifacts: tuple[str, ...] = ()
    conversation_acts: tuple[str, ...] = ()
    known_facts: tuple[str, ...] = ()
    open_questions: tuple[str, ...] = ()
    audience: str = "internal_cs"
    confidence: float = 0.0
    already_known: tuple[str, ...] = ()
    explicitly_requested: tuple[str, ...] = ()
    still_unanswered: tuple[str, ...] = ()
    slots: Mapping[str, tuple[str, ...]] | None = None
    original_primary_intent: str | None = None
    current_primary_intent: str | None = None
    intent_history: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


_ARN = re.compile(r"\b\d{20,}\b")


def understand_ticket(text: str, thread_history: Iterable[str | Mapping[str, Any]] = ()) -> TicketUnderstanding:
    """Extract intents and request slots without asking the model to infer them."""
    value = str(text or "")
    history_values = [str(item.get("text", "")) if isinstance(item, Mapping) else str(item) for item in thread_history]
    lowered = value.casefold()
    intents: list[str] = []
    artifacts: list[str] = []
    acts: list[str] = []
    questions: list[str] = []
    requested: list[str] = []

    if any(term in lowered for term in ("arn", "acquirer reference", "retrieval reference")):
        intents.append("provide_refund_arn")
        artifacts.append("arn")
        requested.append("arn")
    if any(term in lowered for term in ("refund letter", "refund proof", "proof of refund")):
        intents.append("provide_refund_proof")
        artifacts.append("refund_proof")
        requested.append("refund_proof")
    if "refund" in lowered:
        intents.append("confirm_refund_status")
        artifacts.append("refund_status")
        requested.append("refund_status")
    if any(term in lowered for term in ("why", "how come", "doesn't line up", "discrepancy", "difference")):
        intents.append("explain_reconciliation")
        artifacts.append("explanation")
        requested.append("explanation")
    if any(term in lowered for term in ("charged", "payment", "capture", "settled", "authorization", "authorisation")):
        intents.append("explain_payment_status")
        artifacts.append("payment_status")
        requested.append("payment_status")
    if any(term in lowered for term in ("correct", "wrong", "not right", "have another look", "keep digging")):
        acts.append("challenge_or_correction")
    if "already" in lowered or "as stated" in lowered or "merchant knows" in lowered:
        acts.append("avoid_repetition")
    if "?" in value or any(term in lowered for term in ("can you", "could you", "please", "do we have", "how do we")):
        acts.append("request")

    if not intents:
        intents.append("payment_investigation")
    unique_intents = tuple(dict.fromkeys(intents))
    unique_artifacts = tuple(dict.fromkeys(artifacts))
    if "arn" in unique_artifacts:
        questions.append("Was the requested ARN found and included?")
    if "refund_status" in unique_artifacts:
        questions.append("Was the refund status answered?")
    if "explanation" in unique_artifacts:
        questions.append("Was the discrepancy explained with the relevant arithmetic?")
    amounts = tuple(dict.fromkeys(re.findall(r"(?<!\w)(?:[A-Z]{1,3}\$|[$€£¥]|[A-Z]{2,3})\s?\d+(?:[.,]\d{2})?(?!\w)", value)))
    dates = tuple(dict.fromkeys(re.findall(r"\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:?\d{2})?)?\b", value)))
    refund_ids = tuple(dict.fromkeys(re.findall(r"(?i)\b(?:refund\s*(?:id|reference)|refundid)[ :#-]*([A-Za-z0-9_-]{4,})", value)))
    known = tuple(sorted(set(_ARN.findall(value)) | set(refund_ids) | set(amounts) | set(dates)))
    previous = understand_ticket(history_values[0]) if history_values else None
    original_intent = previous.primary_intent if previous else unique_intents[0]
    intent_history = tuple(dict.fromkeys(([previous.primary_intent] if previous else []) + list(unique_intents)))
    known_facts = tuple(dict.fromkeys(known + (previous.known_facts if previous else ())))
    confidence = 0.95 if len(unique_intents) > 1 or unique_artifacts else 0.75
    explicit = tuple(dict.fromkeys(requested))
    unanswered = tuple(dict.fromkeys(questions))
    slots = {"order_ids": tuple(sorted(set(re.findall(r"\bGE\d{8,}[A-Z]{2}\b", value, re.I)))), "amounts": amounts, "dates": dates, "refund_ids": refund_ids, "arns": tuple(_ARN.findall(value))}
    return TicketUnderstanding(unique_intents[0], unique_intents[1:], unique_artifacts, tuple(dict.fromkeys(acts)), known_facts, unanswered, "merchant" if "merchant" in lowered else "internal_cs", confidence, known_facts, explicit, unanswered, slots, original_intent, unique_intents[0], intent_history)


def validate_ticket_answer(understanding: TicketUnderstanding, output: str) -> tuple[str, ...]:
    """Check that a draft addresses explicitly requested artifacts."""
    lowered = str(output or "").casefold()
    reasons: list[str] = []
    if "arn" in understanding.requested_artifacts and not _ARN.search(str(output or "")):
        reasons.append("ticket requested an ARN but the draft contains no ARN")
    if "refund_proof" in understanding.requested_artifacts and not any(term in lowered for term in ("refund letter", "refund reference", "arn")):
        reasons.append("ticket requested refund proof but the draft contains no refund proof reference")
    if "refund_status" in understanding.requested_artifacts and not any(term in lowered for term in ("refund", "refunded", "refunded")):
        reasons.append("ticket requested refund status but the draft does not mention the refund")
    if "explanation" in understanding.requested_artifacts and len(lowered.split()) < 5:
        reasons.append("ticket requested an explanation but the draft is too short")
    return tuple(reasons)


def unanswered_after_draft(understanding: TicketUnderstanding, output: str) -> tuple[str, ...]:
    """Return the request questions that remain after a draft is written."""
    reasons = validate_ticket_answer(understanding, output)
    if reasons:
        return understanding.still_unanswered
    return ()
