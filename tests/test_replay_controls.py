import unittest

from payment_forensics import CaseController, EvidenceItem, explain_replay_difference, reconcile_evidence


class ReplayControlTests(unittest.TestCase):
    def test_ledger_is_derived_from_evidence_and_deduplicates_exact_events(self):
        item = EvidenceItem(source="Admin", source_type="payment", event_type="CAPTURE", status="CAPTURED", amount="100.00", currency="EUR", order_id="GE-1", payment_id="pay-1", timestamp="2026-01-01T10:00:00Z", psp_reference="cap-1")
        result = reconcile_evidence([item.__dict__, item.__dict__], (0, 1))
        self.assertEqual(len(result["events"]), 1)

    def test_snapshot_can_be_restored(self):
        controller = CaseController(case_id="R-RESTORE", identifiers=("GE-1",))
        controller.add_evidence(EvidenceItem(source="Gateway", source_type="payment", event_type="REFUND", status="REFUNDED", amount="10.00", currency="EUR", order_id="GE-1", raw_fact="refund"))
        restored = CaseController.from_snapshot(controller.snapshot())
        self.assertEqual(restored.snapshot()["case_id"], "R-RESTORE")
        self.assertEqual(len(restored.snapshot()["evidence"]), 1)

    def test_replay_difference_ignores_recording_time(self):
        self.assertEqual(explain_replay_difference({"recorded_at": "a", "x": 1}, {"recorded_at": "b", "x": 1}), ())

    def test_phase_regression_is_ignored_and_logged(self):
        controller = CaseController(case_id="R-PHASE", identifiers=("GE-1",))
        controller.advance_phase("VALIDATE")
        controller.advance_phase("LIFECYCLE")
        self.assertEqual(controller.snapshot()["phase"], "VALIDATE")
        self.assertTrue(any(item["event"] == "phase_regression_ignored" for item in controller.snapshot()["event_log"]))


if __name__ == "__main__":
    unittest.main()
