#!/usr/bin/env python3
"""CLI for payment_forensics.coralogix_dump_query.

Usage:
    python tools/query_coralogix_dump.py <dump.txt> --group-by action message
    python tools/query_coralogix_dump.py <dump.txt> --sql "SELECT COUNT(*) FROM events"

See payment_forensics/coralogix_dump_query.py for why this exists: querying
a saved Coralogix result dump with SQL instead of grepping escaped JSON.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from payment_forensics.coralogix_dump_query import field_value_counts, run_sql  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dump_path", help="Path to a saved coralogix_query_dataprime result file")
    parser.add_argument("--group-by", nargs="+", metavar="FIELD", help="userData fields to group and count by")
    parser.add_argument("--sql", help="Arbitrary SQL against the `events` view instead of --group-by")
    parser.add_argument("--limit", type=int, default=50, help="Max rows to print (default 50)")
    args = parser.parse_args()

    if not args.group_by and not args.sql:
        parser.error("pass --group-by FIELD [FIELD ...] or --sql \"...\"")

    try:
        if args.sql:
            rows = run_sql(args.dump_path, args.sql)
        else:
            rows = field_value_counts(args.dump_path, args.group_by, limit=args.limit)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    for row in rows:
        print(row)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
