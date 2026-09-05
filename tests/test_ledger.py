import unittest

from payment_forensics import PaymentEvent, reconcile_events, validate_provider_refund_response


class LedgerTests(unittest.TestCase):
    def test_provider_rejection_is_not_a_refund(self):
        result = validate_provider_refund_response({"refund": None, "userErrors": [{"message": "Transaction cannot be refunded"}]})
        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(result["classification"], "PROVIDER_REJECTED")

    def test_provider_refund_object_is_confirmed(self):
        result = validate_provider_refund_response({"refund": {"id": "gid://shopify/Refund/1"}, "userErrors": []})
        self.assertEqual(result["status"], "REFUNDED")
        self.assertEqual(result["provider_refund_id"], "gid://shopify/Refund/1")
    def test_uncaptured_authorization_is_deterministic(self):
        result = reconcile_events((
            PaymentEvent("AUTHORISATION", "319.99", "EUR"),
            PaymentEvent("CAPTURE", "295.00", "EUR"),
            PaymentEvent("REFUND", "295.00", "EUR"),
        ), adjustment_amount="24.99")
        self.assertEqual(result["classification"], "UNCAPTURED_AUTHORIZATION")
        self.assertEqual(result["uncaptured_authorization"], "24.99")

    def test_partial_refund_stays_unresolved(self):
        result = reconcile_events((
            PaymentEvent("CAPTURE", "100.00", "EUR"),
            PaymentEvent("REFUND", "40.00", "EUR"),
        ))
        self.assertEqual(result["classification"], "PARTIAL_OR_MISSING_REFUND")
        self.assertEqual(result["remaining"], "60.00")


if __name__ == "__main__":
    unittest.main()
