import unittest

from payment_forensics import validate_claims, validate_humanized_draft, validate_output


class OutputValidatorTests(unittest.TestCase):
    def test_claims_require_approved_fact_ids(self):
        result = validate_claims(
            [{"text": "The refund failed", "fact_ids": [2]}], approved_fact_ids=(0,)
        )
        self.assertFalse(result.allowed)
        self.assertIn("claim 0 cites unapproved facts: 2", result.reasons)

    def test_claims_accept_approved_fact_ids(self):
        result = validate_claims(
            [{"text": "The refund failed", "fact_ids": [0]}], approved_fact_ids=(0,)
        )
        self.assertTrue(result.allowed)

    def test_field_assertion_must_match_evidence(self):
        evidence = [{"status": "REFUSED", "amount": "50.00"}]
        result = validate_claims(
            [{"text": "The refund succeeded", "fact_ids": [0], "field": "status", "expected_value": "SUCCESS"}],
            approved_fact_ids=(0,), evidence=evidence,
        )
        self.assertFalse(result.allowed)
        self.assertIn("claim 0 does not match its evidence assertion", result.reasons)

    def test_mode_a_preserves_existing_renderer_style(self):
        result = validate_output(
            mode="A",
            text="Mode A, approved facts (0,)",
            declared_fact_ids=(0,),
            approved_fact_ids=(0,),
        )
        self.assertTrue(result.allowed)

    def test_rejects_unapproved_facts(self):
        result = validate_output(
            mode="A", text="Finding", declared_fact_ids=(2,), approved_fact_ids=(0,)
        )
        self.assertFalse(result.allowed)
        self.assertIn("unapproved output facts: 2", result.reasons)

    def test_mode_b_requires_code_block_and_rejects_banned_language(self):
        result = validate_output(
            mode="B",
            text="The refund was successfully processed by us.",
            declared_fact_ids=(),
            approved_fact_ids=(),
        )
        self.assertFalse(result.allowed)
        self.assertTrue(any("banned Mode B term" in reason for reason in result.reasons))
        self.assertIn("Mode B must be inside a code block", result.reasons)

    def test_mode_c_rejects_gateway_name(self):
        result = validate_output(
            mode="C",
            text="Subject: Refund status\n\n```\nThe PayPal dispute remains open.\n```",
            declared_fact_ids=(0,),
            approved_fact_ids=(0,),
        )
        self.assertFalse(result.allowed)
        self.assertIn("gateway name not allowed in Mode C: PayPal", result.reasons)

    def test_mode_c_accepts_clean_email(self):
        result = validate_output(
            mode="C",
            text="Subject: Refund status\n\n```\nThe dispute remains open, so the refund cannot be processed.\n```",
            declared_fact_ids=(0,),
            approved_fact_ids=(0,),
        )
        self.assertTrue(result.allowed)

    def test_receipt_cannot_be_treated_as_payment_confirmation(self):
        evidence = [{"evidence_role": "customer_receipt", "event_type": None}]
        result = validate_claims(
            [{"text": "The customer was debited", "fact_ids": [0]}],
            approved_fact_ids=(0,), evidence=evidence,
        )
        self.assertFalse(result.allowed)
        self.assertIn("receipt as proof of payment lifecycle", " ".join(result.reasons))

    def test_receipt_cannot_be_dismissed_without_assessment(self):
        result = validate_output(
            mode="B", text="```\nThe customer's receipt adds no new information.\n```",
            declared_fact_ids=(0,), approved_fact_ids=(0,),
            evidence=[{"evidence_role": "customer_receipt"}],
        )
        self.assertFalse(result.allowed)
        self.assertIn("receipt cannot be dismissed", " ".join(result.reasons))

    def test_mode_c_sentence_limit(self):
        result = validate_output(
            mode="C",
            text="Subject: Refund status\n\n```\nThis sentence contains more than twenty words and must be rejected by the deterministic output validator before it reaches a merchant.\n```",
            declared_fact_ids=(),
            approved_fact_ids=(),
        )
        self.assertFalse(result.allowed)
        self.assertIn("Mode C sentence exceeds 20 words", result.reasons)

    def test_humanization_preserves_protected_payment_spans(self):
        original = "Refund GE123456789 completed on 2026-01-02. ARN 12345678901234567890."
        rewritten = "The refund for GE123456789 completed on 2026-01-02. ARN 12345678901234567890."
        self.assertTrue(validate_humanized_draft(original, rewritten).allowed)

    def test_humanization_rejects_changed_identifier(self):
        original = "Refund GE123456789 completed on 2026-01-02."
        rewritten = "Refund GE987654321 completed on 2026-01-02."
        result = validate_humanized_draft(original, rewritten)
        self.assertFalse(result.allowed)
        self.assertIn("protected span changed or removed: GE123456789", result.reasons)


if __name__ == "__main__":
    unittest.main()
