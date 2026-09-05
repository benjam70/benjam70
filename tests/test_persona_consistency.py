import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DudleyPersonaTests(unittest.TestCase):
    def test_persona_contract_names_identity_and_boundaries(self):
        text = (ROOT / "DUDLEY_PERSONA.md").read_text(encoding="utf-8")
        for phrase in (
            "second pair of eyes",
            "Notice the detail that does not fit",
            "Conversational repair",
            "Personality must never add facts",
        ):
            self.assertIn(phrase, text)

    def test_examples_cover_correction_and_evidence_boundaries(self):
        text = (ROOT / "DUDLEY_EXAMPLES.md").read_text(encoding="utf-8")
        self.assertIn("right to question it", text)
        self.assertIn("remaining question", text)
        self.assertIn("does not prove", text)

    def test_humanizer_keeps_personality_inside_payment_safety_boundary(self):
        text = (ROOT / "prompts" / "humanize-payment-output.md").read_text(encoding="utf-8")
        self.assertIn("second-pair-of-eyes voice", text)
        self.assertIn("Never use personality to add warmth, jokes, opinions, certainty, or", text)
        self.assertIn("acknowledge the specific change", text)
        self.assertIn("answer the explicit request first", text)
        self.assertIn("detached model-language", text)


if __name__ == "__main__":
    unittest.main()
