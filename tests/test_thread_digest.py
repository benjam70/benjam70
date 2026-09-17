import unittest

from payment_forensics.thread_digest import build_thread_digest, extract_fact_keys, validate_delta_output
from payment_forensics.request_understanding import understand_ticket


class ThreadDigestTests(unittest.TestCase):
    def test_extracts_chargeback_and_no_refund_keys(self):
        keys = extract_fact_keys(
            "Please note that our system shows that no refunds have been processed. "
            "I see that there is a chargeback for this order."
        )
        self.assertIn("no_refund_processed", keys)
        self.assertIn("chargeback_exists", keys)

    def test_digest_marks_outbound_merchant_facts(self):
        history = [
            {
                "text": (
                    "Hi Shakeel, Please note that our system shows that no refunds have been processed. "
                    "I see that there is a chargeback for this order. Kind regards, Diana"
                ),
                "role": "internal_cs",
                "audience": "merchant",
            }
        ]
        digest = build_thread_digest(
            "Please confirm the chargeback outcome for merchant order GE12526416556GB",
            history,
            recipient="merchant",
        )
        self.assertTrue(digest.already_told_merchant)
        told = digest.fact_keys_for_recipient()
        self.assertIn("no_refund_processed", told)
        self.assertIn("chargeback_exists", told)
        self.assertTrue(any("chargeback outcome" in item for item in digest.open_items))

    def test_rejects_restating_already_told_chargeback(self):
        history = [
            {
                "text": (
                    "Hi Shakeel, Please note that our system shows that no refunds have been processed. "
                    "I see that there is a chargeback for this order. Kind regards, Diana"
                ),
                "role": "internal_cs",
                "audience": "merchant",
            }
        ]
        digest = build_thread_digest(
            "Confirm chargeback outcome GE12526416556GB customer has not received funds",
            history,
            recipient="merchant",
        )
        restating = """Hello Shakeel,

The customer disputed the charge with the card issuer instead.
A chargeback for GBP 1250.00 opened on 04/08/2026.
No refunds have been processed on this order.

Kind regards"""
        reasons = validate_delta_output("C", restating, digest)
        self.assertTrue(reasons)
        self.assertIn("already-told thread facts", reasons[0])

    def test_allows_delta_with_half_sentence_reference(self):
        history = [
            {
                "text": (
                    "Hi Shakeel, Please note that our system shows that no refunds have been processed. "
                    "I see that there is a chargeback for this order. Kind regards, Diana"
                ),
                "role": "internal_cs",
                "audience": "merchant",
            }
        ]
        digest = build_thread_digest(
            "Confirm chargeback outcome GE12526416556GB refund showing processed",
            history,
            recipient="merchant",
        )
        delta = """Hello Shakeel,

Update on the chargeback already flagged for GE12526416556GB.
On 09/09/2026 that chargeback was reversed.
The GBP 1250.00 returned to the merchant account for now.
Dispute status is still Pending while the issuer reviews the defense.
That stage is not final. A further chargeback from the issuer remains possible.
No Global-e refund sits behind the portal view mentioned.

Kind regards"""
        reasons = validate_delta_output("C", delta, digest)
        self.assertEqual(reasons, ())

    def test_understand_ticket_embeds_digest(self):
        result = understand_ticket(
            "Confirm chargeback outcome for merchant GE12526416556GB",
            thread_history=(
                {
                    "text": "Hi Shakeel, I see that there is a chargeback for this order.",
                    "role": "internal_cs",
                    "audience": "merchant",
                },
            ),
        )
        self.assertIn("thread_digest", result.as_dict())
        self.assertIn("avoid_repetition", result.conversation_acts)
        self.assertIn("chargeback_exists", result.already_known)


if __name__ == "__main__":
    unittest.main()
