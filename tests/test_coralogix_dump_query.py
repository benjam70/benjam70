import json
import tempfile
import unittest
from pathlib import Path

from payment_forensics.coralogix_dump_query import field_value_counts, run_sql


def _make_dump(rows: list[dict]) -> str:
    payload = {
        "queryId": {"queryId": "test-query"},
        "rowCount": len(rows),
        "results": [
            {
                "metadata": [{"key": "severity", "value": "3"}],
                "labels": [{"key": "applicationname", "value": "production"}],
                "userData": json.dumps(row),
            }
            for row in rows
        ],
        "warnings": [],
        "statistics": {"status": "COMPLETED", "e2eDurationMs": "1", "outputRowCount": str(len(rows))},
    }
    handle = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(payload, handle)
    handle.close()
    return handle.name


class CoralogixDumpQueryTests(unittest.TestCase):
    def test_field_value_counts_groups_and_counts_correctly(self):
        dump_path = _make_dump([
            {"action": "HandleKlarnaPayment", "orderId": "GE1"},
            {"action": "HandleKlarnaPayment", "orderId": "GE2"},
            {"action": "CreateOrderBasedOnQueueMessage", "orderId": "GE3"},
        ])
        try:
            result = field_value_counts(dump_path, ["action"])
            counts = {row[0]: row[1] for row in result}
            self.assertEqual(counts["HandleKlarnaPayment"], 2)
            self.assertEqual(counts["CreateOrderBasedOnQueueMessage"], 1)
        finally:
            Path(dump_path).unlink(missing_ok=True)

    def test_full_message_text_is_not_truncated(self):
        long_message = "FillMerchantOrder: Adding bundle V2 discounts. OrderId: \"GE13470689052GB\", Count: 0"
        dump_path = _make_dump([{"message": long_message}])
        try:
            result = field_value_counts(dump_path, ["message"])
            self.assertEqual(result[0][0], long_message)
        finally:
            Path(dump_path).unlink(missing_ok=True)

    def test_multi_field_grouping(self):
        dump_path = _make_dump([
            {"action": "A", "operation": "ChangeStatus"},
            {"action": "A", "operation": "ChangeStatus"},
            {"action": "A", "operation": "Other"},
        ])
        try:
            result = field_value_counts(dump_path, ["action", "operation"])
            self.assertEqual(len(result), 2)
            self.assertEqual(result[0][:2], ("A", "ChangeStatus"))
            self.assertEqual(result[0][2], 2)
        finally:
            Path(dump_path).unlink(missing_ok=True)

    def test_unsafe_field_name_is_rejected(self):
        dump_path = _make_dump([{"action": "A"}])
        try:
            with self.assertRaises(ValueError):
                field_value_counts(dump_path, ["action'; DROP TABLE events; --"])
        finally:
            Path(dump_path).unlink(missing_ok=True)

    def test_run_sql_supports_arbitrary_queries(self):
        dump_path = _make_dump([
            {"orderId": "GE1", "newStatus": "ReceivedByGlobalE"},
            {"orderId": "GE2", "newStatus": "PendingPayment"},
        ])
        try:
            rows = run_sql(
                dump_path,
                "SELECT COUNT(*) FROM events WHERE json_extract_string(user_data, '$.newStatus') = 'ReceivedByGlobalE'",
            )
            self.assertEqual(rows[0][0], 1)
        finally:
            Path(dump_path).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
