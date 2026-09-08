import json
import unittest
from pathlib import Path

from tools.dudley_gate_check import evaluate, main


def _base_state(**overrides):
    state = {
        "case_id": "GE12345678AB",
        "identifiers": ["GE12345678AB"],
        "relevant_sources": ["Ticket", "Coralogix"],
        "coverage": {"Ticket": "CHECKED", "Coralogix": "CHECKED"},
        "evidence": [
            {"source": "Coralogix", "source_type": "log", "event_type": "REFUND", "status": "REFUNDED",
             "order_id": "GE12345678AB", "raw_fact": "refund confirmed"},
        ],
        "identity_established": True,
        "lifecycle_checked": True,
        "terminal_state": {"state": "refunded", "funds_location": "customer bank"},
    }
    state.update(overrides)
    return state


class GateCheckTests(unittest.TestCase):
    def test_complete_state_passes(self):
        allowed, reasons = evaluate(_base_state())
        self.assertTrue(allowed, reasons)
        self.assertEqual(reasons, ())

    def test_missing_coverage_fails(self):
        state = _base_state(coverage={"Ticket": "CHECKED"})
        allowed, reasons = evaluate(state)
        self.assertFalse(allowed)
        self.assertTrue(any("coverage incomplete" in reason for reason in reasons))

    def test_missing_terminal_state_fails(self):
        state = _base_state()
        del state["terminal_state"]
        allowed, reasons = evaluate(state)
        self.assertFalse(allowed)
        self.assertTrue(any("terminal_state not established" in reason for reason in reasons))

    def test_identity_not_established_fails(self):
        state = _base_state(identity_established=False)
        allowed, reasons = evaluate(state)
        self.assertFalse(allowed)
        self.assertTrue(any("identity not established" in reason for reason in reasons))

    def test_unresolved_negative_claim_fails(self):
        state = _base_state(negative_claims=[{"claim": "no chargeback found", "proven_absence": False}])
        allowed, reasons = evaluate(state)
        self.assertFalse(allowed)
        self.assertTrue(any("negative_claims insufficient coverage" in reason for reason in reasons))

    def test_negative_claim_missing_proven_absence_raises(self):
        from tools.dudley_gate_check import StateError

        state = _base_state(negative_claims=[{"claim": "no chargeback found"}])
        with self.assertRaises(StateError):
            evaluate(state)

    def test_bad_coverage_value_raises(self):
        from tools.dudley_gate_check import StateError

        state = _base_state(coverage={"Ticket": "SORT_OF"})
        with self.assertRaises(StateError):
            evaluate(state)

    def test_main_exits_zero_on_pass(self, tmp_path=None):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            path.write_text(json.dumps(_base_state()), encoding="utf-8")
            self.assertEqual(main([str(path)]), 0)

    def test_main_exits_one_on_fail(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            state = _base_state()
            del state["terminal_state"]
            path = Path(tmp) / "state.json"
            path.write_text(json.dumps(state), encoding="utf-8")
            self.assertEqual(main([str(path)]), 1)

    def test_main_exits_two_on_missing_file(self):
        self.assertEqual(main(["/no/such/file.json"]), 2)

    def test_non_integer_contradiction_id_raises_cleanly(self):
        from tools.dudley_gate_check import StateError

        state = _base_state(contradiction_ids_resolved=["not-an-int"])
        with self.assertRaises(StateError):
            evaluate(state)

    def test_non_object_state_raises_cleanly(self):
        from tools.dudley_gate_check import StateError

        with self.assertRaises(StateError):
            evaluate(["just", "a", "list"])

    def test_main_exits_two_not_crashes_on_malformed_state(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            path.write_text(json.dumps({"coverage": "not-a-dict"}), encoding="utf-8")
            self.assertEqual(main([str(path)]), 2)

    def test_unresolved_contradiction_between_evidence_fails(self):
        state = _base_state(evidence=[
            {"source": "Coralogix", "source_type": "log", "order_id": "GE12345678AB",
             "psp_reference": "pi_1", "status": "AUTHORISED", "raw_fact": "auth event"},
            {"source": "Gateway", "source_type": "log", "order_id": "GE12345678AB",
             "psp_reference": "pi_1", "status": "REFUSED", "raw_fact": "refusal event"},
        ])
        allowed, reasons = evaluate(state)
        self.assertFalse(allowed)
        self.assertTrue(any("contradictions unresolved" in reason for reason in reasons), reasons)

    def test_resolving_contradiction_by_id_passes(self):
        state = _base_state(evidence=[
            {"source": "Coralogix", "source_type": "log", "order_id": "GE12345678AB",
             "psp_reference": "pi_1", "status": "AUTHORISED", "raw_fact": "auth event"},
            {"source": "Gateway", "source_type": "log", "order_id": "GE12345678AB",
             "psp_reference": "pi_1", "status": "REFUSED", "raw_fact": "refusal event"},
        ], contradiction_ids_resolved=[0])
        allowed, reasons = evaluate(state)
        self.assertTrue(allowed, reasons)


if __name__ == "__main__":
    unittest.main()
