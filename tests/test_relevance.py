import sys
import unittest
from unittest import mock

from payment_forensics.relevance import CrossEncoderRelevanceChecker, RelevanceResult


class RelevanceCheckerTests(unittest.TestCase):
    def test_missing_sentence_transformers_raises_clear_error(self):
        with mock.patch.dict(sys.modules, {"sentence_transformers": None}):
            with self.assertRaises(RuntimeError):
                CrossEncoderRelevanceChecker()

    def test_relevance_result_threshold(self):
        result = RelevanceResult(score=0.8, threshold=0.5)
        self.assertTrue(result.is_relevant)
        result = RelevanceResult(score=0.3, threshold=0.5)
        self.assertFalse(result.is_relevant)


if __name__ == "__main__":
    unittest.main()
