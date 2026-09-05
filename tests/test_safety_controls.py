import unittest

from payment_forensics import (
    EvidenceItem,
    check_startup_integrity,
    normalize_timestamp,
    redact_sensitive,
    run_cross_model_regression,
    validate_output,
)


class SafetyControlTests(unittest.TestCase):
    def test_startup_integrity_finds_authoritative_installation(self):
        self.assertTrue(check_startup_integrity().allowed)

    def test_timestamps_are_normalized_to_utc_when_admitted(self):
        item = EvidenceItem(source="Gateway", source_type="gateway", order_id="GE-1", timestamp="2026-01-01T12:00:00+02:00")
        from payment_forensics import CaseController
        controller = CaseController(case_id="R-SAFE", identifiers=("GE-1",))
        controller.add_evidence(item)
        self.assertEqual(controller.snapshot()["evidence"][0]["timestamp"], "2026-01-01T10:00:00Z")

    def test_sensitive_data_is_redacted_from_audit_material(self):
        redacted = redact_sensitive("PAN 4111 1111 1111 1111, cvv: 123, api_key=sk_test_12345678")
        self.assertNotIn("4111", redacted)
        self.assertNotIn("123", redacted)
        self.assertNotIn("sk_test_", redacted)

    def test_final_validator_blocks_card_data_in_every_mode(self):
        result = validate_output(mode="A", text="Card 4111111111111111", declared_fact_ids=(), approved_fact_ids=())
        self.assertFalse(result.allowed)

    def test_cross_model_runner_uses_the_same_fixtures(self):
        fixtures = (("clean", "case", lambda result: result == "ok"),)
        results = run_cross_model_regression({"codex": lambda _: "ok", "claude": lambda _: "ok"}, fixtures)
        self.assertEqual([(item.model_name, item.passed, item.failed) for item in results], [("codex", 1, 0), ("claude", 1, 0)])


if __name__ == "__main__":
    unittest.main()
