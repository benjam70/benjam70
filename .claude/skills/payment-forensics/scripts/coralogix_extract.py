#!/usr/bin/env python3
"""
Extract match context from a saved mcp__Neo__coralogix_search_logs output file.

Why this exists: coralogix_search_logs results routinely exceed the tool
token limit and get dumped to a local file instead of returned inline. Those
files have a handful of extremely long lines (one Coralogix log entry per
line, often 10-20k+ characters of escaped JSON), so the Read tool's
offset/limit can't chunk them usefully, and the Grep tool's own line-length
cutoff replaces long matching lines with "[Omitted long matching line]".
Re-deriving a one-off python regex scan for this every time wastes a
turn. This script is that scan, written once.

Usage:
    python3 coralogix_extract.py <file> <pattern> [--context N] [--regex]

    <file>      path to the saved coralogix_search_logs .txt output
    <pattern>   plain substring to search for (case-insensitive) by default;
                pass --regex to treat it as a regular expression instead
    --context N characters of context on each side of a match (default 200)
    --max M     max number of matches to print (default 40)

Prints each match with surrounding context, separated by "---MATCH---".
Also extracts the per-line Coralogix "timestamp" metadata value (if present
on the same line as the match) so results can be dropped straight into a
Timeline table without a second pass.
"""
import argparse
import re
import sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("pattern")
    ap.add_argument("--context", type=int, default=200)
    ap.add_argument("--max", type=int, default=40)
    ap.add_argument("--regex", action="store_true", help="treat pattern as a regex instead of a literal substring")
    args = ap.parse_args()

    needle = args.pattern if args.regex else re.escape(args.pattern)
    pattern = re.compile(needle, re.IGNORECASE)
    ts_pattern = re.compile(r'"key":"timestamp","value":"([^"]+)"')

    total = 0
    with open(args.file, "r", errors="replace") as f:
        for line_no, line in enumerate(f):
            ts_match = ts_pattern.search(line)
            ts = ts_match.group(1) if ts_match else None
            for m in pattern.finditer(line):
                if total >= args.max:
                    print(f"\n... stopped at --max {args.max} matches, re-run with a narrower pattern or higher --max", file=sys.stderr)
                    return
                start = max(0, m.start() - args.context)
                end = min(len(line), m.end() + args.context)
                total += 1
                print(f"---MATCH--- line={line_no} timestamp={ts}")
                print(line[start:end])
                print()

    if total == 0:
        print(f"No matches for {args.pattern!r} in {args.file}", file=sys.stderr)


if __name__ == "__main__":
    main()
