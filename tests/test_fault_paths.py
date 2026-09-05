import unittest

from payment_forensics import CaseController, EvidenceItem, SearchResultState, ToolResult


class FaultPathTests(unittest.TestCase):
    def test_timeout_cannot_become_checked_coverage(self):
        controller = CaseController(case_id="R-TIMEOUT", identifiers=("GE-1",))
        controller.add_tool_result(ToolResult("Coralogix", SearchResultState.FAILED, True, error="timeout"), query="GE-1 refund", identifiers=("GE-1",))
        self.assertEqual(controller.snapshot()["coverage"]["Coralogix"], "FAILED")

    def test_stale_result_cannot_become_checked_coverage(self):
        controller = CaseController(case_id="R-STALE", identifiers=("GE-1",))
        controller.add_tool_result(ToolResult("Gateway", SearchResultState.RESULTS, True, stale=True, facts=(EvidenceItem(source="Gateway", source_type="payment", event_type="REFUND", amount="10.00", currency="EUR", order_id="GE-1"),)), query="GE-1 refund", identifiers=("GE-1",))
        self.assertEqual(controller.snapshot()["coverage"]["Gateway"], "FAILED")

    def test_duplicate_events_remain_auditable_but_ledger_deduplicates(self):
        controller = CaseController(case_id="R-DUP", identifiers=("GE-1",))
        item = EvidenceItem(source="Gateway", source_type="payment", event_type="REFUND", status="REFUNDED", amount="10.00", currency="EUR", timestamp="2026-01-01T10:00:00Z", order_id="GE-1", refund_id="ref-1")
        controller.add_evidence(item)
        controller.add_evidence(item)
        self.assertEqual(len(controller.snapshot()["evidence"]), 2)
        self.assertEqual(len(controller.snapshot()["derived_ledger"]["events"]), 1)


if __name__ == "__main__":
    unittest.main()
