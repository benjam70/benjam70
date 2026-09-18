"""Thread digest and delta-draft gate for Mode B/C.

Builds a structured common-ground record from prior ticket messages so drafts
answer only what is still open for the recipient, instead of replaying facts
already told to that audience.

Deterministic: keyword/status fingerprints plus short-sentence reference cues.
No model call required. Hosts that skip HybridEngine still follow the same
digest rules in CORE.md; this module is the mechanical enforcer when the
engine runs.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any, Iterable, Mapping


_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+|\n+")
_WORD_RE = re.compile(r"[A-Za-z0-9']+")
_ORDER_RE = re.compile(r"\bGE\d{8,}[A-Z]{2}\b", re.I)
_AMOUNT_RE = re.compile(
    r"(?<!\w)(?:GBP|EUR|USD|AUD|CAD|SGD|[£$€])\s?\d{1,3}(?:,\d{3})*(?:\.\d{2})?\b"
    r"|\b\d{1,3}(?:,\d{3})*\.\d{2}\s?(?:GBP|EUR|USD|AUD|CAD|SGD)\b"
    # Bare money-like decimals (merchant notes often omit the currency code).
    # Excludes dot-separated dates (15.09.2026): a decimal immediately
    # followed by another ".<digit>" is a date component, not an amount.
    r"|\b\d{1,3}(?:,\d{3})*\.\d{2}\b(?!\.\d)",
    re.I,
)
_DATE_RE = re.compile(
    r"\b\d{1,2}/\d{1,2}/\d{2,4}\b"
    r"|\b\d{4}-\d{2}-\d{2}\b"
)
_REF_RE = re.compile(
    r"\b(?:pi_|ch_|re_|du_)[A-Za-z0-9]+\b"
    r"|\b[A-Z0-9]{12,20}\b"
    r"|\b(?:refund\s*(?:id|ref(?:erence)?)|ARN)[ :#-]*[A-Za-z0-9_-]{4,}\b",
    re.I,
)

# (pattern, fact_key) — payment statuses / outcomes already communicable in a thread
_FACT_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bno refunds?(?:\s+\w+){0,4}\s+process", re.I), "no_refund_processed"),
    (re.compile(r"\bno\s+global-?e\s+refund\b", re.I), "no_refund_processed"),
    (re.compile(r"\bno\s+refund\s+(?:exists|has been|was)\b", re.I), "no_refund_processed"),
    (
        re.compile(
            r"\brefundfailed\b"
            r"|\brefund\s+failed\b"
            r"|\brefund\b(?:\s+\S+){0,8}\s+failed\b"
            r"|\brefund\s+shows?\s+as\s+failed\b"
            r"|\bshows?\s+as\s+failed\b",
            re.I,
        ),
        "refund_failed",
    ),
    (re.compile(r"\bthere is a chargeback\b|\ba chargeback for\b|\bchargeback for this\b", re.I), "chargeback_exists"),
    (re.compile(r"\bchargeback\b", re.I), "chargeback_exists"),
    (re.compile(r"\bchargeback\s+(?:was\s+)?reversed\b|\bchargebackreversed\b", re.I), "chargeback_reversed"),
    (re.compile(r"\bdispute status(?:\s+\w+){0,3}\s+pending\b|\bstatus remains pending\b|\bstill pending\b", re.I), "dispute_pending"),
    (re.compile(r"\bpre-?arbitration\b", re.I), "pre_arbitration"),
    (re.compile(r"\bsecond chargeback\b|\bfurther chargeback\b", re.I), "second_chargeback_possible"),
    (re.compile(r"\bproof of refund\b|\brefund proof\b|\brefund letter\b", re.I), "refund_proof_request"),
    (re.compile(r"\barn\b", re.I), "arn_mentioned"),
    (re.compile(r"\bcaptured\b|\bauthori[sz]ed\b|\bsettled\b", re.I), "payment_lifecycle"),
    (
        re.compile(
            r"\bdispute\s+(?:was\s+|is\s+)?closed\b"
            r"|\bcase\s+(?:was\s+|is\s+)?closed\b"
            r"|\bclosed\s+the\s+dispute\b",
            re.I,
        ),
        "dispute_closed",
    ),
    (
        re.compile(
            r"\brefund\s+processed\b"
            r"|\brefund\s+(?:has\s+been|was)\s+processed\b"
            r"|\bprocessed,?\s+dispute\s+closed\b",
            re.I,
        ),
        "refund_processed",
    ),
)

_REFERENCE_CUES = re.compile(
    r"\balready\b|\bearlier\b|\bas noted\b|\bas flagged\b|\bfollowing the\b|"
    r"\bprevious(?:ly)?\b|\bas stated\b|\bupdate on\b|\bmentioned\b",
    re.I,
)

_MERCHANT_SPEAKER = re.compile(
    r"\b(?:dear team|kind regards|customer service|merchant|harrods|shakeel|"
    r"please confirm|please attach|stock point)\b",
    re.I,
)
_INTERNAL_SPEAKER = re.compile(
    r"\b(?:hi finance|internal|bridge|hi team,\s*kindly|please advise)\b",
    re.I,
)
_OUTBOUND_TO_MERCHANT = re.compile(
    r"\b(?:hi shakeel|dear shakeel|thank you for your message|kindly proceed|"
    r"please note that our system|i see that there is a chargeback|"
    r"kind regards,\s*\w+)\b",
    re.I,
)


@dataclass(frozen=True)
class ThreadFact:
    text: str
    fact_keys: tuple[str, ...]
    speaker_role: str
    audience: str
    message_index: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ThreadDigest:
    established: tuple[ThreadFact, ...]
    already_told_merchant: tuple[ThreadFact, ...]
    already_told_internal: tuple[ThreadFact, ...]
    open_items: tuple[str, ...]
    current_ask: str
    recipient: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "established": [item.as_dict() for item in self.established],
            "already_told_merchant": [item.as_dict() for item in self.already_told_merchant],
            "already_told_internal": [item.as_dict() for item in self.already_told_internal],
            "open_items": list(self.open_items),
            "current_ask": self.current_ask,
            "recipient": self.recipient,
            "already_told_fact_keys": sorted(self.fact_keys_for_recipient()),
            "open_fact_keys": sorted(self.open_fact_keys()),
        }

    def fact_keys_for_recipient(self) -> set[str]:
        if self.recipient == "merchant":
            source = list(self.already_told_merchant)
            # Merchant already knows facts they themselves stated (their ask
            # is not news to them). Count those as known so Mode C cannot
            # restate "the refund failed" back as the opening finding.
            source.extend(
                fact for fact in self.established if fact.speaker_role == "merchant"
            )
        else:
            source = self.already_told_internal
        keys: set[str] = set()
        for fact in source:
            keys.update(fact.fact_keys)
        return keys

    def open_fact_keys(self) -> set[str]:
        """Fact keys implied by open items (allowed / expected in the draft)."""
        keys: set[str] = set()
        joined = " ".join(self.open_items).casefold()
        if "chargeback outcome" in joined or "dispute outcome" in joined or "reversed" in joined:
            keys.update({"chargeback_reversed", "dispute_pending", "second_chargeback_possible", "pre_arbitration"})
        if "refund status" in joined or "no refund" in joined or "portal" in joined or "payout" in joined:
            keys.add("no_refund_processed")
        if "refund proof" in joined or "arn" in joined:
            keys.update({"refund_proof_request", "arn_mentioned"})
        if "payment status" in joined:
            keys.add("payment_lifecycle")
        if "answer latest ask" in joined:
            # Unknown delta: allow new outcome keys, still block pure restatement of closed statuses.
            keys.update({"chargeback_reversed", "dispute_pending", "second_chargeback_possible", "no_refund_processed"})
        if "favour" in joined or "whose-side" in joined:
            keys.update({"dispute_pending", "second_chargeback_possible"})
        return keys


def _normalize_message(item: str | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(item, Mapping):
        text = str(item.get("text") or item.get("body") or item.get("content") or "")
        role = str(item.get("role") or item.get("speaker_role") or item.get("from_role") or "").strip().lower()
        audience = str(item.get("audience") or item.get("to_role") or "").strip().lower()
        return {"text": text, "role": role, "audience": audience}
    return {"text": str(item), "role": "", "audience": ""}


def _infer_roles(text: str, explicit_role: str, explicit_audience: str) -> tuple[str, str]:
    role = explicit_role
    audience = explicit_audience
    if not role:
        if _INTERNAL_SPEAKER.search(text):
            role = "internal_cs"
        elif _OUTBOUND_TO_MERCHANT.search(text):
            role = "internal_cs"
            audience = audience or "merchant"
        elif _MERCHANT_SPEAKER.search(text):
            role = "merchant"
            audience = audience or "internal_cs"
        else:
            role = "unknown"
    if not audience:
        if role == "internal_cs" and _OUTBOUND_TO_MERCHANT.search(text):
            audience = "merchant"
        elif role == "merchant":
            audience = "internal_cs"
        elif role == "internal_cs":
            audience = "internal_cs"
        else:
            audience = "unknown"
    if audience in {"cs", "colleague", "finance", "bridge"}:
        audience = "internal_cs"
    if audience in {"mt", "b2b"}:
        audience = "merchant"
    return role, audience


def extract_fact_keys(text: str) -> tuple[str, ...]:
    """Return stable fact keys present in a message or draft sentence."""
    keys: list[str] = []
    for pattern, key in _FACT_PATTERNS:
        if pattern.search(text) and key not in keys:
            keys.append(key)
    for order in _ORDER_RE.findall(text):
        token = f"order:{order.upper()}"
        if token not in keys:
            keys.append(token)
    for amount in _AMOUNT_RE.findall(text):
        compact = re.sub(r"\s+", "", amount.upper())
        token = f"amount:{compact}"
        if token not in keys:
            keys.append(token)
    return tuple(keys)


def _split_sentences(text: str) -> list[str]:
    return [part.strip() for part in _SENTENCE_RE.split(text) if part.strip()]


def _is_reference_sentence(sentence: str) -> bool:
    words = _WORD_RE.findall(sentence)
    if _REFERENCE_CUES.search(sentence) and len(words) <= 18:
        return True
    if len(words) <= 10 and _REFERENCE_CUES.search(sentence):
        return True
    return False


def build_thread_digest(
    case_input: str,
    thread_history: Iterable[str | Mapping[str, Any]] = (),
    *,
    recipient: str | None = None,
) -> ThreadDigest:
    """Build established / already-told / open-item digest for a ticket turn."""
    current = str(case_input or "")
    messages = [_normalize_message(item) for item in thread_history]
    # If history is empty, treat multi-block case captures as single current ask.
    established: list[ThreadFact] = []
    told_merchant: list[ThreadFact] = []
    told_internal: list[ThreadFact] = []

    for index, message in enumerate(messages):
        text = message["text"].strip()
        if not text:
            continue
        role, audience = _infer_roles(text, message["role"], message["audience"])
        keys = extract_fact_keys(text)
        if not keys:
            continue
        fact = ThreadFact(text[:280], keys, role, audience, index)
        established.append(fact)
        if audience == "merchant" or (role == "internal_cs" and audience == "merchant"):
            told_merchant.append(fact)
        if audience == "internal_cs" or role == "merchant":
            # Merchant statements are already known to CS; internal notes to CS are too.
            told_internal.append(fact)

    lowered_current = current.casefold()
    inferred_recipient = recipient
    if not inferred_recipient:
        if "merchant" in lowered_current or "mode c" in lowered_current:
            inferred_recipient = "merchant"
        else:
            inferred_recipient = "merchant" if told_merchant and "hi shakeel" not in lowered_current else "internal_cs"
            # Prefer merchant when drafting looks outbound or ticket is merchant-facing.
            if any(term in lowered_current for term in ("dear team", "harrods", "merchant enquiry", "b2b")):
                inferred_recipient = "merchant"
            if any(term in lowered_current for term in ("finance bridge", "internal note", "hi team")):
                inferred_recipient = "internal_cs"

    open_items = _open_items_from_ask(current, told_merchant if inferred_recipient == "merchant" else told_internal)
    return ThreadDigest(
        established=tuple(established),
        already_told_merchant=tuple(told_merchant),
        already_told_internal=tuple(told_internal),
        open_items=tuple(open_items),
        current_ask=current[:500],
        recipient=inferred_recipient,
    )


def _open_items_from_ask(ask: str, already_told: Iterable[ThreadFact]) -> list[str]:
    lowered = ask.casefold()
    told_keys = {key for fact in already_told for key in fact.fact_keys}
    items: list[str] = []

    wants_refund_status = any(term in lowered for term in ("refund status", "confirm the status", "confirm refund", "has not received the funds", "refund is showing"))
    wants_chargeback_outcome = any(term in lowered for term in ("chargeback outcome", "confirm chargeback", "still open", "dispute status", "advise further"))
    wants_favour = bool(re.search(r"\bfavou?r\b", lowered))
    wants_proof = any(term in lowered for term in ("proof of refund", "refund proof", "refund letter", "attach a screenshot"))
    wants_arn = "arn" in lowered

    if wants_refund_status and "no_refund_processed" not in told_keys:
        items.append("refund status still open")
    elif wants_refund_status and "no_refund_processed" in told_keys:
        # Status already told; only reopen if ask is specifically about funds not arriving despite portal
        if "not received" in lowered or "showing as processed" in lowered:
            items.append("clarify portal refund view vs no payout")
    if wants_favour:
        items.append("answer favour / whose-side question")
    if wants_chargeback_outcome:
        if "chargeback_reversed" not in told_keys and "dispute_pending" not in told_keys:
            items.append("chargeback outcome still open")
        elif "chargeback_exists" in told_keys and "chargeback_reversed" not in told_keys:
            items.append("chargeback outcome still open")
    if wants_proof and "arn_mentioned" not in told_keys:
        items.append("refund proof still open")
    if wants_arn and "arn_mentioned" not in told_keys:
        items.append("ARN still open")
    if not items and ("refund" in lowered or "chargeback" in lowered or "dispute" in lowered or "favou" in lowered):
        items.append("answer latest ask only")
    return items


_FINANCE_AS_THIRD_PARTY = re.compile(
    r"\bfinance\s+(?:will|should|needs?\s+to|must|to)\b",
    re.I,
)
_OPS_OWNER = re.compile(
    r"\b(?:ops|operations|warehouse|shipping|bermuda|fulfillment|fulfilment)\b"
    r".{0,50}\b(?:will|should|need to|needs to|must|to)\b"
    r"|\b(?:escalate|send|hand|route|pass)\b.{0,40}\b(?:ops|operations|warehouse|bermuda|shipping)\b"
    r"|\b(?:ops|operations|warehouse|bermuda)\b.{0,40}\b(?:to\s+)?(?:confirm|check|action|handle)\b",
    re.I,
)
_ASK_OPS = re.compile(r"\b(?:ops|operations|warehouse|bermuda|shipping|fulfillment|fulfilment)\b", re.I)


def validate_audience_scope(
    mode: str,
    text: str,
    current_ask: str = "",
) -> tuple[str, ...]:
    """Reject Mode B drafts that invent the wrong owner for the next step.

    Mode B is a note *to* CS/Finance. Saying "Finance will…" treats Finance as
    a third party. Inventing Ops/warehouse/bermuda next steps when the ask did
    not mention them is the same class of scope creep.
    """
    normalized_mode = str(mode or "").upper()
    if normalized_mode != "B":
        return ()
    body = str(text or "")
    if not body.strip():
        return ()
    reasons: list[str] = []
    if _FINANCE_AS_THIRD_PARTY.search(body):
        reasons.append(
            "audience scope: Mode B is for Finance/CS — do not say 'Finance will…'; "
            "state the next action directly"
        )
    ask = str(current_ask or "")
    if not _ASK_OPS.search(ask) and _OPS_OWNER.search(body):
        reasons.append(
            "audience scope: draft invents Ops/warehouse next steps outside the Finance ask"
        )
    return tuple(reasons)


def validate_delta_output(mode: str, text: str, digest: ThreadDigest) -> tuple[str, ...]:
    """Reject Mode B/C drafts that restate facts already told to the recipient."""
    normalized_mode = str(mode or "").upper()
    if normalized_mode not in {"B", "C"}:
        return ()
    if not digest.established and not digest.already_told_merchant and not digest.already_told_internal:
        return ()

    told = digest.fact_keys_for_recipient()
    if not told:
        return ()
    allowed = digest.open_fact_keys() | {key for key in told if key.startswith("order:")}
    # Order IDs alone are fine. Statuses AND amounts already told to this
    # recipient are not: Mode B/C must not replay merchant-stated figures or
    # prior "dispute closed / refund processed" lines.
    checkable_told = {key for key in told if not key.startswith("order:")}
    if not checkable_told:
        return ()

    restated: list[str] = []
    for sentence in _split_sentences(text):
        if _is_reference_sentence(sentence):
            continue
        keys = set(extract_fact_keys(sentence))
        overlap = (keys & checkable_told) - allowed
        # Outcome-specific keys supersede the generic "chargeback exists" restatement.
        if keys & {"chargeback_reversed", "dispute_pending", "second_chargeback_possible", "pre_arbitration"}:
            overlap.discard("chargeback_exists")
        # A new settlement amount may sit beside a half-sentence pointer; still
        # block bare replay of known amounts without a reference cue.
        if not overlap:
            continue
        words = _WORD_RE.findall(sentence)
        # Short pointers with a cue already handled; long overlap without cue = restatement
        if len(words) >= 8 and overlap:
            restated.extend(sorted(overlap))
        elif overlap and any(key.startswith("amount:") for key in overlap) and len(words) >= 5:
            restated.extend(sorted(key for key in overlap if key.startswith("amount:")))

    unique = tuple(dict.fromkeys(restated))
    if unique:
        return (
            f"Mode {normalized_mode} restates already-told thread facts: {', '.join(unique)}. "
            "Reference in half a sentence or omit; answer only open items.",
        )
    return ()
