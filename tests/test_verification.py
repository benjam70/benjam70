"""Tests for CoVe, FineVerify, read-gate, and consistency checks."""

from __future__ import annotations

import unittest

from payment_forensics.verification import (
    SubClaimJudgment,
    claim_text_entailed_by_facts,
    decompose_subclaims,
    fineverify_score,
    read_gate_pending,
    run_accuracy_gates,
    score_subclaim,
    terminal_state_consistency,
)


class VerificationTests(unittest.TestCase):
    def test_subclaim_scores_refund_evidence(self):
        evidence = [{"event_type": "REFUND", "status": "REFUNDED", "amount": "100.00", "raw_fact": "refunded"}]
        result = score_subclaim("Was a provider-side refund executed?", evidence)
        self.assertEqual(result.judgment, SubClaimJudgment.SUPPORTED)

    def test_claim_entailment_requires_overlap(self):
        evidence = [{"event_type": "REFUND", "status": "REFUNDED", "amount": "100.00", "raw_fact": "refund completed"}]
        ok, _ = claim_text_entailed_by_facts("refund completed", (0,), evidence)
        self.assertTrue(ok)
        bad, reason = claim_text_entailed_by_facts("customer loves the product", (0,), evidence)
        self.assertFalse(bad)
        self.assertIn("not entailed", reason)

    def test_read_gate_pending(self):
        self.assertEqual(read_gate_pending((0, 1, 2), (0, 2)), (1,))

    def test_terminal_consistency_refund(self):
        result = terminal_state_consistency(
            terminal_state="Refunded",
            funds_location="refunded",
            evidence=[{"status": "REFUNDED", "event_type": "REFUND"}],
            secondary_terminal_state="Refunded",
        )
        self.assertTrue(result["consistent"])

    def test_accuracy_gates_pass_on_clean_refund(self):
        evidence = [{"event_type": "REFUND", "status": "REFUNDED", "amount": "100.00", "raw_fact": "refunded 100.00"}]
        claims = [{"text": "refunded 100.00", "fact_ids": [0]}]
        bundle = run_accuracy_gates(
            case_input="Refund for GE123",
            intent="refund_status",
            evidence=evidence,
            claims=claims,
            terminal_state="Refunded",
            funds_location="refunded",
            admitted_fact_ids=(0,),
            inspected_fact_ids=(0,),
        )
        self.assertTrue(bundle.allowed, bundle.reasons)
        self.assertGreaterEqual(len(bundle.cove), 2)
        score, _ = fineverify_score(bundle.subclaims)
        self.assertGreater(score, 0)

    def test_accuracy_gates_block_uninspected_facts(self):
        evidence = [{"event_type": "REFUND", "status": "REFUNDED", "raw_fact": "refunded"}]
        bundle = run_accuracy_gates(
            case_input="Refund for GE123",
            intent="refund_status",
            evidence=evidence,
            claims=(),
            terminal_state="Refunded",
            funds_location="refunded",
            admitted_fact_ids=(0,),
            inspected_fact_ids=(),
        )
        self.assertFalse(bundle.allowed)
        self.assertTrue(any("read-gate" in reason for reason in bundle.reasons))

    def test_decompose_includes_dispute_claim(self):
        claims = decompose_subclaims("chargeback opened", intent="dispute_status")
        self.assertTrue(any("dispute" in claim.casefold() or "chargeback" in claim.casefold() for claim in claims))


if __name__ == "__main__":
    unittest.main()
