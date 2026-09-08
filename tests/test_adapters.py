import sys
import types
import unittest
from unittest.mock import patch

from payment_forensics import JsonProposalModel, LiteLLMModel, OpenAIResponsesModel, RegistrySearchExecutor, SearchResultState, ToolResult
from payment_forensics.engine import SearchRequest


def _fake_litellm(response_content, *, raise_on_response_format=False):
    module = types.ModuleType("litellm")

    def completion(**kwargs):
        if raise_on_response_format and "response_format" in kwargs:
            raise TypeError("response_format not supported for this model")
        return {"choices": [{"message": {"content": response_content}}]}

    module.completion = completion
    return module


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


class LiteLLMModelTests(unittest.TestCase):
    def test_propose_decodes_json_content(self):
        fake = _fake_litellm('{"complete": false, "searches": []}')
        with patch.dict(sys.modules, {"litellm": fake}):
            model = LiteLLMModel(instructions="be dudley", model="gemini/gemini-3-pro")
            proposal = model.propose({"case": "GE12345678AB"})
        self.assertFalse(proposal["complete"])

    def test_propose_strips_markdown_fence(self):
        fake = _fake_litellm('```json\n{"complete": true, "searches": []}\n```')
        with patch.dict(sys.modules, {"litellm": fake}):
            model = LiteLLMModel(instructions="be dudley", model="claude-opus-4-6")
            proposal = model.propose({})
        self.assertTrue(proposal["complete"])

    def test_propose_falls_back_when_response_format_unsupported(self):
        fake = _fake_litellm('{"complete": true, "searches": []}', raise_on_response_format=True)
        with patch.dict(sys.modules, {"litellm": fake}):
            model = LiteLLMModel(instructions="be dudley", model="some/unsupported-model")
            proposal = model.propose({})
        self.assertTrue(proposal["complete"])

    def test_render_returns_text_content(self):
        fake = _fake_litellm("Here is the note.")
        with patch.dict(sys.modules, {"litellm": fake}):
            model = LiteLLMModel(instructions="be dudley", model="gpt-5.2")
            output = model.render("B", {}, (1, 2))
        self.assertEqual(output, "Here is the note.")

    def test_model_defaults_to_env_var(self):
        with patch.dict("os.environ", {"DUDLEY_MODEL": "gemini/gemini-3-pro"}):
            model = LiteLLMModel(instructions="be dudley")
        self.assertEqual(model.model, "gemini/gemini-3-pro")


if __name__ == "__main__":
    unittest.main()
