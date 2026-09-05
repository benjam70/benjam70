import unittest

from payment_forensics import validate_persona_trajectory, validate_persona_turn


class PersonaEvalTests(unittest.TestCase):
    def test_correction_is_acknowledged(self):
        result = validate_persona_turn("You're right to question that entry. It changes the conclusion.", correction=True)
        self.assertTrue(result.allowed)

    def test_new_evidence_is_connected(self):
        result = validate_persona_turn("The new evidence adds the ARN, so that part is now closed.", new_evidence=True)
        self.assertTrue(result.allowed)

    def test_missing_repair_signal_is_reported(self):
        result = validate_persona_trajectory([{"text": "The refund is complete.", "correction": True}])
        self.assertFalse(result.allowed)
        self.assertIn("correction was not acknowledged", result.reasons[0])


if __name__ == "__main__":
    unittest.main()
