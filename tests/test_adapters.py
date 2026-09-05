import unittest

from payment_forensics import JsonProposalModel, OpenAIResponsesModel, RegistrySearchExecutor, SearchResultState, ToolResult
from payment_forensics.engine import SearchRequest


class AdapterTests(unittest.TestCase):
    def test_json_proposal_model_decodes_structured_json(self):
        model = JsonProposalModel(lambda context: '{"complete": false, "searches": []}', lambda mode, context, fact_ids: "output")
        self.assertFalse(model.propose({})["complete"])
        self.assertEqual(model.render("A", {}, ()), "output")

    def test_registry_converts_missing_handler_to_failed(self):
        executor = RegistrySearchExecutor({})
        result = executor.search(SearchRequest("Coralogix", "order", ("GE-1",)))
        self.assertEqual(result.result_state, SearchResultState.FAILED)

    def test_registry_converts_transport_error_to_failed(self):
        def broken(request):
            raise TimeoutError("source timeout")

        result = RegistrySearchExecutor({"Gateway": broken}).search(SearchRequest("Gateway", "refund", ("GE-1",)))
        self.assertEqual(result.result_state, SearchResultState.FAILED)
        self.assertIn("source timeout", result.error)

    def test_production_proposal_schema_accepts_component_reconciliation(self):
        properties = OpenAIResponsesModel.PROPOSAL_SCHEMA["properties"]
        self.assertIn("component_lifecycle", properties)
        self.assertIn("provider_refund_results", properties)
        self.assertIn("amount_reconciliation", properties)
        self.assertIn("component_lifecycle", OpenAIResponsesModel.PROPOSAL_SCHEMA["required"])
        self.assertIn("provider_refund_results", OpenAIResponsesModel.PROPOSAL_SCHEMA["required"])
        self.assertIn("amount_reconciliation", OpenAIResponsesModel.PROPOSAL_SCHEMA["required"])


if __name__ == "__main__":
    unittest.main()
