"""Coralogix MCP server — read-only DataPrime log/trace queries.

Runs locally, so calls go out from this machine's own network path rather
than the hosted `mcp__claude_ai_Coralogix__*` connector's infrastructure.
Built as a fallback for when the hosted connector can't reach Coralogix
(e.g. account-level IP allowlisting that only covers VPN/office IPs, not
wherever the hosted connector's own egress lands), not as a replacement —
prefer the hosted connector when it works, this exists for when it
doesn't. See mcp-servers/README.md for the full background.

Requires these environment variables:
  CORALOGIX_API_KEY   a Coralogix API key with query/read permission
                       (Coralogix UI -> Data Flow -> API Keys, or Org
                       Settings -> API Keys depending on your account's
                       UI version). Scope it read-only / query-only if
                       that option exists, same least-privilege principle
                       as every other server in this directory.
  CORALOGIX_DOMAIN    the domain suffix for your Coralogix account's
                       region, e.g. "eu2.coralogix.com", "us1.coralogix.com".
                       Visible in the URL when logged into the Coralogix
                       web UI. Getting this wrong produces a connection
                       error, not a silent wrong answer.

Wraps Coralogix's DataPrime HTTP Query API:
  https://coralogix.com/docs/dataprime/API/api-queries/
  https://coralogix.com/docs/dataprime/API/direct-archive-query-http/

The response is newline-delimited JSON: a queryId line, one or more
result lines (each with a "results" array of log rows), and a final
statistics line. This server flattens that into a single JSON object.
Only spot-checked against Coralogix's published API docs, not against a
real account — sanity-check the first real call, same caveat the other
servers in this directory carry for their own first real call.

Run directly for a stdio smoke test: python3 server.py
"""
import asyncio
import json
import os
import shutil
import sys
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

API_KEY = os.environ.get("CORALOGIX_API_KEY", "")
DOMAIN = os.environ.get("CORALOGIX_DOMAIN", "")

if not API_KEY:
    print(
        "[coralogix-mcp] Missing credentials: set CORALOGIX_API_KEY before "
        "tools will work.",
        file=sys.stderr,
    )
if not DOMAIN:
    print(
        "[coralogix-mcp] Missing CORALOGIX_DOMAIN (e.g. 'eu2.coralogix.com', "
        "check the URL of your Coralogix web UI) before tools will work.",
        file=sys.stderr,
    )

BASE_URL = f"https://api.{DOMAIN}/api/v1/dataprime/query" if DOMAIN else ""
HEADERS = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

mcp = FastMCP("coralogix")

_CX_CANDIDATES = (
    shutil.which("cx"),
    os.path.expandvars(r"%LOCALAPPDATA%\cx\cx.exe"),
)
CX_BIN = next((path for path in _CX_CANDIDATES if path and os.path.isfile(path)), None)


def _parse_ndjson(text: str) -> dict[str, Any]:
    query_id = None
    rows: list[dict[str, Any]] = []
    warnings: list[Any] = []
    statistics = None
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "queryId" in obj:
            query_id = obj["queryId"]
        elif "result" in obj:
            rows.extend(obj["result"].get("results", []))
        elif "statistics" in obj:
            statistics = obj["statistics"]
        elif "warning" in obj:
            warnings.append(obj["warning"])
    return {
        "queryId": query_id,
        "rowCount": len(rows),
        "results": rows,
        "warnings": warnings,
        "statistics": statistics,
    }


