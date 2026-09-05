import unittest

from payment_forensics import run_vale


class ValeLinterTests(unittest.TestCase):
    def test_missing_vale_is_safe_and_explicitly_skipped(self):
        result = run_vale("Subject: Status\n\n```\nClean text.\n```", mode="C", executable="vale-not-installed")
        self.assertTrue(result.allowed)
        self.assertTrue(result.skipped)
        self.assertFalse(result.available)


if __name__ == "__main__":
    unittest.main()
