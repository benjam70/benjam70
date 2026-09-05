import unittest

import tempfile
from pathlib import Path

from payment_forensics import (
    EvidenceItem,
    check_host_integration,
    check_startup_integrity,
    normalize_timestamp,
    redact_sensitive,
    run_cross_model_regression,
    validate_output,
)


class SafetyControlTests(unittest.TestCase):
    def test_startup_integrity_finds_authoritative_installation(self):
        self.assertTrue(check_startup_integrity().allowed)

    def test_startup_integrity_is_independent_of_any_host_wiring(self):
        # A checkout with no Codex or Claude Code integration files at all
        # (e.g. a bare Cursor checkout, or CI) must still pass, since none
        # of those files affect what the engine loads or executes.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "payment_forensics").mkdir()
            for name in ("controller.py", "engine.py", "output_validator.py"):
                (root / "payment_forensics" / name).write_text("", encoding="utf-8")
            skill_dir = root / ".agents" / "skills" / "payment-forensics"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(
                "RULE 0\nMODE B\nMODE C\nSOURCE-TAG RULE\nCoralogix\n", encoding="utf-8"
            )
            humanizer_dir = root / ".agents" / "skills" / "automatic-humanizer"
            humanizer_dir.mkdir(parents=True)
            (humanizer_dir / "SKILL.md").write_text("humanizer", encoding="utf-8")

            self.assertTrue(check_startup_integrity(root).allowed)

    def test_host_integration_reports_missing_host_without_failing_engine_integrity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = check_host_integration(root)

            self.assertIn("claude_code", report)
            self.assertIn("codex", report)
            self.assertEqual(report["codex"].present, ())
            self.assertTrue(report["codex"].missing)
            self.assertEqual(report["claude_code"].present, ())
            self.assertTrue(report["claude_code"].missing)
            # Absence of every host's wiring is informational only and must
            # never be reflected by check_startup_integrity.
            self.assertTrue(check_startup_integrity(root).allowed is False)  # no engine files here either
            for name in ("controller.py", "engine.py", "output_validator.py"):
                (root / "payment_forensics").mkdir(exist_ok=True)
                (root / "payment_forensics" / name).write_text("", encoding="utf-8")
            skill_dir = root / ".agents" / "skills" / "payment-forensics"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(
                "RULE 0\nMODE B\nMODE C\nSOURCE-TAG RULE\nCoralogix\n", encoding="utf-8"
            )
            (root / ".agents" / "skills" / "automatic-humanizer").mkdir(parents=True)
            (root / ".agents" / "skills" / "automatic-humanizer" / "SKILL.md").write_text("humanizer", encoding="utf-8")
            self.assertTrue(check_startup_integrity(root).allowed)

    def test_host_integration_flags_skill_copy_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agents_skill = root / ".agents" / "skills" / "payment-forensics"
            agents_skill.mkdir(parents=True)
            (agents_skill / "SKILL.md").write_text("authoritative", encoding="utf-8")
            claude_skill = root / ".claude" / "skills" / "payment-forensics"
            claude_skill.mkdir(parents=True)
            (claude_skill / "SKILL.md").write_text("drifted copy", encoding="utf-8")

            report = check_host_integration(root)
            self.assertFalse(report["claude_code"].skill_copies_match)

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