@mcp.tool()
async def coralogix_query_dataprime(
    query: str,
    start_date: str,
    end_date: str,
    tier: str = "TIER_FREQUENT_SEARCH",
    limit: int = 200,
) -> str:
    """Run a DataPrime query against Coralogix logs/spans, over this machine's own network path.

    query: a DataPrime query string, e.g. "source logs | filter $d ~ 'GE12602280838FR'".
    start_date / end_date: ISO 8601 UTC timestamps, e.g. "2026-08-01T00:00:00Z".
      Both required — unlike the hosted tool, there is no silent narrow
      default here, omitting either raises an explicit error instead.
    tier: "TIER_FREQUENT_SEARCH" (recent/hot data, default) or
      "TIER_ARCHIVE" (older data moved to archive storage).
    limit: max rows to return after flattening the response (default 200).

    Returns a JSON object with queryId, rowCount, results (each row's
    userData/labels/metadata exactly as Coralogix returns them, not
    reshaped), any warnings (e.g. a compileWarning about a dropped short
    numeric token), and statistics.
    """
    if not API_KEY or not DOMAIN:
        return json.dumps(
            {"error": "CORALOGIX_API_KEY and/or CORALOGIX_DOMAIN not set"}, indent=2
        )
    if not start_date or not end_date:
        return json.dumps(
            {"error": "start_date and end_date are both required (ISO 8601 UTC)"}, indent=2
        )

    body = {
        "query": query,
        "metadata": {
            "startDate": start_date,
            "endDate": end_date,
            "tier": tier,
            "syntax": "QUERY_SYNTAX_DATAPRIME",
        },
    }
    async with httpx.AsyncClient(headers=HEADERS, timeout=60) as client:
        resp = await client.post(BASE_URL, json=body)
        resp.raise_for_status()
        parsed = _parse_ndjson(resp.text)

    parsed["results"] = parsed["results"][: max(1, limit)]
    return json.dumps(parsed, indent=2, default=str)


@mcp.tool()
async def coralogix_search_fields(
    text: str,
    search_type: str = "semantic",
    dataset: str = "logs",
    limit: int = 10,
) -> str:
    """Find the real DataPrime field path for a concept, before guessing one.

    Wraps `cx search-fields`, which is not the same tool as
    coralogix_query_dataprime: this does not search log CONTENT, it searches
    Coralogix's schema of known fields (semantic mode) or scans recent field
    VALUES (value mode) and returns the exact dotted path to use in a query.

    Use this first whenever the right field path isn't already known.
    coralogix_query_dataprime's own DataPrime dotted-path lookups (e.g.
    `$d.userData.something`) fail SILENTLY (zero rows, no error) on a wrong
    or guessed path, so a genuine gap and a typo'd field name look identical
    from that tool alone. This tool exists to remove the guess: semantic mode
    takes a plain-English description ("refund amount", "chargeback reason
    code") and returns candidate `$d.<path>` fields ranked by similarity,
    each with a human-readable description of what it holds. Value mode
    instead takes a literal value you already expect to see (an order ID, a
    status string) and finds which field(s) actually carry it.

    text: description (semantic mode) or literal value (value mode) to search for.
    search_type: "semantic" (default, description-based) or "value" (by field
      value content). Value mode needs a broader auth scope than plain log
      queries; if it errors on a missing team-id/company-id header, that is a
      credential-scope gap to raise with whoever issued the API key, not a
      sign the field doesn't exist — fall back to semantic mode or a direct
      coralogix_query_dataprime full-text search instead of reporting absence.
    dataset: "logs" or "spans" for semantic mode; "logs", "spans", or "all" for value mode.
    limit: max results (default 10).

    Returns the raw JSON `cx search-fields` prints: a list of
    {dataprime_path, top_level_key, path, description, similarity} (semantic)
    or the matching value hits (value mode). Runs over the `cx` CLI's own
    configured profile on this machine, not the CORALOGIX_API_KEY/DOMAIN env
    vars coralogix_query_dataprime uses — see docs/coralogix-claude-code.md
    for `cx profiles add`.
    """
    if not CX_BIN:
        return json.dumps(
            {"error": "cx CLI not found on PATH or at %LOCALAPPDATA%\\cx\\cx.exe. See docs/coralogix-claude-code.md."},
            indent=2,
        )
    if search_type not in {"semantic", "value"}:
        return json.dumps({"error": "search_type must be 'semantic' or 'value'"}, indent=2)

    args = [
        CX_BIN,
        "search-fields",
        text,
        "--search-type",
        search_type,
        "--dataset",
        dataset,
        "--limit",
        str(max(1, limit)),
        "-o",
        "json",
    ]
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        return json.dumps(
            {"error": stderr.decode(errors="replace").strip() or f"cx exited {proc.returncode}"},
            indent=2,
        )
    try:
        return json.dumps(json.loads(stdout.decode(errors="replace")), indent=2)
    except json.JSONDecodeError:
        return json.dumps({"error": "cx returned non-JSON output", "raw": stdout.decode(errors="replace")}, indent=2)


if __name__ == "__main__":
    mcp.run(transport="stdio")
