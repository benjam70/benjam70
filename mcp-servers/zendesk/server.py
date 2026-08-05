"""Zendesk MCP server — read-only ticket search and retrieval.

Requires these environment variables:
  ZENDESK_SUBDOMAIN   e.g. "global-e" for global-e.zendesk.com
  ZENDESK_EMAIL       the agent email associated with the API token
  ZENDESK_API_TOKEN   generated in Zendesk Admin Center > Apps and
                       integrations > APIs > Zendesk API > Add API token

Run directly for a stdio smoke test: python3 server.py
"""
import json
import os
import sys
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

SUBDOMAIN = os.environ.get("ZENDESK_SUBDOMAIN", "")
EMAIL = os.environ.get("ZENDESK_EMAIL", "")
API_TOKEN = os.environ.get("ZENDESK_API_TOKEN", "")

if not all([SUBDOMAIN, EMAIL, API_TOKEN]):
    print(
        "[zendesk-mcp] Missing credentials: set ZENDESK_SUBDOMAIN, "
        "ZENDESK_EMAIL, and ZENDESK_API_TOKEN before tools will work.",
        file=sys.stderr,
    )

BASE_URL = f"https://{SUBDOMAIN}.zendesk.com/api/v2"
AUTH = (f"{EMAIL}/token", API_TOKEN)

mcp = FastMCP("zendesk")


async def _get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    async with httpx.AsyncClient(auth=AUTH, timeout=30) as client:
        resp = await client.get(f"{BASE_URL}{path}", params=params)
        resp.raise_for_status()
        return resp.json()


@mcp.tool()
async def zendesk_search_tickets(query: str, limit: int = 25) -> str:
    """Search Zendesk tickets.

    `query` follows Zendesk search syntax, e.g.
    'status:open requester:customer@example.com' or a free-text term.
    'type:ticket' is added automatically if not already present, so
    results stay ticket-only rather than mixing in users/organizations.
    Returns id, subject, status, priority, requester_id, tags,
    created_at, updated_at, and a direct agent URL for each match.
    """
    if "type:" not in query:
        query = f"type:ticket {query}"
    limit = max(1, min(limit, 100))
    data = await _get("/search.json", {"query": query, "per_page": limit})
    results = [
        {
            "id": t.get("id"),
            "subject": t.get("subject"),
            "status": t.get("status"),
            "priority": t.get("priority"),
            "requester_id": t.get("requester_id"),
            "tags": t.get("tags"),
            "created_at": t.get("created_at"),
            "updated_at": t.get("updated_at"),
            "url": f"https://{SUBDOMAIN}.zendesk.com/agent/tickets/{t.get('id')}",
        }
        for t in data.get("results", [])
    ]
    return json.dumps({"count": data.get("count", len(results)), "results": results}, indent=2, default=str)


@mcp.tool()
async def zendesk_get_ticket(ticket_id: int, include_comments: bool = True) -> str:
    """Get full details of a Zendesk ticket, optionally with its comment thread.

    Returns the ticket's core fields plus, when include_comments is true,
    every comment (author id, whether it's public or internal, plain-text
    body, and timestamp) in chronological order, the same thread a CS
    agent sees when opening the ticket.
    """
    ticket_data = await _get(f"/tickets/{ticket_id}.json")
    ticket = ticket_data.get("ticket", {})
    out: dict[str, Any] = {
        "id": ticket.get("id"),
        "subject": ticket.get("subject"),
        "description": ticket.get("description"),
        "status": ticket.get("status"),
        "priority": ticket.get("priority"),
        "requester_id": ticket.get("requester_id"),
        "assignee_id": ticket.get("assignee_id"),
        "group_id": ticket.get("group_id"),
        "tags": ticket.get("tags"),
        "created_at": ticket.get("created_at"),
        "updated_at": ticket.get("updated_at"),
        "url": f"https://{SUBDOMAIN}.zendesk.com/agent/tickets/{ticket_id}",
    }
    if include_comments:
        comments_data = await _get(f"/tickets/{ticket_id}/comments.json")
        out["comments"] = [
            {
                "author_id": c.get("author_id"),
                "public": c.get("public"),
                "body": c.get("plain_body") or c.get("body"),
                "created_at": c.get("created_at"),
            }
            for c in comments_data.get("comments", [])
        ]
    return json.dumps(out, indent=2, default=str)


if __name__ == "__main__":
    mcp.run(transport="stdio")
