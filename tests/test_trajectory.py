import unittest

from payment_forensics import validate_trajectory


class TrajectoryValidationTests(unittest.TestCase):
    def test_required_sources_must_be_queried(self):
        result = validate_trajectory(
            [{"source": "Gateway", "result_state": "RESULTS"}],
            required_sources=("Gateway", "Coralogix"),
            completion_claimed=True,
        )
        self.assertFalse(result.allowed)
        self.assertIn("required source was not queried: coralogix", result.reasons)

    def test_partial_required_source_blocks_completion(self):
        result = validate_trajectory(
            [
                {"source": "Gateway", "result_state": "RESULTS"},
                {"source": "Coralogix", "result_state": "PARTIAL"},
            ],
            required_sources=("Gateway", "Coralogix"),
            completion_claimed=True,
        )
        self.assertFalse(result.allowed)
        self.assertIn("required source returned incomplete result: Coralogix", result.reasons)

    def test_complete_trajectory_is_allowed(self):
        result = validate_trajectory(
            [
                {"source": "Gateway", "result_state": "RESULTS"},
                {"source": "Coralogix", "result_state": "NO_RESULT"},
            ],
            required_sources=("Gateway", "Coralogix"),
            completion_claimed=True,
        )
        self.assertTrue(result.allowed)

    def test_required_tool_calls_include_case_identifiers(self):
        result = validate_trajectory(
            [{"source": "Coralogix", "query": "refund", "identifiers": ["GE-1"], "result_state": "RESULTS"}],
            required_sources=("Coralogix",), required_identifiers=("GE-1", "refund-1"), completion_claimed=True,
        )
        self.assertFalse(result.allowed)
        self.assertIn("tool call missing case identifier: refund-1 (Coralogix)", result.reasons)


if __name__ == "__main__":
    unittest.main()
