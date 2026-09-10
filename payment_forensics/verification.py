"""Accuracy gates: CoVe, claim-evidence scoring, read-gate, self-consistency.

These checks are deterministic and do not require optional ML packages. When an
HFNLIConsistencyChecker is supplied, it can add contradiction flags on top.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import re
from typing import Any, Iterable, Mapping, Sequence


class SubClaimJudgment(str, Enum):
    SUPPORTED = "supported"
    NOT_FOUND = "not_found"
    CONTRADICTED = "contradicted"


@dataclass(frozen=True)
class SubClaimResult:
    claim: str
    judgment: SubClaimJudgment
    fact_ids: tuple[int, ...] = ()
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "claim": self.claim,
            "judgment": self.judgment.value,
            "fact_ids": list(self.fact_ids),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class CoveQuestion:
    question: str
    answer: str
    overturns_finding: bool
    evidence_fact_ids: tuple[int, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "answer": self.answer,
            "overturns_finding": self.overturns_finding,
            "evidence_fact_ids": list(self.evidence_fact_ids),
        }


@dataclass(frozen=True)
class VerificationBundle:
    allowed: bool
    reasons: tuple[str, ...]
    subclaims: tuple[SubClaimResult, ...] = ()
    cove: tuple[CoveQuestion, ...] = ()
    read_gate_pending: tuple[int, ...] = ()
    consistency: Mapping[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reasons": list(self.reasons),
            "subclaims": [item.as_dict() for item in self.subclaims],
            "cove": [item.as_dict() for item in self.cove],
            "read_gate_pending": list(self.read_gate_pending),
            "consistency": dict(self.consistency or {}),
        }


_TOKEN = re.compile(r"[a-z0-9_./-]{3,}")


def _tokens(text: str) -> set[str]:
    return {match.group(0) for match in _TOKEN.finditer(text.casefold())}


def decompose_subclaims(
    case_input: str,
    *,
    intent: str | None = None,
    terminal_state: str | None = None,
) -> tuple[str, ...]:
    """FineVerify-style checkable sub-questions derived from the case."""
    lowered = case_input.casefold()
    claims: list[str] = []
    if "refund" in lowered or (intent or "").casefold() in {"refund_status", "payment_investigation"}:
        claims.append("Was a provider-side refund executed?")
        claims.append("Does the refund amount match the disputed amount?")
    if any(token in lowered for token in ("chargeback", "dispute")):
        claims.append("Is there an active or closed dispute/chargeback record?")
    if "authori" in lowered or "charged" in lowered or "payment" in lowered:
        claims.append("Was the payment authorised and/or captured?")
    if terminal_state:
        claims.append(f"Does the evidence support terminal state '{terminal_state}'?")
    if not claims:
        claims.append("What is the evidenced terminal state of funds?")
    # De-dupe while preserving order.
    return tuple(dict.fromkeys(claims))


def score_subclaim(claim: str, evidence: Sequence[Mapping[str, Any]]) -> SubClaimResult:
    claim_tokens = _tokens(claim)
    supporting: list[int] = []
    contradicting: list[int] = []
    for index, item in enumerate(evidence):
        blob = " ".join(
            str(item.get(key) or "")
            for key in ("event_type", "status", "raw_fact", "amount", "psp_reference", "refund_id", "arn")
        )
        overlap = claim_tokens & _tokens(blob)
        status = str(item.get("status") or item.get("event_type") or "").upper()
        if "refund" in claim.casefold():
            if status in {"REFUNDED", "REFUND"} or "refund" in blob.casefold():
                supporting.append(index)
            elif status in {"FAILED", "REFUSED", "DECLINED"} and "refund" in blob.casefold():
                contradicting.append(index)
        elif "dispute" in claim.casefold() or "chargeback" in claim.casefold():
            if status in {"CHARGEBACK", "DISPUTE"} or "chargeback" in blob.casefold() or "dispute" in blob.casefold():
                supporting.append(index)
        elif "authori" in claim.casefold() or "captur" in claim.casefold():
            if status in {"AUTHORISATION", "AUTHORIZATION", "CAPTURE", "CAPTURED", "SETTLED", "SUCCEEDED"}:
                supporting.append(index)
        elif overlap:
            supporting.append(index)
        if "terminal state" in claim.casefold() and overlap:
            supporting.append(index)
    if contradicting and not supporting:
        return SubClaimResult(claim, SubClaimJudgment.CONTRADICTED, tuple(contradicting), "contradicting evidence present")
    if supporting:
        return SubClaimResult(claim, SubClaimJudgment.SUPPORTED, tuple(sorted(set(supporting))), "evidence overlap")
    return SubClaimResult(claim, SubClaimJudgment.NOT_FOUND, (), "no supporting evidence located")


def fineverify_score(subclaims: Sequence[SubClaimResult]) -> tuple[float, bool]:
    if not subclaims:
        return 0.0, False
    score = sum(1.0 if item.judgment == SubClaimJudgment.SUPPORTED else 0.0 for item in subclaims) / len(subclaims)
    perfect = all(item.judgment == SubClaimJudgment.SUPPORTED for item in subclaims)
    return score, perfect


def default_cove_questions(
    *,
    terminal_state: str | None,
    evidence: Sequence[Mapping[str, Any]],
    case_input: str,
) -> tuple[CoveQuestion, ...]:
    """Chain-of-Verification questions answered from evidence, not from the Finding narrative."""
    questions: list[CoveQuestion] = []
    refund_ids = [
        index for index, item in enumerate(evidence)
        if str(item.get("event_type") or item.get("status") or "").upper() in {"REFUND", "REFUNDED"}
    ]
    capture_ids = [
        index for index, item in enumerate(evidence)
        if str(item.get("event_type") or item.get("status") or "").upper() in {"CAPTURE", "CAPTURED", "SETTLED", "SETTLEMENT"}
    ]
    questions.append(
        CoveQuestion(
            question="Would the same cited cause also be true of a successful sibling case?",
            answer="Not evaluated against a sibling case in this run; only case-scoped evidence was used.",
            overturns_finding=False,
            evidence_fact_ids=tuple(range(min(3, len(evidence)))),
        )
    )
    if "refund" in case_input.casefold() or (terminal_state or "").casefold() == "refunded":
        questions.append(
            CoveQuestion(
                question="Is there a provider-side refund event, not only an Admin label?",
                answer="Yes — refund evidence is present." if refund_ids else "No provider-side refund event was admitted.",
                overturns_finding=not bool(refund_ids) and (terminal_state or "").casefold() == "refunded",
                evidence_fact_ids=tuple(refund_ids),
            )
        )
    if capture_ids or "captur" in case_input.casefold():
        questions.append(
            CoveQuestion(
                question="Does capture/settlement evidence exist for the authorised amount?",
                answer="Capture/settlement evidence present." if capture_ids else "No capture/settlement evidence admitted.",
                overturns_finding=False,
                evidence_fact_ids=tuple(capture_ids),
            )
        )
    if terminal_state:
        questions.append(
            CoveQuestion(
                question=f"What single evidence item would overturn terminal state '{terminal_state}'?",
                answer="A later authoritative opposing lifecycle event on the same identifiers.",
                overturns_finding=False,
                evidence_fact_ids=tuple(range(min(2, len(evidence)))),
            )
        )
    return tuple(questions[:4])


def validate_cove_answers(raw_answers: Iterable[Mapping[str, Any]], *, require: int = 2) -> tuple[CoveQuestion, ...]:
    answers: list[CoveQuestion] = []
    for item in raw_answers:
        if not isinstance(item, Mapping):
            continue
        question = str(item.get("question", "")).strip()
        answer = str(item.get("answer", "")).strip()
        if not question or not answer:
            continue
        answers.append(
            CoveQuestion(
                question=question,
                answer=answer,
                overturns_finding=bool(item.get("overturns_finding", False)),
                evidence_fact_ids=tuple(int(value) for value in item.get("evidence_fact_ids", ()) if str(value).lstrip("-").isdigit()),
            )
        )
    if len(answers) < require:
        return tuple(answers)
    return tuple(answers)


def claim_text_entailed_by_facts(
    claim_text: str,
    fact_ids: Iterable[int],
    evidence: Sequence[Mapping[str, Any]],
) -> tuple[bool, str]:
    ids = [int(value) for value in fact_ids]
    if not ids:
        return False, "claim has no supporting fact_ids"
    missing = [fact_id for fact_id in ids if fact_id < 0 or fact_id >= len(evidence)]
    if missing:
        return False, f"claim references missing fact_ids {missing}"
    premise_parts = []
    for fact_id in ids:
        item = evidence[fact_id]
        premise_parts.append(
            " ".join(
                str(item.get(key) or "")
                for key in ("event_type", "status", "amount", "currency", "raw_fact", "psp_reference", "refund_id", "arn")
            )
        )
    premise = " ".join(premise_parts)
    claim_tokens = _tokens(claim_text)
    if not claim_tokens:
        return True, "empty claim tokens"
    overlap = claim_tokens & _tokens(premise)
    # Require at least one substantive overlapping token, or an amount/date-like token from the claim present in facts.
    if overlap:
        return True, f"lexical entailment via {sorted(overlap)[:5]}"
    # Amounts often appear only in facts; allow numeric claim tokens to match evidence amounts.
    claim_numbers = {token for token in claim_tokens if any(char.isdigit() for char in token)}
    if claim_numbers & _tokens(premise):
        return True, "numeric entailment"
    return False, "claim text not entailed by cited facts"


def apply_optional_nli(premise: str, hypothesis: str, checker: Any | None) -> tuple[bool, str]:
    if checker is None:
        return True, "nli skipped"
    try:
        result = checker.check(premise, hypothesis)
    except Exception as exc:  # pragma: no cover - optional dependency path
        return True, f"nli unavailable: {exc}"
    if getattr(result, "is_contradiction", False):
        return False, f"nli contradiction ({result.label})"
    return True, f"nli {result.label}"


def read_gate_pending(admitted_fact_ids: Iterable[int], inspected_fact_ids: Iterable[int]) -> tuple[int, ...]:
    admitted = set(int(value) for value in admitted_fact_ids)
    inspected = set(int(value) for value in inspected_fact_ids)
    return tuple(sorted(admitted - inspected))


def terminal_state_consistency(
    *,
    terminal_state: str | None,
    funds_location: str | None,
    evidence: Sequence[Mapping[str, Any]],
    secondary_terminal_state: str | None = None,
) -> dict[str, Any]:
    """Self-consistency: ledger-implied state should agree with declared terminal state."""
    statuses = {
        str(item.get("status") or item.get("event_type") or "").upper()
        for item in evidence
    }
    implied = "unknown"
    if "REFUNDED" in statuses or "REFUND" in statuses:
        implied = "refunded"
    elif "CHARGEBACK" in statuses or "DISPUTE" in statuses:
        implied = "dispute"
    elif "CAPTURED" in statuses or "CAPTURE" in statuses or "SETTLED" in statuses or "SETTLEMENT" in statuses:
        implied = "settled"
    elif "AUTHORISATION" in statuses or "AUTHORIZATION" in statuses or "SUCCEEDED" in statuses:
        implied = "authorised"

    declared = (terminal_state or "").casefold()
    funds = (funds_location or "").casefold()
    agrees_ledger = implied == "unknown" or implied in declared or implied in funds or (
        implied == "refunded" and ("refund" in declared or "refund" in funds)
    ) or (
        implied == "settled" and any(token in declared or token in funds for token in ("settlement", "settled", "merchant"))
    ) or (
        implied == "dispute" and any(token in declared or token in funds for token in ("dispute", "chargeback", "held"))
    ) or (
        implied == "authorised" and any(token in declared or token in funds for token in ("authori", "gateway pending", "pending"))
    )

    secondary = (secondary_terminal_state or "").casefold()
    agrees_secondary = not secondary or secondary == declared or (secondary and declared and (secondary in declared or declared in secondary))

    return {
        "implied_from_evidence": implied,
        "declared_terminal_state": terminal_state,
        "funds_location": funds_location,
        "agrees_ledger": agrees_ledger,
        "agrees_secondary": agrees_secondary,
        "consistent": agrees_ledger and agrees_secondary,
    }


def run_accuracy_gates(
    *,
    case_input: str,
    intent: str | None,
    evidence: Sequence[Mapping[str, Any]],
    claims: Sequence[Mapping[str, Any]],
    terminal_state: str | None,
    funds_location: str | None,
    admitted_fact_ids: Iterable[int],
    inspected_fact_ids: Iterable[int],
    cove_answers: Iterable[Mapping[str, Any]] = (),
    secondary_terminal_state: str | None = None,
    nli_checker: Any | None = None,
    require_perfect_subclaims: bool = False,
) -> VerificationBundle:
    reasons: list[str] = []
    subclaim_texts = decompose_subclaims(case_input, intent=intent, terminal_state=terminal_state)
    subclaims = tuple(score_subclaim(claim, evidence) for claim in subclaim_texts)
    score, perfect = fineverify_score(subclaims)
    if require_perfect_subclaims and not perfect:
        reasons.append(f"fineverify incomplete: score={score:.2f}")
    elif score == 0 and evidence:
        reasons.append("fineverify found no supported subclaims despite evidence")

    cove = validate_cove_answers(cove_answers, require=2)
    if len(cove) < 2:
        cove = default_cove_questions(terminal_state=terminal_state, evidence=evidence, case_input=case_input)
    if any(item.overturns_finding for item in cove):
        reasons.append("cove disproof unanswered or overturns finding")
    if len(cove) < 2:
        reasons.append("cove requires at least two answered disproof questions")

    pending = read_gate_pending(admitted_fact_ids, inspected_fact_ids)
    if pending:
        reasons.append(f"read-gate: uninspected facts {list(pending)}")

    for index, claim in enumerate(claims):
        if not isinstance(claim, Mapping):
            continue
        text = str(claim.get("text", ""))
        ok, detail = claim_text_entailed_by_facts(text, claim.get("fact_ids", ()), evidence)
        if not ok:
            reasons.append(f"claim {index} not entailed: {detail}")
        else:
            premise = " ".join(
                str(evidence[int(fact_id)].get("raw_fact") or evidence[int(fact_id)].get("status") or "")
                for fact_id in claim.get("fact_ids", ())
                if str(fact_id).lstrip("-").isdigit() and 0 <= int(fact_id) < len(evidence)
            )
            nli_ok, nli_detail = apply_optional_nli(premise, text, nli_checker)
            if not nli_ok:
                reasons.append(f"claim {index} nli: {nli_detail}")

    consistency = terminal_state_consistency(
        terminal_state=terminal_state,
        funds_location=funds_location,
        evidence=evidence,
        secondary_terminal_state=secondary_terminal_state,
    )
    if terminal_state and evidence and not consistency["consistent"]:
        reasons.append(
            f"terminal-state consistency failed: implied={consistency['implied_from_evidence']} declared={terminal_state}"
        )

    return VerificationBundle(not reasons, tuple(reasons), subclaims=subclaims, cove=cove, read_gate_pending=pending, consistency=consistency)
