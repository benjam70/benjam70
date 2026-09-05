import unittest

from payment_forensics import (
    CaseController,
    CoverageStatus,
    EvidenceItem,
    SearchResultState,
    TerminalFundsState,
    ToolResult,
)


def fact(source, status, *, order_id="GE-1", payment_id="pay-1", timestamp="2026-01-01T10:00:00Z", priority=10, amount="100.00", currency="EUR"):
    return EvidenceItem(
        source=source,
        source_type=source,
        event_type="REFUND",
        status=status,
        amount=amount,
        currency=currency,
        timestamp=timestamp,
        order_id=order_id,
        payment_id=payment_id,
        source_priority=priority,
        raw_fact=f"{source}:{status}:{timestamp}",
    )


class PaymentForensicsControllerTests(unittest.TestCase):
    def test_negative_claim_requires_coverage_and_multiple_identifiers(self):
        controller = CaseController(case_id="R01", identifiers=("GE-1", "pay-1"))
        result = ToolResult("Gateway", SearchResultState.NO_RESULT, True)
        controller.add_tool_result(result, query="refund lookup", identifiers=("GE-1",))
        self.assertFalse(controller.record_negative_claim("no refund", source="Gateway", identifiers=("GE-1",), adequate_window=True, later_event_checked=True))
        self.assertTrue(controller.record_negative_claim("no refund", source="Gateway", identifiers=("GE-1", "pay-1"), adequate_window=True, later_event_checked=True))

    def test_later_successful_retry_supersedes_failure(self):
        controller = CaseController(case_id="R02", identifiers=("GE-1", "pay-1"))
        failed = controller.add_evidence(fact("Gateway", "FAILED"))
        succeeded = controller.add_evidence(fact("Gateway", "SUCCEEDED", timestamp="2026-01-01T10:05:00Z"))
        self.assertTrue(controller.link_retry(failed, succeeded))

    def test_admin_provider_conflicts_are_retained(self):
        controller = CaseController(case_id="R03", identifiers=("GE-1", "pay-1"))
        controller.add_evidence(fact("Admin", "REFUNDED", priority=20))
        controller.add_evidence(fact("Gateway", "REFUSED", priority=100))
        self.assertEqual(len(controller.evidence), 2)
        self.assertTrue(any(item.field == "status" for item in controller.contradictions))

    def test_partial_source_blocks_completion(self):
        controller = CaseController(case_id="R04", identifiers=("GE-1", "pay-1"), required_sources=("Gateway", "Coralogix"))
        controller.add_tool_result(ToolResult("Gateway", SearchResultState.RESULTS, True, facts=(fact("Gateway", "REFUNDED"),)), query="refund", identifiers=("GE-1", "pay-1"))
        controller.add_tool_result(ToolResult("Coralogix", SearchResultState.PARTIAL, True, truncated=True, error="timeout"), query="refund", identifiers=("GE-1", "pay-1"))
        controller.set_terminal_state("Refunded", funds_location=TerminalFundsState.REFUNDED)
        gate = controller.completion_gate(identity_established=True, relevant_sources=("Gateway", "Coralogix"))
        self.assertFalse(gate.allowed)
        self.assertIn("Coralogix=PARTIAL", " ".join(gate.reasons))

    def test_output_facts_are_ledger_approved_only(self):
        controller = CaseController(case_id="R05", identifiers=("GE-1",))
        accepted = controller.add_evidence(fact("Gateway", "REFUNDED"))
        rejected = controller.add_evidence(fact("Gateway", "REFUNDED", order_id="OTHER"))
        self.assertEqual(controller.validate_output_facts((accepted,)).allowed, True)
        self.assertEqual(controller.validate_output_facts((rejected,)).allowed, False)

    def test_terminal_state_is_required_even_with_clean_evidence(self):
        controller = CaseController(case_id="R06", identifiers=("GE-1", "pay-1"))
        controller.add_evidence(fact("Gateway", "REFUNDED"))
        gate = controller.completion_gate(identity_established=True, relevant_sources=(), lifecycle_checked=True)
        self.assertFalse(gate.allowed)
        controller.set_terminal_state("Refunded", funds_location=TerminalFundsState.REFUNDED)
        self.assertTrue(controller.completion_gate(identity_established=True, relevant_sources=(), lifecycle_checked=True).allowed)

    def test_explicit_unknown_terminal_state_is_allowed(self):
        controller = CaseController(case_id="R06B", identifiers=("GE-1",))
        controller.set_terminal_state("UNKNOWN", funds_location=TerminalFundsState.UNKNOWN)
        self.assertTrue(controller.completion_gate(identity_established=True, relevant_sources=(), lifecycle_checked=True).allowed)

    def test_query_execution_alone_does_not_count_as_checked(self):
        controller = CaseController(case_id="R07", identifiers=("GE-1",))
        controller.add_tool_result(ToolResult("Gateway", SearchResultState.RESULTS, False), query="refund", identifiers=("GE-1",))
        self.assertEqual(controller.coverage["Gateway"], CoverageStatus.FAILED)
        self.assertEqual(len(controller.evidence), 0)

    def test_empty_results_do_not_count_as_checked(self):
        controller = CaseController(case_id="R07B", identifiers=("GE-1",))
        controller.add_tool_result(ToolResult("Coralogix", SearchResultState.RESULTS, True), query="payment", identifiers=("GE-1",))
        self.assertEqual(controller.coverage["Coralogix"], CoverageStatus.FAILED)
        self.assertEqual(len(controller.evidence), 0)

    def test_archive_gap_marks_coralogix_partial(self):
        controller = CaseController(case_id="R07C", identifiers=("GE-1",))
        controller.add_tool_result(
            ToolResult("Coralogix", SearchResultState.RESULTS, True, error="Query completed but some archive data is missing"),
            query="source logs", identifiers=("GE-1",),
        )
        self.assertEqual(controller.coverage["Coralogix"], CoverageStatus.PARTIAL)

    def test_warning_metadata_marks_coralogix_partial(self):
        controller = CaseController(case_id="R07D", identifiers=("GE-1",))
        controller.add_tool_result(
            ToolResult("Coralogix", SearchResultState.NO_RESULT, True, warnings=("archiveWarning: missingData",)),
            query="source logs", identifiers=("GE-1",),
        )
        self.assertEqual(controller.coverage["Coralogix"], CoverageStatus.PARTIAL)

    def test_unproven_negative_claim_blocks_completion(self):
        controller = CaseController(case_id="R08B", identifiers=("GE-1", "pay-1"))
        controller.add_tool_result(
            ToolResult("Gateway", SearchResultState.NO_RESULT, True),
            query="refund", identifiers=("GE-1", "pay-1"),
        )
        controller.record_negative_claim(
            "no refund", source="Gateway", identifiers=("GE-1", "pay-1"),
            adequate_window=False, later_event_checked=False,
        )
        controller.set_terminal_state("UNKNOWN", funds_location=TerminalFundsState.UNKNOWN)
        gate = controller.completion_gate(identity_established=True, relevant_sources=("Gateway",), lifecycle_checked=True)
        self.assertFalse(gate.allowed)
        self.assertIn("negative_claims insufficient coverage", gate.reasons)

    def test_three_no_novelty_actions_require_replan(self):
        controller = CaseController(case_id="R13", identifiers=("GE-1", "pay-1"))
        for index in range(3):
            controller.add_tool_result(
                ToolResult("Gateway", SearchResultState.NO_RESULT, True),
                query=f"refund lookup {index}", identifiers=("GE-1", "pay-1"),
            )
        self.assertTrue(controller.snapshot()["replan_required"])
        controller.set_terminal_state("UNKNOWN", funds_location=TerminalFundsState.UNKNOWN)
        gate = controller.completion_gate(identity_established=True, relevant_sources=("Gateway",), lifecycle_checked=True)
        self.assertIn("search novelty exhausted: explicit re-plan required", gate.reasons)
        controller.accept_replan(True)
        self.assertFalse(controller.snapshot()["replan_required"])

    def test_new_evidence_resets_novelty_counter(self):
        controller = CaseController(case_id="R14", identifiers=("GE-1", "pay-1"))
        for index in range(2):
            controller.add_tool_result(
                ToolResult("Gateway", SearchResultState.NO_RESULT, True),
                query=f"refund lookup {index}", identifiers=("GE-1", "pay-1"),
            )
        controller.add_tool_result(
            ToolResult("Gateway", SearchResultState.RESULTS, True, facts=(fact("Gateway", "REFUNDED"),)),
            query="refund by payment", identifiers=("GE-1", "pay-1"),
        )
        self.assertEqual(controller.snapshot()["consecutive_no_novelty"], 0)
        self.assertFalse(controller.snapshot()["replan_required"])

    def test_receipt_mismatch_is_retained_as_separate_evidence(self):
        controller = CaseController(case_id="R15", identifiers=("GE-1", "pay-1"))
        controller.add_evidence(EvidenceItem(
            source="Ticket", source_type="customer", evidence_role="customer_receipt",
            amount="537489", currency="NGN", payment_method="bank transfer",
            order_id="GE-1", raw_fact="customer receipt",
        ))
        controller.add_evidence(EvidenceItem(
            source="Admin", source_type="payment", event_type="AUTHORISATION",
            amount="526950", currency="NGN", payment_method="Mastercard",
            order_id="GE-1", payment_id="pay-1", raw_fact="authorisation",
        ))
        relationship = controller.snapshot()["receipt_relationships"][0]
        self.assertEqual(relationship["status"], "MISMATCHED")
        self.assertIn("amount mismatch", relationship["reasons"])
        self.assertIn("payment method mismatch", relationship["reasons"])

    def test_ticket_intent_and_prior_statement_controls(self):
        controller = CaseController(case_id="R16", identifiers=("GE-1",))
        controller.set_ticket_intent("refund_status")
        controller.record_previously_stated_facts(("The refund was rejected.",))
        self.assertEqual(controller.snapshot()["ticket_intent"], "refund_status")
        self.assertTrue(controller.repeated_statement_reasons([{ "text": "The refund was rejected." }]))

    def test_failed_refund_component_blocks_completion(self):
        controller = CaseController(case_id="R17", identifiers=("GE-1",))
        controller.record_component_state("gift_card", "FAILED", amount="139.99", currency="GBP")
        controller.set_terminal_state("Refunded", funds_location=TerminalFundsState.REFUNDED)
        gate = controller.completion_gate(identity_established=True, relevant_sources=(), lifecycle_checked=True)
        self.assertFalse(gate.allowed)
        self.assertIn("component lifecycle unresolved", gate.reasons)

    def test_structured_component_evidence_updates_controller_state(self):
        controller = CaseController(case_id="R18", identifiers=("GE-1",))
        controller.add_evidence(EvidenceItem(
            source="Gateway", source_type="refund", event_type="REFUND", status="FAILED",
            order_id="GE-1", component="gift_card", raw_fact="gift card refund failed",
        ))
        self.assertEqual(controller.snapshot()["component_lifecycle"]["gift_card"]["status"], "FAILED")

    def test_provider_rejection_blocks_admin_completed_aggregate(self):
        controller = CaseController(case_id="R-PROVIDER", identifiers=("GE-1",))
        controller.record_component_state("card", "REFUNDED", amount="3.05", currency="ILS")
        controller.record_provider_refund_result("gift_card", {"refund": None, "userErrors": [{"message": "The refund could not be processed"}]})
        controller.set_terminal_state("Refunded", funds_location=TerminalFundsState.REFUNDED)
        gate = controller.completion_gate(identity_established=True, relevant_sources=(), lifecycle_checked=True)
        self.assertFalse(gate.allowed)
        self.assertIn("provider refund response unresolved", gate.reasons)

    def test_older_component_state_cannot_overwrite_newer_state(self):
        controller = CaseController(case_id="R-STALE", identifiers=("GE-1",))
        controller.record_component_state("card", "REFUNDED", timestamp="2026-09-05T12:00:00Z")
        controller.record_component_state("card", "FAILED", timestamp="2026-09-05T11:00:00Z")
        self.assertEqual(controller.component_lifecycle["card"]["status"], "REFUNDED")

    def test_amount_reconciliation_blocks_unmapped_refund_amount(self):
        controller = CaseController(case_id="R19", identifiers=("GE-1",))
        result = controller.reconcile_amounts(
            paid_total="885.60", refund_total="676.60", currency="SAR",
            transactions=({"amount": "209.00", "status": "REFUNDED"},),
        )
        self.assertEqual(result["remaining"], "209.00")
        self.assertEqual(result["status"], "UNRESOLVED")
        controller.set_terminal_state("Refunded", funds_location=TerminalFundsState.REFUNDED)
        gate = controller.completion_gate(identity_established=True, relevant_sources=(), lifecycle_checked=True)
        self.assertFalse(gate.allowed)

    def test_authorized_but_uncaptured_difference_is_not_a_missing_refund(self):
        controller = CaseController(case_id="R-AUTH", identifiers=("GE-1",))
        result = controller.reconcile_authorization_gap(
            authorized_total="319.99", captured_total="295.00", refunded_total="295.00",
            adjustment_amount="24.99", currency="EUR",
        )
        self.assertEqual(result["status"], "UNCAPTURED_AUTHORIZATION")
        self.assertEqual(result["uncaptured_authorization"], "24.99")
        self.assertFalse(result["bank_release_verified"])
        controller.set_terminal_state("Refunded", funds_location=TerminalFundsState.REFUNDED, lifecycle_checked=True)
        self.assertTrue(controller.completion_gate(identity_established=True, relevant_sources=(), lifecycle_checked=True).allowed)


if __name__ == "__main__":
    unittest.main()
