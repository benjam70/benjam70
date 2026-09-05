"""Deterministic validation for rendered payment-forensics outputs."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable


@dataclass(frozen=True)
class OutputValidation:
    allowed: bool
    reasons: tuple[str, ...] = ()


_BANNED_TERMS = (
    "successfully", "should", "we", "our", "us", "team", "reached out",
    "escalated", "will follow up", "soon", "sorry", "appreciate",
)
_GATEWAY_NAMES = ("Adyen", "Stripe", "PayPal", "Klarna", "Worldpay")
_SENTENCE_RE = re.compile(r"[^.!?]+(?:[.!?]+|$)", re.MULTILINE)
_WORD_RE = re.compile(r"\b[\w][\w'/-]*\b")
_SENSITIVE_RE = re.compile(r"(?i)\b(?:cvv|cvc|security code)\s*[:=]?\s*\d{3,4}\b|(?<!\d)\d(?:[ -]?\d){12,18}\d(?!\d)")


def validate_claims(claims: Iterable[dict], approved_fact_ids: Iterable[int], evidence: Iterable[dict] = ()) -> OutputValidation:
    """Require every proposed factual claim to cite approved ledger facts."""
    reasons: list[str] = []
    approved = set(int(value) for value in approved_fact_ids)
    evidence_by_id = {index: item for index, item in enumerate(evidence)}
    for index, claim in enumerate(claims):
        if not isinstance(claim, dict):
            reasons.append(f"claim {index} is not an object")
            continue
        text = claim.get("text")
        fact_ids = claim.get("fact_ids")
        if not isinstance(text, str) or not text.strip():
            reasons.append(f"claim {index} has no text")
        if not isinstance(fact_ids, (list, tuple)) or not fact_ids:
            reasons.append(f"claim {index} has no fact IDs")
            continue
        try:
            unapproved = sorted(set(int(value) for value in fact_ids) - approved)
        except (TypeError, ValueError):
            reasons.append(f"claim {index} has invalid fact IDs")
            continue
        if unapproved:
            reasons.append(f"claim {index} cites unapproved facts: " + ", ".join(map(str, unapproved)))
        cited = [evidence_by_id[int(fact_id)] for fact_id in fact_ids if int(fact_id) in evidence_by_id]
        receipt_cited = any(item.get("evidence_role") in {"customer_receipt", "bank_receipt"} for item in cited)
        lifecycle_cited = any(item.get("event_type") in {"CAPTURE", "REFUND", "SETTLEMENT", "PAYMENT"} for item in cited)
        claim_type = str(claim.get("claim_type", "")).lower()
        payment_assertion = re.search(r"\b(debit(?:ed)?|charged|paid|payment was made|captured)\b", str(text), re.IGNORECASE)
        if receipt_cited and payment_assertion and not lifecycle_cited and claim_type not in {"customer_report", "receipt_observation"}:
            reasons.append(f"claim {index} treats a receipt as proof of payment lifecycle without lifecycle evidence")
        field = claim.get("field")
        expected = claim.get("expected_value")
        if field is not None or expected is not None:
            allowed_fields = {"event_type", "status", "amount", "currency", "provider", "order_id", "payment_id", "refund_id", "psp_reference", "arn", "dispute_id"}
            if not isinstance(field, str) or expected is None:
                reasons.append(f"claim {index} has incomplete field assertion")
            elif field not in allowed_fields:
                reasons.append(f"claim {index} uses unsupported assertion field: {field}")
            elif not any(str(evidence_by_id[int(fact_id)].get(field)) == str(expected) for fact_id in fact_ids if int(fact_id) in evidence_by_id):
                reasons.append(f"claim {index} does not match its evidence assertion")
    return OutputValidation(not reasons, tuple(reasons))


def validate_output(
    *,
    mode: str,
    text: str,
    declared_fact_ids: Iterable[int],
    approved_fact_ids: Iterable[int],
    tier: str = "STANDARD",
    allow_gateway_names: bool = False,
    evidence: Iterable[dict] = (),
    claims: Iterable[dict] | None = None,
) -> OutputValidation:
    reasons: list[str] = []
    normalized_mode = str(mode).upper()
    if normalized_mode not in {"A", "B", "C"}:
        reasons.append(f"invalid mode: {normalized_mode}")
    if not isinstance(text, str) or not text.strip():
        reasons.append("output is empty")
        return OutputValidation(False, tuple(reasons))
    if _SENSITIVE_RE.search(text):
        reasons.append("output contains prohibited card/security data")

    approved = set(int(value) for value in approved_fact_ids)
    declared = tuple(int(value) for value in declared_fact_ids)
    unapproved = sorted(set(declared) - approved)
    if unapproved:
        reasons.append("unapproved output facts: " + ", ".join(map(str, unapproved)))

    if normalized_mode in {"B", "C"}:
        lowered = text.lower()
        evidence_list = list(evidence)
        receipt_present = any(item.get("evidence_role") in {"customer_receipt", "bank_receipt"} for item in evidence_list)
        lifecycle_present = any(item.get("event_type") in {"CAPTURE", "REFUND", "SETTLEMENT", "PAYMENT"} for item in evidence_list)
        if receipt_present and re.search(r"\b(receipt|debit(?:ed)?|charged|paid)\b", lowered) and re.search(r"\b(proves?|confirms?|was debited|was charged|payment was made)\b", lowered) and not lifecycle_present:
            reasons.append("receipt wording is not supported by payment lifecycle evidence")
        if receipt_present and re.search(r"adds? no new information|does not add new information", lowered):
            reasons.append("customer receipt cannot be dismissed without an explicit receipt assessment")
        if claims is not None and not tuple(claims):
            reasons.append(f"Mode {normalized_mode} requires at least one grounded claim")
        for term in _BANNED_TERMS:
            if re.search(rf"\b{re.escape(term)}\b", lowered):
                reasons.append(f"banned Mode {normalized_mode} term: {term}")
        if not allow_gateway_names:
            for name in _GATEWAY_NAMES:
                if re.search(rf"\b{re.escape(name)}\b", text, re.IGNORECASE):
                    reasons.append(f"gateway name not allowed in Mode {normalized_mode}: {name}")
        if normalized_mode == "B" and not _is_code_block(text):
            reasons.append("Mode B must be inside a code block")
        if normalized_mode == "C" and not re.match(r"^\s*[^\n]+\n\s*```", text):
            reasons.append("Mode C requires a subject line followed by a code block")

        max_sentence_words = 20 if normalized_mode == "C" else 25
        for sentence in _SENTENCE_RE.findall(text):
            if len(_WORD_RE.findall(sentence)) > max_sentence_words:
                reasons.append(f"Mode {normalized_mode} sentence exceeds {max_sentence_words} words")
                break
        ceiling = {"FAST": 80, "STANDARD": 150, "DEEP": 250}.get(str(tier).upper(), 150)
        if len(_WORD_RE.findall(text)) > ceiling:
            reasons.append(f"Mode {normalized_mode} exceeds {ceiling} words for {str(tier).upper()} tier")

    return OutputValidation(not reasons, tuple(reasons))


def _is_code_block(text: str) -> bool:
    stripped = text.strip()
    return stripped.startswith("```") and stripped.endswith("```")
