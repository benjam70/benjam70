import unittest
from datetime import datetime, timezone

from payment_forensics.timestamp_normalize import (
    UnknownSourceError,
    is_day_month_ambiguous,
    normalize_timestamp,
)


class TimestampNormalizeTests(unittest.TestCase):
    def test_ge_admin_dayfirst_is_not_misread_as_month_first(self):
        # The real risk this closes: "08/09/2026" defaults to 9 August under
        # plain dateutil, not 8 September, with no error.
        result = normalize_timestamp("08/09/2026 11:58:29", source="ge_admin")
        self.assertEqual(result, datetime(2026, 9, 8, 11, 58, 29, tzinfo=timezone.utc))

    def test_adyen_gmt_offset_sign_is_not_inverted(self):
        # dateutil's own automatic GMT+N handling inverts the sign; this
        # confirms the explicit-offset path is used instead.
        result = normalize_timestamp("Sep 14, 2026, 01:11:03 GMT+3", source="adyen")
        self.assertEqual(result, datetime(2026, 9, 13, 22, 11, 3, tzinfo=timezone.utc))

    def test_coralogix_and_adyen_agree_on_the_same_real_event(self):
        adyen = normalize_timestamp("Sep 14, 2026, 01:11:03 GMT+3", source="adyen")
        coralogix = normalize_timestamp("2026-09-13T22:11:03.00Z", source="coralogix")
        self.assertEqual(adyen, coralogix)

    def test_unregistered_source_raises_instead_of_guessing(self):
        with self.assertRaises(UnknownSourceError):
            normalize_timestamp("21/08/2026 11:21:25", source="customer_statement")

    def test_ambiguous_date_is_flagged(self):
        self.assertTrue(is_day_month_ambiguous("08/09/2026 11:58:29"))

    def test_unambiguous_date_is_not_flagged(self):
        self.assertFalse(is_day_month_ambiguous("21/08/2026 11:21:25"))

    def test_iso_dates_are_unaffected_by_dayfirst(self):
        result = normalize_timestamp("2026-09-13T22:11:03.00Z", source="coralogix")
        self.assertEqual(result, datetime(2026, 9, 13, 22, 11, 3, tzinfo=timezone.utc))


if __name__ == "__main__":
    unittest.main()
