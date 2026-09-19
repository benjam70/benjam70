import unittest

from payment_forensics.coralogix_templates import mine_templates


class CoralogixTemplateMiningTests(unittest.TestCase):
    def test_repeated_events_with_different_orders_merge_into_one_template(self):
        lines = [
            "Successfully saved PaymentTransactionMessage Response for Merchant Reference GE13144619284NL. Operation Type: Settle",
            "Successfully saved PaymentTransactionMessage Response for Merchant Reference GE13063238903GB. Operation Type: Refund",
            "Successfully saved PaymentTransactionMessage Response for Merchant Reference GE12602280838FR. Operation Type: Auth",
        ]
        clusters = mine_templates(lines)
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0].size, 3)
        self.assertIn("<ORDER_ID>", clusters[0].template)
        self.assertFalse(clusters[0].likely_noise)

    def test_single_unrelated_line_is_flagged_as_likely_noise(self):
        # Mirrors the real documented false positive: a code-review bot's log
        # mentioning the same class/method names as a genuine Amazon Pay
        # webhook handler, matched by keyword search but structurally unlike
        # every real event.
        lines = [
            "Successfully saved PaymentTransactionMessage Response for Merchant Reference GE13144619284NL. Operation Type: Settle",
            "Successfully saved PaymentTransactionMessage Response for Merchant Reference GE13063238903GB. Operation Type: Refund",
            "[CodeReviewBot] Example code: class AmazonPayV2Controller { PSPNotificationHandler(id) {...} }",
        ]
        clusters = mine_templates(lines)
        noise_clusters = [c for c in clusters if c.likely_noise]
        self.assertEqual(len(noise_clusters), 1)
        self.assertIn("CodeReviewBot", noise_clusters[0].example)

    def test_structurally_distinct_messages_stay_in_separate_clusters(self):
        lines = [
            "Skipping refund status update for status Refused under CORE-201546 async mode",
            "Skipping refund status update for status Refused under CORE-201546 async mode",
            "DLocalAlternativeController:DoWeHaveTheFunds - invalid fixer data",
            "DLocalAlternativeController:DoWeHaveTheFunds - invalid fixer data",
        ]
        clusters = mine_templates(lines)
        self.assertEqual(len(clusters), 2)
        self.assertTrue(all(c.size == 2 for c in clusters))

    def test_empty_lines_are_skipped_without_error(self):
        clusters = mine_templates(["", None, "Capture completed event was already sent"])
        self.assertEqual(len(clusters), 1)

    def test_clusters_are_sorted_largest_first(self):
        lines = (
            ["Order settled successfully"] * 5
            + ["One-off unrelated log line"]
        )
        clusters = mine_templates(lines)
        self.assertEqual(clusters[0].size, 5)
        self.assertLessEqual(clusters[-1].size, clusters[0].size)


if __name__ == "__main__":
    unittest.main()
