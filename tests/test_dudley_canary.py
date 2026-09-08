import unittest
from unittest.mock import patch

from tools.dudley_canary import (
    build_backends,
    run_canary,
    runnable_and_skipped_cases,
    tag_checkers,
)


class TagCheckerTests(unittest.TestCase):
    def setUp(self):
        self.checkers = tag_checkers()

    def test_date_tag(self):
        self.assertTrue(self.checkers["date"]("Refund confirmed 2026-01-01.", ""))
        self.assertFalse(self.checkers["date"]("Refund confirmed.", ""))

    def test_reference_tag(self):
        self.assertTrue(self.checkers["reference"]("Order GE12345678AB was refunded.", ""))
        self.assertFalse(self.checkers["reference"]("The order was refunded.", ""))

    def test_no_gateway_tag_blocks_internal_psp_names(self):
        self.assertFalse(self.checkers["no-gateway"]("Adyen confirmed the refund.", ""))
        self.assertTrue(self.checkers["no-gateway"]("Klarna confirmed the refund.", ""))

    def test_plain_language_tag_blocks_internal_jargon(self):
        self.assertFalse(self.checkers["plain-language"]("Checked mcp__Coralogix__query_dataprime.", ""))
        self.assertTrue(self.checkers["plain-language"]("Checked the payment logs.", ""))

    def test_no_new_facts_tag_flags_unsourced_amount(self):
        case_input = "Customer paid 50.00 EUR."
        self.assertTrue(self.checkers["no-new-facts"]("Refunded 50.00 EUR.", case_input))
        self.assertFalse(self.checkers["no-new-facts"]("Refunded 999.99 EUR.", case_input))

    def test_subject_tag(self):
        self.assertTrue(self.checkers["subject"]("Subject: Refund update\n\nBody text.", ""))
        self.assertFalse(self.checkers["subject"]("Refund update\n\nBody text.", ""))

    def test_terminal_state_tag(self):
        self.assertTrue(self.checkers["terminal-state"]("Funds were refunded to the customer.", ""))
        self.assertFalse(self.checkers["terminal-state"]("We are still looking into it.", ""))


class RunnableCaseDetectionTests(unittest.TestCase):
    def test_incomplete_shipped_cases_are_reported_as_skipped_not_run(self):
        cases = [
            {"id": "B-refund", "mode": "B", "tier": "FAST", "required": ["date", "refund"]},
        ]
        runnable, skipped = runnable_and_skipped_cases(cases)
        self.assertEqual(runnable, [])
        self.assertEqual(len(skipped), 1)
        self.assertIn("B-refund", skipped[0])

    def test_fully_specified_case_is_runnable(self):
        cases = [
            {"id": "B-refund", "required": ["date"], "case_input": "GE1 refund", "canned_results": {}},
        ]
        runnable, skipped = runnable_and_skipped_cases(cases)
        self.assertEqual(len(runnable), 1)
        self.assertEqual(skipped, [])


class BuildBackendsTests(unittest.TestCase):
    def test_no_keys_means_no_backends(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(build_backends(), {})

    def test_each_key_enables_its_backend(self):
        with patch.dict("os.environ", {"OPENAI_API_KEY": "x", "ANTHROPIC_API_KEY": "y", "GEMINI_API_KEY": "z"}):
            backends = build_backends()
        self.assertEqual(set(backends), {"openai", "claude", "gemini"})


class FakeCanaryModel:
    """A minimal ProposalModel that completes a case in one round, for testing the harness."""

    def propose(self, context):
        return {
            "searches": [
                {"source": "Gateway", "query": "refund", "identifiers": ["GE12345678AB"]},
                {"source": "Coralogix", "query": "GE12345678AB refund", "identifiers": ["GE12345678AB"]},
            ],
            "relevant_sources": ["Gateway", "Coralogix"],
            "identity_established": True,
            "lifecycle_checked": True,
            "terminal_state": {"state": "refunded", "funds_location": "refunded"},
            # The case_input text itself gets auto-parsed for an admin-capture-style
            # fact by extract_admin_capture_facts, independent of canned_results -
            # a real, pre-existing extraction step, not something this test controls.
            # It disagrees with the canned Gateway fact's status, so it must be
            # resolved like any other real contradiction, not just declared away.
            "contradiction_ids_resolved": [0],
            "fact_ids": [1],
            "complete": True,
        }

    def render(self, mode, context, fact_ids):
        return "Subject: Refund update\n\nOrder GE12345678AB was refunded 50.00 EUR on 2026-01-01."


class RunCanaryEndToEndTests(unittest.TestCase):
    def test_full_pipeline_passes_with_a_correct_fake_model(self):
        cases = [{
            "id": "B-refund",
            "required": ["date", "refund", "reference", "no-new-facts", "subject"],
            "case_input": "Customer says they paid 50.00 EUR for order GE12345678AB and want a refund status update.",
            "canned_results": {
                "Gateway": {
                    "result_state": "RESULTS",
                    "facts": [{
                        "source": "Gateway", "source_type": "gateway", "event_type": "REFUND",
                        "status": "REFUNDED", "amount": "50.00", "currency": "EUR",
                        "timestamp": "2026-01-01T10:00:00Z", "order_id": "GE12345678AB",
                        "raw_fact": "refund confirmed",
                    }],
                },
            },
        }]
        results = run_canary(cases, {"fake": lambda instructions: FakeCanaryModel()}, instructions="be dudley")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].model_name, "fake")
        self.assertEqual(results[0].failed, 0, results[0].failures)
        self.assertEqual(results[0].passed, 1)

    def test_full_pipeline_fails_when_output_leaks_a_gateway_name(self):
        class LeakyModel(FakeCanaryModel):
            def render(self, mode, context, fact_ids):
                return "Subject: Refund update\n\nAdyen confirmed the refund of 50.00 EUR on 2026-01-01 for GE12345678AB."

        cases = [{
            "id": "B-refund",
            "required": ["no-gateway"],
            "case_input": "Customer says they paid 50.00 EUR for order GE12345678AB and want a refund status update.",
            "canned_results": {
                "Gateway": {
                    "result_state": "RESULTS",
                    "facts": [{
                        "source": "Gateway", "source_type": "gateway", "event_type": "REFUND",
                        "status": "REFUNDED", "amount": "50.00", "currency": "EUR",
                        "timestamp": "2026-01-01T10:00:00Z", "order_id": "GE12345678AB",
                        "raw_fact": "refund confirmed",
                    }],
                },
            },
        }]
        results = run_canary(cases, {"fake": lambda instructions: LeakyModel()}, instructions="be dudley")
        self.assertEqual(results[0].failed, 1)


if __name__ == "__main__":
    unittest.main()
