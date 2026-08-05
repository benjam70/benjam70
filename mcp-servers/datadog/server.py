"""Datadog MCP server — read-only log search, metric queries, and monitor status.

Requires these environment variables:
  DATADOG_API_KEY    Organization Settings > API Keys
  DATADOG_APP_KEY    Organization Settings > Application Keys
                      (must belong to a user with the read scopes needed:
                      logs_read_data, metrics_read, monitors_read)
  DATADOG_SITE        defaults to "datadoghq.eu" (Global-e's Datadog is EU);
                       override if pointed at a different site

Run directly for a stdio smoke test: python3 server.py
"""
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

API_KEY = os.environ.get("DATADOG_API_KEY", "")
APP_KEY = os.environ.get("DATADOG_APP_KEY", "")
SITE = os.environ.get("DATADOG_SITE", "datadoghq.eu")

if not all([API_KEY, APP_KEY]):
    print(
        "[datadog-mcp] Missing credentials: set DATADOG_API_KEY and "
        "DATADOG_APP_KEY before tools will work.",
        file=sys.stderr,
    )

BASE_URL = f"https://api.{SITE}"
HEADERS = {
    "DD-API-KEY": API_KEY,
    "DD-APPLICATION-KEY": APP_KEY,
    "Content-Type": "application/json",
}

mcp = FastMCP("datadog")


def _to_unix(ts: str) -> int:
    """Accept ISO 8601 or an already-numeric unix timestamp string."""
    if ts.isdigit():
        return int(ts)
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


@mcp.tool()
async def datadog_search_logs(query: str, start_time: str, end_time: str = "", limit: int = 50) -> str:
    """Search Datadog logs.

    `query` is Datadog log search syntax, e.g.
    'service:checkout-api status:error @order_id:GE20458812DE'.
    start_time/end_time are ISO 8601 timestamps (end_time defaults to now).
    Returns matching log entries with timestamp, service, status, and message.
    """
    limit = max(1, min(limit, 200))
    body = {
        "filter": {
            "query": query,
            "from": start_time,
            "to": end_time or "now",
        },
        "page": {"limit": limit},
        "sort": "-timestamp",
    }
    async with httpx.AsyncClient(headers=HEADERS, timeout=30) as client:
        resp = await client.post(f"{BASE_URL}/api/v2/logs/events/search", json=body)
        resp.raise_for_status()
        data = resp.json()
    logs = []
    for item in data.get("data", []):
        attrs = item.get("attributes", {})
        logs.append(
            {
                "timestamp": attrs.get("timestamp"),
                "service": attrs.get("service"),
                "status": attrs.get("status"),
                "host": attrs.get("host"),
                "message": attrs.get("message"),
            }
        )
    return json.dumps({"count": len(logs), "logs": logs}, indent=2, default=str)


@mcp.tool()
async def datadog_query_metrics(query: str, start_time: str, end_time: str = "") -> str:
    """Query a Datadog timeseries metric.

    `query` is a Datadog metric query, e.g. 'avg:trace.http.request.duration{service:checkout-api}'.
    start_time/end_time are ISO 8601 timestamps (end_time defaults to now).
    Returns the series' points as [unix_ms, value] pairs per matched scope.
    """
    from_ts = _to_unix(start_time)
    to_ts = _to_unix(end_time) if end_time else int(datetime.now(timezone.utc).timestamp())
    async with httpx.AsyncClient(headers=HEADERS, timeout=30) as client:
        resp = await client.get(
            f"{BASE_URL}/api/v1/query",
            params={"query": query, "from": from_ts, "to": to_ts},
        )
        resp.raise_for_status()
        data = resp.json()
    series = [
        {"scope": s.get("scope"), "metric": s.get("metric"), "unit": s.get("unit"), "pointlist": s.get("pointlist")}
        for s in data.get("series", [])
    ]
    return json.dumps({"query": query, "series": series}, indent=2, default=str)


@mcp.tool()
async def datadog_list_monitors(query: str = "", limit: int = 50) -> str:
    """List/search Datadog monitors (alerts, SLOs surfaced as monitors) and their current status.

    `query` is Datadog monitor search syntax, e.g. 'tag:service:checkout-api status:alert'.
    Leave empty to list monitors regardless of state (capped by limit).
    Returns id, name, type, current overall_state, and tags for each match.
    """
    limit = max(1, min(limit, 100))
    async with httpx.AsyncClient(headers=HEADERS, timeout=30) as client:
        resp = await client.get(
            f"{BASE_URL}/api/v1/monitor/search",
            params={"query": query, "per_page": limit},
        )
        resp.raise_for_status()
        data = resp.json()
    monitors = [
        {
            "id": m.get("id"),
            "name": m.get("name"),
            "type": m.get("type"),
            "overall_state": m.get("status"),
            "tags": m.get("tags"),
        }
        for m in data.get("monitors", [])
    ]
    return json.dumps({"count": len(monitors), "monitors": monitors}, indent=2, default=str)


if __name__ == "__main__":
    mcp.run(transport="stdio")
