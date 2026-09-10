"""Tests for avenue checklist and exhaustion control."""

from __future__ import annotations

import unittest

from payment_forensics.avenues import (
    PredicateStatus,
    RoundVerdict,
    build_avenue_checklist,
    classify_round_progress,
    exhaustion_certificate,
    open_avenues,
    required_triangulations,
    triangulation_gaps,
    update_avenues_from_state,
)


class AvenueTests(unittest.TestCase):
    def test_refund_case_builds_expected_predicates(self):
        avenues = build_avenue_checklist("Refund for GE12345678GB pi_123", identifiers=("GE12345678GB", "pi_123"), intent="refund_status")
        ids = {item.predicate_id for item in avenues}
        self.assertIn("identity", ids)
        self.assertIn("refund_execution", ids)
        self.assertIn("terminal_funds", ids)
        self.assertIn("disconfirm_active_hypotheses", ids)

    def test_dispute_case_adds_dispute_avenue(self):
        avenues = build_avenue_checklist("chargeback on order", identifiers=("GE1",), intent="dispute_status")
        self.assertTrue(any(item.predicate_id == "dispute_lifecycle" for item in avenues))

    def test_update_closes_refund_and_exhausts_missing_auth(self):
        avenues = build_avenue_checklist("Refund GE1 pi_1", identifiers=("GE1", "pi_1"), intent="refund_status")
        update_avenues_from_state(
            avenues,
            evidence=[{"event_type": "REFUND", "status": "REFUNDED", "amount": "10", "raw_fact": "refunded"}],
            searches=[
                {"source": "Gateway", "query": "refund", "result_state": "RESULTS"},
                {"source": "Coralogix", "query": "AUTHORISATION", "result_state": "NO_RESULT"},
            ],
            coverage={"Gateway": "CHECKED", "Coralogix": "CHECKED"},
            identifiers=("GE1", "pi_1"),
            terminal_state="Refunded",
            funds_location="refunded",
            hypotheses=(),
            negative_claims=(),
        )
        by_id = {item.predicate_id: item for item in avenues}
        self.assertEqual(by_id["identity"].status, PredicateStatus.SUPPORTED)
        self.assertEqual(by_id["refund_execution"].status, PredicateStatus.SUPPORTED)
        self.assertEqual(by_id["terminal_funds"].status, PredicateStatus.SUPPORTED)
        self.assertEqual(by_id["authorisation"].status, PredicateStatus.EXHAUSTED)
        self.assertEqual(open_avenues(avenues), ())

    def test_round_verdict_force_stale_when_no_progress(self):
        verdict = classify_round_progress(
            previous_open=3,
            current_open=3,
            new_fact_count=0,
            duplicate_search_count_delta=1,
            consecutive_no_novelty=2,
            forced_pivot=False,
        )
        self.assertEqual(verdict, RoundVerdict.QUERY_STALE)

    def test_triangulation_only_for_active_sources(self):
        rules = required_triangulations("refund missing", "refund_status")
        gaps = triangulation_gaps(
            {"Gateway": "CHECKED", "Coralogix": "NOT_CHECKED", "Admin": "NOT_CHECKED"},
            rules,
            available_sources=("Gateway", "Coralogix"),
        )
        self.assertTrue(any("refund_gateway_coralogix" in gap for gap in gaps))
        no_admin = triangulation_gaps(
            {"Gateway": "CHECKED", "Coralogix": "CHECKED", "Admin": "NOT_CHECKED"},
            rules,
            available_sources=("Gateway", "Coralogix"),
        )
        self.assertFalse(any("admin_gateway" in gap for gap in no_admin))

    def test_exhaustion_certificate(self):
        avenues = build_avenue_checklist("Refund GE1", identifiers=("GE1",), intent="refund_status")
        for avenue in avenues:
            avenue.status = PredicateStatus.EXHAUSTED
        cert = exhaustion_certificate(avenues, round_verdicts=("PRODUCTIVE", "EXHAUSTED"))
        self.assertTrue(cert["all_avenues_closed"])
        self.assertTrue(cert["ready_to_report"])


if __name__ == "__main__":
    unittest.main()
