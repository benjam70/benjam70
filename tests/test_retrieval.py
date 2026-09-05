import unittest

from payment_forensics import CandidateDocument, HybridCandidateIndex, EvidenceItem, RerankingSearchExecutor, SearchResultState, ToolResult
from payment_forensics.engine import SearchRequest


class RetrievalTests(unittest.TestCase):
    def test_lexical_fallback_works_without_hugging_face_dependencies(self):
        index = HybridCandidateIndex([
            CandidateDocument("refund", "refund attempt failed for payment", {}),
            CandidateDocument("capture", "capture completed for payment", {}),
        ])
        results = index.search("refund failed", limit=2)
        self.assertEqual(results[0].document.document_id, "refund")

    def test_empty_index_is_safe(self):
        self.assertEqual(HybridCandidateIndex().search("payment"), ())

    def test_reranking_wrapper_only_reorders_existing_facts(self):
        first = EvidenceItem(source="Gateway", source_type="gateway", order_id="GE-1", raw_fact="first")
        second = EvidenceItem(source="Gateway", source_type="gateway", order_id="GE-1", raw_fact="second")

        class FakeExecutor:
            def search(self, request):
                return ToolResult("Gateway", SearchResultState.RESULTS, True, facts=(first, second))

        class ReverseReranker:
            def rank(self, query, candidates):
                return (1, 0)

        result = RerankingSearchExecutor(FakeExecutor(), ReverseReranker()).search(SearchRequest("Gateway", "refund", ("GE-1",)))
        self.assertEqual(result.facts, (second, first))


if __name__ == "__main__":
    unittest.main()
