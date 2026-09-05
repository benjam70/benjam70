import unittest

from payment_forensics import (
    CaseController,
    CoverageStatus,
    EvidenceItem,
    SearchResultState,
    TerminalFundsState,
    ToolResult,
)


def evidence(source, status, *, order="GE-1", payment="pay-1", amount="100.00", currency="EUR", timestamp="2026-01-01T10:00:00Z", priority=10, arn=None, refund=None):
    return EvidenceItem(
        source=source,
        source_type=source,
        event_type="REFUND" if "REFUND" in status else "CAPTURE",
        status=status,
        amount=amount,
        currency=currency,
        timestamp=timestamp,
        order_id=order,
        payment_id=payment,
        arn=arn,
        refund_id=refund,
        source_priority=priority,
        raw_fact=f"{source}:{status}:{timestamp}",
    )


class FullRegressionHarnessTests(unittest.TestCase):
    def test_r01_successful_refund(self):
        c = CaseController(case_id="R01", identifiers=("GE-1", "pay-1"))
        c.add_evidence(evidence("Gateway", "REFUNDED", arn="12345678901234567890"))
        c.set_terminal_state("Refunded", funds_location=TerminalFundsState.CUSTOMER_BANK)
        self.assertTrue(c.completion_gate(identity_established=True, relevant_sources=(), lifecycle_checked=True).allowed)

    def test_r02_failed_refund(self):
        c = CaseController(case_id="R02", identifiers=("GE-1", "pay-1"))
        c.add_evidence(evidence("Gateway", "FAILED"))
        c.set_terminal_state("Refund unresolved", funds_location=TerminalFundsState.GATEWAY_PENDING)
        self.assertTrue(c.completion_gate(identity_established=True, relevant_sources=(), lifecycle_checked=True).allowed)

    def test_r03_later_successful_retry(self):
        c = CaseController(case_id="R03", identifiers=("GE-1", "pay-1"))
        failed = c.add_evidence(evidence("Gateway", "FAILED"))
        later = c.add_evidence(evidence("Gateway", "REFUNDED", timestamp="2026-01-01T10:05:00Z"))
        self.assertTrue(c.link_retry(failed, later))

    def test_r04_open_dispute(self):
        c = CaseController(case_id="R04", identifiers=("GE-1", "pay-1"))
        c.add_evidence(evidence("Gateway", "REFUND_REFUSED"))
        c.set_terminal_state("Dispute held", funds_location=TerminalFundsState.DISPUTE_HELD)
        self.assertTrue(c.completion_gate(identity_established=True, relevant_sources=(), lifecycle_checked=True).allowed)

    def test_r05_duplicate_capture_is_disclosed(self):
        c = CaseController(case_id="R05", identifiers=("GE-1", "pay-1"))
        c.add_evidence(evidence("Gateway", "CAPTURED"))
        c.add_evidence(evidence("Gateway", "CAPTURED", timestamp="2026-01-01T10:01:00Z"))
        self.assertTrue(c.contradictions)

    def test_r06_partial_refund_same_currency(self):
        c = CaseController(case_id="R06", identifiers=("GE-1", "pay-1"))
        c.add_evidence(evidence("Gateway", "CAPTURED", amount="515.00"))
        c.add_evidence(evidence("Gateway", "REFUNDED", amount="500.00"))
        c.set_terminal_state("Partially refunded", funds_location=TerminalFundsState.CUSTOMER_BANK)
        self.assertEqual({item.currency for item in c.evidence}, {"EUR"})

    def test_r07_multiple_refunds_remain_separate(self):
        c = CaseController(case_id="R07", identifiers=("GE-1", "pay-1"))
        c.add_evidence(evidence("Gateway", "REFUNDED", amount="60.00", refund="refund-1"))
        c.add_evidence(evidence("Gateway", "REFUNDED", amount="40.00", timestamp="2026-01-01T10:01:00Z", refund="refund-2"))
        self.assertEqual(len(c.evidence), 2)

    def test_r08_admin_provider_conflict_stays_visible(self):
        c = CaseController(case_id="R08", identifiers=("GE-1", "pay-1"))
        c.add_evidence(evidence("Admin", "REFUNDED", priority=20))
        c.add_evidence(evidence("Gateway", "REFUSED", priority=100))
        self.assertTrue(any(item.field == "status" for item in c.contradictions))

    def test_r09_unrelated_buried_event_is_rejected(self):
        c = CaseController(case_id="R09", identifiers=("GE-1", "pay-1"))
        fact = evidence("Coralogix", "REFUNDED", order="OTHER", payment="other")
        c.add_tool_result(ToolResult("Coralogix", SearchResultState.RESULTS, True, facts=(fact,)), query="refund", identifiers=("GE-1", "pay-1"))
        self.assertEqual(c.evidence, [])

    def test_r10_missing_identifier_cannot_establish_identity(self):
        c = CaseController(case_id="R10", identifiers=())
        c.set_terminal_state("UNKNOWN", funds_location=TerminalFundsState.UNKNOWN)
        gate = c.completion_gate(identity_established=False, relevant_sources=(), lifecycle_checked=True)
        self.assertFalse(gate.allowed)

    def test_r11_currency_conflict_is_disclosed(self):
        c = CaseController(case_id="R11", identifiers=("GE-1", "pay-1"))
        c.add_evidence(evidence("Admin", "CAPTURED", currency="USD"))
        c.add_evidence(evidence("Gateway", "REFUNDED", currency="EUR"))
        self.assertTrue(any(item.field == "currency" for item in c.contradictions))

    def test_r12_partial_source_blocks_completion(self):
        c = CaseController(case_id="R12", identifiers=("GE-1", "pay-1"), required_sources=("Gateway", "Coralogix"))
        c.add_tool_result(ToolResult("Gateway", SearchResultState.RESULTS, True, facts=(evidence("Gateway", "REFUNDED"),)), query="refund", identifiers=("GE-1", "pay-1"))
        c.add_tool_result(ToolResult("Coralogix", SearchResultState.PARTIAL, True, truncated=True, error="timeout"), query="refund", identifiers=("GE-1", "pay-1"))
        c.set_terminal_state("Refunded", funds_location=TerminalFundsState.REFUNDED)
        gate = c.completion_gate(identity_established=True, relevant_sources=("Gateway", "Coralogix"), lifecycle_checked=True)
        self.assertFalse(gate.allowed)
        self.assertEqual(c.coverage["Coralogix"], CoverageStatus.PARTIAL)


if __name__ == "__main__":
    unittest.main()
