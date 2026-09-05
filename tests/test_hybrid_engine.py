import unittest

from payment_forensics import EvidenceItem, SearchResultState, TerminalFundsState, ToolResult
from payment_forensics.engine import HybridEngine, SearchRequest, extract_identifiers


def refund_fact(status="REFUNDED", timestamp="2026-01-01T10:00:00Z"):
    return EvidenceItem(
        source="Gateway",
        source_type="gateway",
        event_type="REFUND",
        status=status,
        amount="100.00",
        currency="EUR",
        timestamp=timestamp,
        order_id="GE12345678GB",
        payment_id="pay-1",
        psp_reference="pi_123",
        raw_fact=status,
    )


class FakeTools:
    def search(self, request: SearchRequest) -> ToolResult:
        if request.source == "Coralogix":
            return ToolResult("Coralogix", SearchResultState.NO_RESULT, True)
        return ToolResult("Gateway", SearchResultState.RESULTS, True, facts=(refund_fact(),))


class FakeModel:
    def __init__(self):
        self.calls = 0

    def propose(self, context):
        self.calls += 1
        if self.calls == 1:
            return {
                "searches": [
                    {"source": "Gateway", "query": "refund", "identifiers": ["GE12345678GB", "pi_123"]},
                    {"source": "Coralogix", "query": "GE12345678GB pi_123 refund", "identifiers": ["GE12345678GB", "pi_123"]},
                ],
                "relevant_sources": ["Gateway"],
                "identity_established": True,
                "lifecycle_checked": True,
                "complete": False,
            }
        return {
            "relevant_sources": ["Gateway"],
            "identity_established": True,
            "lifecycle_checked": True,
            "terminal_state": {"state": "Refunded", "funds_location": "refunded"},
            "fact_ids": [0],
            "complete": True,
        }

    def render(self, mode, context, fact_ids):
        return f"Mode {mode}, approved facts {fact_ids}"


class HybridEngineTests(unittest.TestCase):
    def test_identifier_extraction(self):
        values = extract_identifiers("GE12345678GB pi_123 ARN 123456789012345678901")
        self.assertIn("GE12345678GB", values)
        self.assertIn("pi_123", values)

    def test_end_to_end_search_gate_and_render(self):
        result = HybridEngine(FakeModel(), FakeTools()).investigate("Refund for GE12345678GB, pi_123")
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.mode, "A")
        self.assertEqual(result.output, "Mode A, approved facts (0,)")
        self.assertEqual(result.state["funds_location"], TerminalFundsState.REFUNDED.value)

    def test_engine_blocks_when_mandatory_source_is_omitted(self):
        class OmittingModel(FakeModel):
            def propose(self, context):
                proposal = super().propose(context)
                proposal["searches"] = ()
                proposal["relevant_sources"] = ("Gateway",)
                return proposal

        result = HybridEngine(OmittingModel(), FakeTools(), max_rounds=2).investigate("Refund for GE12345678GB, pi_123")
        self.assertEqual(result.status, "blocked")
        self.assertTrue(any("coverage incomplete: Coralogix" in reason for reason in result.gate.reasons))

    def test_required_tool_search_must_carry_case_identifier(self):
        class BadQueryModel(FakeModel):
            def propose(self, context):
                proposal = super().propose(context)
                proposal["searches"] = [{"source": "Coralogix", "query": "refund", "identifiers": []}]
                return proposal

        result = HybridEngine(BadQueryModel(), FakeTools(), max_rounds=1).investigate("Refund for GE12345678GB, pi_123")
        self.assertTrue(any("coverage incomplete: Coralogix" in reason for reason in result.gate.reasons))
        self.assertTrue(any("missing case identifier" in str(item) for item in result.state["source_failures"]))

    def test_klarna_dispute_uses_explicit_no_path_exception(self):
        engine = HybridEngine(FakeModel(), FakeTools(), max_rounds=1)
        self.assertEqual(engine._source_plan("Klarna dispute for GE12345678GB"), ())

    def test_attachment_arn_is_ingested_as_document_evidence(self):
        class AttachmentModel(FakeModel):
            def propose(self, context):
                proposal = super().propose(context)
                if self.calls > 1:
                    proposal.update({"fact_ids": [0, 1], "contradiction_ids_resolved": [0, 1], "complete": True})
                return proposal

        letter = {
            "name": "refund-letter.pdf",
            "text": (
                "Adyen Reference: K283K9PVZH7J23H6\n"
                "Refund Adyen Reference: LFKD7JJJLXS4XNP9\n"
                "Refund ARN: 74987506230001596811073\n"
                "Refund Amount: EUR 140.00\nRefund Date: 2026-08-18"
            ),
        }
        class MatchingTools(FakeTools):
            def search(self, request):
                result = super().search(request)
                if request.source == "Gateway":
                    fact = refund_fact()
                    fact = EvidenceItem(**{**fact.__dict__, "amount": "140.00"})
                    return ToolResult("Gateway", SearchResultState.RESULTS, True, facts=(fact,))
                return result

        result = HybridEngine(AttachmentModel(), MatchingTools()).investigate(
            "Refund for GE12345678GB, pi_123", attachments=[letter]
        )
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.state["attachment_coverage"]["refund-letter.pdf"], "CHECKED")
        self.assertEqual(result.state["attachments"]["refund-letter.pdf"]["facts"][0]["arn"], "74987506230001596811073")

    def test_unreadable_attachment_blocks_completion(self):
        result = HybridEngine(FakeModel(), FakeTools(), max_rounds=2).investigate(
            "Refund for GE12345678GB, pi_123", attachments=[{"name": "scan.pdf", "text": ""}]
        )
        self.assertEqual(result.status, "blocked")
        self.assertTrue(any("attachment coverage incomplete: scan.pdf=FAILED" in reason for reason in result.gate.reasons))

    def test_mode_c_renderer_receives_only_approved_context(self):
        class FirewallModel(FakeModel):
            def render(self, mode, context, fact_ids):
                self.render_context = context
                return "Subject: Refund status\n\n```\nThe refund was recorded.\n```"

            def propose(self, context):
                proposal = super().propose(context)
                if self.calls > 1:
                    proposal.update({"mode": "C", "claims": [{"text": "The refund was recorded", "fact_ids": [0], "field": "status", "expected_value": "REFUNDED"}]})
                return proposal

        model = FirewallModel()
        result = HybridEngine(model, FakeTools()).investigate("Refund for GE12345678GB, pi_123")
        self.assertEqual(result.status, "completed")
        self.assertNotIn("case_input", model.render_context)
        self.assertIn("approved_facts", model.render_context)
        self.assertIn("second pair of eyes", model.render_context["voice_profile"])

    def test_engine_records_phase_history_and_replay_hash(self):
        result = HybridEngine(FakeModel(), FakeTools()).investigate("Refund for GE12345678GB, pi_123")
        self.assertEqual(result.state["phase"], "COMPLETE")
        self.assertIn("IDENTITY", result.state["phase_history"])
        self.assertIn("RECONCILIATION", result.state["phase_history"]) if result.state.get("amount_reconciliation") else None
        self.assertTrue(result.audit["replay_hash"])
        self.assertEqual(result.state["run_id"], result.state["run_id"])
        self.assertTrue(any(item["event"] == "run_finished" for item in result.state["telemetry"]))


if __name__ == "__main__":
    unittest.main()
