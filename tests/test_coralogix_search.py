import unittest

from payment_forensics import SearchRequest, SearchResultState, ToolResult, assess_query, alternate_queries, result_quality, time_sliced_queries


class CoralogixSearchTests(unittest.TestCase):
    def test_query_quality_requires_identifier_and_window(self):
        quality = assess_query(SearchRequest("Coralogix", "refund", ()))
        self.assertFalse(quality.allowed)
        self.assertIn("no case identifier supplied", quality.reasons)

    def test_alternates_are_identifier_and_event_specific(self):
        request = SearchRequest("Coralogix", "source logs | filter $d ~ 'GE-1'", ("GE-1", "pay-1"), "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z")
        variants = alternate_queries(request)
        self.assertTrue(any("eventCode=REFUND" in item.query for item in variants))
        self.assertTrue(all(item.start_date and item.end_date for item in variants))

    def test_result_quality_rejects_empty_success_result(self):
        quality = result_quality(ToolResult("Coralogix", SearchResultState.RESULTS, True))
        self.assertFalse(quality.allowed)
        self.assertIn("result has no normalized facts", quality.reasons)

    def test_alternates_include_dataprime_and_field_aware_queries(self):
        request = SearchRequest("Coralogix", "source logs | filter $d ~ 'GE-1'", ("GE-1",), "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z")
        variants = alternate_queries(request)
        self.assertTrue(any(item.query_language == "dataprime" for item in variants))
        self.assertTrue(any("refundId" in item.query or "orderId" in item.query for item in variants))

    def test_long_windows_are_split_into_explicit_utc_slices(self):
        request = SearchRequest("Coralogix", "source logs | filter $d ~ 'GE-1'", ("GE-1",), "2025-08-04T00:00:00Z", "2026-09-04T23:59:59Z")
        slices = time_sliced_queries(request, max_slices=4)
        self.assertEqual(len(slices), 4)
        self.assertEqual(slices[0].start_date, "2025-08-04T00:00:00Z")
        self.assertEqual(slices[-1].end_date, "2026-09-04T23:59:59Z")
        self.assertTrue(all(item.start_date and item.end_date for item in slices))

    def test_archive_gap_is_not_accepted_as_checked_coverage(self):
        result = ToolResult("Coralogix", SearchResultState.RESULTS, True, error="archive data is missing")
        quality = result_quality(result)
        self.assertFalse(quality.allowed)
        self.assertIn("archive or coverage gap reported", quality.reasons)

    def test_fuzzy_double_tilde_is_flagged(self):
        request = SearchRequest("Coralogix", "source logs | filter $d ~~ 'refnd'", ("GE-1",), "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z")
        quality = assess_query(request)
        self.assertTrue(any("fuzzy operator ~~" in reason for reason in quality.reasons))

    def test_lucene_fuzzy_suffix_is_flagged(self):
        request = SearchRequest(
            "Coralogix",
            'source logs | lucene \'finalTransactionStatus:refund~1\'',
            ("GE-1",),
            "2026-01-01T00:00:00Z",
            "2026-01-02T00:00:00Z",
            query_language="lucene",
        )
        quality = assess_query(request)
        self.assertTrue(any("hard 400" in reason for reason in quality.reasons))

    def test_compound_negated_regex_is_flagged(self):
        request = SearchRequest(
            "Coralogix",
            "source logs payment | filter status == 'x' || reason !~ 'y'",
            ("GE-1",),
            "2026-01-01T00:00:00Z",
            "2026-01-02T00:00:00Z",
        )
        quality = assess_query(request)
        self.assertTrue(any("compound filter" in reason for reason in quality.reasons))

    def test_ge_correlation_id_is_flagged(self):
        request = SearchRequest(
            "Coralogix",
            "source logs payment | filter GECorrelationId == 'GE1'",
            ("GE-1",),
            "2026-01-01T00:00:00Z",
            "2026-01-02T00:00:00Z",
        )
        quality = assess_query(request)
        self.assertTrue(any("batch-job run ID" in reason for reason in quality.reasons))

    def test_nested_dotted_path_is_flagged_as_advisory(self):
        request = SearchRequest(
            "Coralogix",
            "source logs payment | filter $d.userData.refund == 'x'",
            ("GE-1",),
            "2026-01-01T00:00:00Z",
            "2026-01-02T00:00:00Z",
        )
        quality = assess_query(request)
        self.assertTrue(any("fails silently" in reason for reason in quality.reasons))

    def test_neo_source_is_hard_rejected(self):
        request = SearchRequest("Coralogix via Neo", "source logs | filter $d ~ 'GE-1'", ("GE-1",), "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z")
        quality = assess_query(request)
        self.assertFalse(quality.allowed)
        self.assertEqual(quality.score, 0)
        self.assertTrue(any("Neo-routed" in reason for reason in quality.reasons))

    def test_provider_warning_is_not_accepted_as_checked_coverage(self):
        result = ToolResult(
            "Coralogix",
            SearchResultState.NO_RESULT,
            True,
            warnings=("compileWarning: token not indexed",),
        )
        self.assertFalse(result.valid_for_coverage)
        quality = result_quality(result)
        self.assertFalse(quality.allowed)
        self.assertIn("failed result", quality.reasons)


if __name__ == "__main__":
    unittest.main()
