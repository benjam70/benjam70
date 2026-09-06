import unittest

from payment_forensics.grammar import run_grammar_check


class GrammarCheckTests(unittest.TestCase):
    def test_missing_harper_is_safe_and_explicitly_skipped(self):
        result = run_grammar_check("Clean text.", executable="harper-not-installed")
        self.assertTrue(result.allowed)
        self.assertTrue(result.skipped)
        self.assertFalse(result.available)


if __name__ == "__main__":
    unittest.main()
