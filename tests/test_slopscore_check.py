import unittest
from unittest import mock

from payment_forensics.slopscore_check import (
    SCORE_THRESHOLD,
    MIN_WORDS,
    prose_for_scoring,
    run_slopscore_check,
)


class SlopScoreCheckTests(unittest.TestCase):
    def test_prose_for_scoring_strips_mode_b_fence(self):
        text = "```\nYes. Order GE1 is in GE.\n```"
        self.assertEqual(prose_for_scoring(text), "Yes. Order GE1 is in GE.")

    def test_prose_for_scoring_keeps_mode_c_subject(self):
        text = "Order located: GE1\n```\nHello,\n\nThe order is GE1.\n```"
        prose = prose_for_scoring(text)
        self.assertIn("Order located: GE1", prose)
        self.assertIn("The order is GE1.", prose)

    def test_missing_package_is_safe_skip(self):
        import builtins

        real_import = builtins.__import__

        def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "slopscore" or name.startswith("slopscore."):
                raise ImportError("forced missing slopscore")
            return real_import(name, globals, locals, fromlist, level)

        with mock.patch("builtins.__import__", side_effect=fake_import):
            result = run_slopscore_check("Clean note.")
        self.assertTrue(result.allowed)
        self.assertTrue(result.skipped)
        self.assertFalse(result.available)
        self.assertTrue(any("not installed" in message for message in result.messages))

    def test_short_note_passes_even_with_high_score(self):
        class FakeReport:
            class score:
                slop_score = 95.0
                label = "mild"
                abstained = True

            class input:
                word_count = MIN_WORDS - 1

            evidence = ()

        class FakeScorer:
            def __init__(self, settings=None):
                pass

            def scan_text(self, text, source="<mode-bc>"):
                return FakeReport()

        with mock.patch("slopscore.core.SlopScorer", FakeScorer):
            result = run_slopscore_check("short bad note " * 5)
        self.assertTrue(result.allowed)
        self.assertEqual(result.score, 95.0)
        self.assertTrue(any("below" in message for message in result.messages))

    def test_long_high_score_is_rejected(self):
        class Evidence:
            def __init__(self, rule_id, span):
                self.rule_id = rule_id
                self.span = span

        class FakeReport:
            class score:
                slop_score = SCORE_THRESHOLD + 1
                label = "mild"
                abstained = False

            class input:
                word_count = MIN_WORDS

            evidence = (Evidence("FORMULAIC_WORTH_NOTING", "It is worth noting that"),)

        class FakeScorer:
            def __init__(self, settings=None):
                pass

            def scan_text(self, text, source="<mode-bc>"):
                return FakeReport()

        body = " ".join(f"word{i}" for i in range(MIN_WORDS))
        with mock.patch("slopscore.core.SlopScorer", FakeScorer):
            result = run_slopscore_check(f"```\n{body}\n```")
        self.assertFalse(result.allowed)
        self.assertTrue(any("exceeds threshold" in message for message in result.messages))
        self.assertTrue(any("FORMULAIC_WORTH_NOTING" in message for message in result.messages))

    def test_real_package_accepts_clean_mode_b_when_installed(self):
        note = (
            "```\n"
            "Yes. Order GE13327243221NL is in GE.\n"
            "Marion Dorges, Logitech EU, EUR 159.99 on 21/08/2026, Apple Pay Express, "
            "Settled on 24/08/2026 (ARN 74987506236003527430076).\n"
            "Status is Dispatched to customer (AWBs 876136273137 and 876236106530).\n\n"
            "Ticket installment numbers are not GE order IDs.\n"
            "Checkout opened that installment method twice, then deleted both attempts.\n"
            "Live payment is Apple Pay Express, funded by that installment bank, so the "
            "customer app shows Pay in 3 for this purchase.\n\n"
            "Customer told the installment provider the order was cancelled. GE still shows Dispatched.\n"
            "Only refund is EUR 0.00 on the free mouse pad (refund 26073041 on 09/09/2026). "
            "No money refund of EUR 159.99.\n\n"
            "Ship to is 276 Rue Paul Bert, Fontaine-Notre-Dame 59400, email marion.dorges@hotmail.com, "
            "not the ticket address or Marion.drgs spelling.\n\n"
            "Reply that the order is GE13327243221NL and Dispatched. The cancel claim does not match GE.\n"
            "```"
        )
        result = run_slopscore_check(note)
        if not result.available:
            self.skipTest("slopscore-lint not installed")
        self.assertTrue(result.allowed)
        self.assertIsNotNone(result.score)
        self.assertLess(result.score, SCORE_THRESHOLD)


if __name__ == "__main__":
    unittest.main()
