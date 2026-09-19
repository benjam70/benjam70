import unittest

from payment_forensics.coralogix_json_schema import infer_schema, summarize_fields


PAYJUSTNOW_SAMPLES = [
    {
        "checkoutPaymentStatus": "PAID_PENDING_CALLBACK",
        "paymentReference": "PJN-001",
        "merchantOrderReference": "GE1",
    },
    {
        "checkoutPaymentStatus": "SETTLED",
        "paymentReference": "PJN-002",
        "merchantOrderReference": "GE2",
    },
    {
        "checkoutPaymentStatus": "REFUNDED",
        "paymentReference": "PJN-003",
        "merchantOrderReference": "GE3",
        "refundAmount": 45.5,
        "refundReason": "customer_request",
    },
]


class CoralogixJsonSchemaTests(unittest.TestCase):
    def test_infer_schema_merges_all_samples(self):
        result = infer_schema(PAYJUSTNOW_SAMPLES)
        self.assertEqual(result["sample_count"], 3)
        self.assertIn("refundAmount", result["schema"]["properties"])

    def test_always_present_fields_are_flagged_correctly(self):
        fields = summarize_fields(PAYJUSTNOW_SAMPLES)
        by_name = {f.name: f for f in fields}
        self.assertTrue(by_name["checkoutPaymentStatus"].always_present)
        self.assertTrue(by_name["paymentReference"].always_present)

    def test_event_specific_fields_are_flagged_as_not_always_present(self):
        fields = summarize_fields(PAYJUSTNOW_SAMPLES)
        by_name = {f.name: f for f in fields}
        self.assertFalse(by_name["refundAmount"].always_present)
        self.assertFalse(by_name["refundReason"].always_present)
        self.assertEqual(by_name["refundAmount"].example, 45.5)

    def test_json_text_payloads_are_parsed_same_as_dicts(self):
        import json

        text_payloads = [json.dumps(p) for p in PAYJUSTNOW_SAMPLES]
        fields = summarize_fields(text_payloads)
        self.assertTrue(any(f.name == "checkoutPaymentStatus" for f in fields))

    def test_unparseable_entries_are_skipped_not_errored(self):
        mixed = PAYJUSTNOW_SAMPLES + ["not valid json", 42, None]
        result = infer_schema(mixed)
        self.assertEqual(result["sample_count"], 3)

    def test_empty_input_returns_empty(self):
        self.assertEqual(infer_schema([])["sample_count"], 0)
        self.assertEqual(summarize_fields([]), ())


if __name__ == "__main__":
    unittest.main()
