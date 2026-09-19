import unittest

from payment_forensics.coralogix_fuzzy import rank_similar


class CoralogixFuzzyTests(unittest.TestCase):
    def test_typo_surfaces_the_real_value_first(self):
        matches = rank_similar(
            "AuthorizationFailed",
            ["AutherizationFailed", "Undefined", "Captured", "Refused"],
        )
        self.assertTrue(matches)
        self.assertEqual(matches[0].value, "AutherizationFailed")

    def test_unrelated_candidates_are_dropped_below_cutoff(self):
        matches = rank_similar("AuthorizationFailed", ["Undefined", "Captured"], score_cutoff=60.0)
        self.assertEqual(matches, ())

    def test_empty_term_or_candidates_returns_empty(self):
        self.assertEqual(rank_similar("", ["Undefined"]), ())
        self.assertEqual(rank_similar("term", []), ())

    def test_duplicate_candidates_are_deduped(self):
        matches = rank_similar("Refused", ["Refused", "Refused", "Undefined"])
        self.assertEqual(len(matches), 1)

    def test_limit_caps_result_count(self):
        matches = rank_similar(
            "Settled",
            ["Settled", "Settle", "Settlement", "Settles", "Undefined"],
            limit=2,
            score_cutoff=1.0,
        )
        self.assertLessEqual(len(matches), 2)


if __name__ == "__main__":
    unittest.main()
