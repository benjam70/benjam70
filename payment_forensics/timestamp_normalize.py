"""Normalize timestamps from mixed sources to UTC, without silent day/month swaps.

RULE 1.6 in this skill requires resolving every timestamp to one reference
timezone before ordering a Timeline, because sources disagree: PSP
timestamps are typically UTC, GE Admin displays dates as DD/MM/YYYY, Adyen's
customer area shows a GMT offset in the string itself, customer statements
are in local time. That rule has been enforced by hand so far.

The concrete risk this closes: ``dateutil.parser.parse`` defaults to
month-first (US) interpretation. Fed a GE Admin date like "08/09/2026", it
silently returns 9 August instead of 8 September, a full month off, with no
error or warning. This happened for real in this session; it was only
caught because an independent Coralogix timestamp for the same event
happened to be checked separately. Without that lucky cross-check, this
class of misparse would corrupt a Timeline silently.

This module never guesses which convention a source uses. Each known
source's date convention and timezone must be registered in ``SOURCES``
below, confirmed by evidence, not assumed. A source not in that registry
raises rather than falling back to a default, matching the skill's own
"don't guess, mark AMBIGUOUS" rule for a timezone that can't be resolved.

Requires the optional `python-dateutil` package. Without it, callers
should keep normalizing timestamps by hand, the way every case before this
was actually investigated; a missing install is not a data gap.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

# dateutil silently inverts the sign on a trailing "GMT+N"/"GMT-N" suffix
# (confirmed live: "Sep 14, 2026, 01:11:03 GMT+3" parses as UTC-3, not
# UTC+3, six hours wrong, with no error). Strip and apply that offset
# ourselves instead of trusting dateutil's automatic handling of it.
_GMT_OFFSET_RE = re.compile(r"\s*GMT\s*([+-]\d{1,2})\s*$")


@dataclass(frozen=True)
class SourceConvention:
    dayfirst: bool
    tz: str  # IANA zone name, or "utc" for sources that are already UTC/offset-aware


# Confirmed conventions only. Add a source here only once its date format
# and timezone have actually been verified against real evidence, the same
# standard the skill applies to everything else.
SOURCES: dict[str, SourceConvention] = {
    "ge_admin": SourceConvention(dayfirst=True, tz="utc"),
    "adyen": SourceConvention(dayfirst=False, tz="utc"),
    "coralogix": SourceConvention(dayfirst=False, tz="utc"),
}


class UnknownSourceError(ValueError):
    """Raised for a source with no confirmed date convention registered.

    This is deliberate: guessing a convention here is exactly the silent
    misparse this module exists to prevent. Register the source in
    `SOURCES` once its format is confirmed, or normalize by hand and mark
    the timezone AMBIGUOUS per RULE 1.6 in the meantime.
    """


def normalize_timestamp(raw: str, *, source: str) -> datetime:
    """Parse a raw timestamp string from a known source into an aware UTC datetime.

    raw: the timestamp exactly as it appears in the source (e.g.
      "08/09/2026 11:58:29", "Sep 14, 2026, 01:11:03 GMT+3",
      "2026-09-13T22:11:03.00Z").
    source: a key in `SOURCES`. Raises UnknownSourceError for anything else,
      rather than guessing a day/month or timezone convention.

    Adyen's customer-area strings and Coralogix's ISO timestamps already
    carry an explicit offset or `Z`, so `dateutil` resolves those correctly
    regardless of the registered `tz`; the registry entry mainly documents
    that fact. GE Admin's DD/MM/YYYY strings carry no offset at all, so
    `dayfirst` and the registered `tz` are what make the parse correct
    instead of silently wrong.
    """
    try:
        from dateutil import parser as dateutil_parser
    except ImportError as exc:  # pragma: no cover - depends on optional install
        raise RuntimeError(
            "Install the optional python-dateutil package to enable timestamp normalization"
        ) from exc
    convention = SOURCES.get(source)
    if convention is None:
        raise UnknownSourceError(
            f"no confirmed date convention registered for source {source!r}; "
            f"known sources: {sorted(SOURCES)}"
        )

    gmt_match = _GMT_OFFSET_RE.search(raw)
    if gmt_match:
        naive = dateutil_parser.parse(raw[: gmt_match.start()], dayfirst=convention.dayfirst)
        offset = timezone(timedelta(hours=int(gmt_match.group(1))))
        return naive.replace(tzinfo=offset).astimezone(timezone.utc)

    parsed = dateutil_parser.parse(raw, dayfirst=convention.dayfirst)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(convention.tz) if convention.tz != "utc" else timezone.utc)
    return parsed.astimezone(timezone.utc)


def is_day_month_ambiguous(raw: str) -> bool:
    """True if a DD/MM/YYYY-shaped date's day and month are both <=12.

    Both readings (day-first and month-first) would parse as valid dates
    in that case, so the source's registered convention is the only thing
    that makes the result correct. Use this to flag a timestamp worth a
    second look, e.g. against an independent source, when the convention
    for a case's origin is uncertain.
    """
    import re

    match = re.match(r"^(\d{1,2})[/-](\d{1,2})[/-]\d{2,4}", raw.strip())
    if not match:
        return False
    first, second = int(match.group(1)), int(match.group(2))
    return first <= 12 and second <= 12
