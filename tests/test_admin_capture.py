import unittest

from payment_forensics import extract_admin_capture_facts


class AdminCaptureTests(unittest.TestCase):
    def test_extracts_split_refund_facts_without_changing_capture(self):
        text = """RAW COPY CASE CAPTURE\nOrder: GE12113092766US\nRefund ID: 25786742\nCard refund €3.05 Completed\nGift Card refund €108.95 Failed: All gift cards failed on refund!\n"""
        facts = extract_admin_capture_facts(text)
        self.assertEqual(len(facts), 3)
        self.assertEqual(facts[0].refund_id, "25786742")
        self.assertEqual(facts[1].order_id, "GE12113092766US")
        self.assertEqual(facts[1].component, "card")
        self.assertEqual(facts[2].component, "gift_card")
        self.assertEqual(facts[2].status, "FAILED")
        self.assertEqual(facts[2].amount, "108.95")
        self.assertIn("All gift cards failed", facts[2].raw_fact)

    def test_ignores_non_lifecycle_amounts(self):
        facts = extract_admin_capture_facts("Order total: €319.99\nShipping: €24.99")
        self.assertEqual(facts, ())


if __name__ == "__main__":
    unittest.main()
