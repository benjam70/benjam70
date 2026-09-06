import unittest

from payment_forensics.slop_check import run_slop_check


class SlopCheckTests(unittest.TestCase):
    def test_missing_script_is_safe_and_explicitly_skipped(self):
        result = run_slop_check("Clean text.", script="nonexistent-slop-check.py")
        self.assertTrue(result.allowed)
        self.assertTrue(result.skipped)
        self.assertFalse(result.available)


if __name__ == "__main__":
    unittest.main()
