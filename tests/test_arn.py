import unittest

from payment_forensics import assess_arn_availability


class ArnAssessmentTests(unittest.TestCase):
    def test_amex_external_refund_gets_specific_explanation(self):
        result = assess_arn_availability("Payment Method ApplePay Express Co-branded: American Express Last status: RefundedExternally")
        self.assertEqual(result["status"], "NOT_EXPECTED")
        self.assertIn("American Express", result["reason"])
        self.assertIn("external acquirer", result["reason"])

    def test_unknown_method_stays_unresolved(self):
        result = assess_arn_availability("Payment Method Visa Last status: Refunded")
        self.assertEqual(result["status"], "UNRESOLVED")


if __name__ == "__main__":
    unittest.main()
