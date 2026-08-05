"""Monday.com MCP server — read-only board item search and retrieval.

Requires this environment variable:
  MONDAY_API_TOKEN     Avatar > Administration > Connections > API,
                        or a personal token from your profile's Developer page

Optional:
  MONDAY_API_VERSION    GraphQL API version header, e.g. "2024-10".
                         Defaults below to a recent version; if Monday has
                         released newer versions since, update this.

Run directly for a stdio smoke test: python3 server.py

Note on search: Monday's GraphQL API filters items by column values, which
are board-specific (column IDs differ per board). To keep this usable without
per-board configuration, monday_search_items fetches a page of items from the
given board and filters by substring match on the item name client-side. For
column-value-precise filtering, extend the GraphQL query_params in this file
with the specific board's column IDs.
"""
import json
import os
import sys
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

API_TOKEN = os.environ.get("MONDAY_API_TOKEN", "")
API_VERSION = os.environ.get("MONDAY_API_VERSION", "2024-10")

if not API_TOKEN:
    print(
        "[monday-mcp] Missing credentials: set MONDAY_API_TOKEN before tools will work.",
        file=sys.stderr,
    )

BASE_URL = "https://api.monday.com/v2"
# Monday's Authorization header is the raw token, no "Bearer " prefix.
HEADERS = {"Authorization": API_TOKEN, "API-Version": API_VERSION, "Content-Type": "application/json"}

mcp = FastMCP("monday")


async def _graphql(query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
    async with httpx.AsyncClient(headers=HEADERS, timeout=30) as client:
        resp = await client.post(BASE_URL, json={"query": query, "variables": variables or {}})
        resp.raise_for_status()
        data = resp.json()
    if "errors" in data:
        raise RuntimeError(f"Monday API error: {data['errors']}")
    return data.get("data", {})


@mcp.tool()
async def monday_search_items(board_id: int, query_text: str = "", limit: int = 25) -> str:
    """Search items on a Monday.com board.

    Fetches up to `limit` items from the board and, if query_text is given,
    filters to items whose name contains it (case-insensitive substring
    match). Returns each item's id, name, and its column values (id, text).
    """
    limit = max(1, min(limit, 100))
    query = """
    query ($boardId: [ID!], $limit: Int!) {
      boards(ids: $boardId) {
        name
        items_page(limit: $limit) {
          items {
            id
            name
            column_values {
              id
              text
              type
            }
          }
        }
      }
    }
    """
    data = await _graphql(query, {"boardId": [str(board_id)], "limit": limit})
    boards = data.get("boards", [])
    if not boards:
        return json.dumps({"error": f"board {board_id} not found or not accessible"}, indent=2)
    items = boards[0].get("items_page", {}).get("items", [])
    if query_text:
        needle = query_text.lower()
        items = [i for i in items if needle in (i.get("name") or "").lower()]
    return json.dumps({"board": boards[0].get("name"), "count": len(items), "items": items}, indent=2, default=str)


@mcp.tool()
async def monday_get_item(item_id: int) -> str:
    """Get full details of a Monday.com item by ID.

    Returns the item's name, its board, all column values (id, text, type),
    and recent updates (comments) with their author and body.
    """
    query = """
    query ($itemId: [ID!]) {
      items(ids: $itemId) {
        id
        name
        board {
          id
          name
        }
        column_values {
          id
          text
          type
        }
        updates(limit: 25) {
          creator {
            name
          }
          body
          created_at
        }
      }
    }
    """
    data = await _graphql(query, {"itemId": [str(item_id)]})
    items = data.get("items", [])
    if not items:
        return json.dumps({"error": f"item {item_id} not found or not accessible"}, indent=2)
    return json.dumps(items[0], indent=2, default=str)


if __name__ == "__main__":
    mcp.run(transport="stdio")
