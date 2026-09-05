import unittest

from payment_forensics import CaseController, EvidenceItem, calibration_report, classify_review


class QualityControlTests(unittest.TestCase):
    def test_provenance_edge_is_persisted(self):
        controller = CaseController(case_id="R-PROV", identifiers=("GE-1",))
        controller.add_evidence(EvidenceItem(source="Gateway", source_type="payment", event_type="REFUND", status="REFUNDED", amount="10.00", currency="EUR", order_id="GE-1", raw_fact="refund"))
        self.assertTrue(controller.snapshot()["provenance_edges"])

    def test_review_is_classified(self):
        result = classify_review("Refund amount is 10.00", "Refund amount is 5.00", run_id="R1")
        self.assertEqual(result.error_type, "arithmetic_or_fact")

    def test_confidence_report(self):
        result = calibration_report(({"confidence": 0.9, "correct": True}, {"confidence": 0.9, "correct": False}))
        self.assertEqual(result["count"], 2)
        self.assertIsNotNone(result["brier_score"])


if __name__ == "__main__":
    unittest.main()
