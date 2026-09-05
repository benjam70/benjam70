import unittest

from payment_forensics import understand_ticket, unanswered_after_draft, validate_ticket_answer


class RequestUnderstandingTests(unittest.TestCase):
    def test_ticket_can_have_multiple_requests(self):
        result = understand_ticket("Please confirm the refund and provide the ARN for GE12345678GB")
        self.assertEqual(result.primary_intent, "provide_refund_arn")
        self.assertIn("confirm_refund_status", result.secondary_intents)
        self.assertIn("arn", result.requested_artifacts)
        self.assertIn("refund_status", result.requested_artifacts)

    def test_missing_requested_arn_blocks_draft(self):
        result = understand_ticket("Do we have an ARN for the refund?")
        reasons = validate_ticket_answer(result, "The refund was completed.")
        self.assertIn("ticket requested an ARN", " ".join(reasons))

    def test_known_arn_is_retained(self):
        result = understand_ticket("Refund ARN 12345678901234567890")
        self.assertIn("12345678901234567890", result.known_facts)

    def test_ledgers_slots_and_history_are_preserved(self):
        result = understand_ticket(
            "Please provide the ARN for refund ID 24606960. The refund was AUD 426.20 on 2026-07-11.",
            thread_history=("Please investigate the refund for GE12345678GB.",),
        )
        self.assertIn("arn", result.explicitly_requested)
        self.assertIn("AUD 426.20", result.slots["amounts"])
        self.assertIn("2026-07-11", result.slots["dates"])
        self.assertIn("24606960", result.slots["refund_ids"])
        self.assertEqual(result.original_primary_intent, "confirm_refund_status")
        self.assertEqual(result.current_primary_intent, "provide_refund_arn")
        self.assertTrue(result.still_unanswered)
        self.assertEqual(unanswered_after_draft(result, "The refund was completed. ARN 12345678901234567890."), ())


if __name__ == "__main__":
    unittest.main()
