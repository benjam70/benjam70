"""HubSpot MCP server — read-only CRM object search and retrieval.

Requires this environment variable:
  HUBSPOT_ACCESS_TOKEN   a private app access token with at least
                          crm.objects.contacts.read, crm.objects.companies.read,
                          crm.objects.deals.read (Settings > Integrations >
                          Private Apps > create/select an app > Auth tab)

Run directly for a stdio smoke test: python3 server.py
"""
import json
import os
import sys
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

ACCESS_TOKEN = os.environ.get("HUBSPOT_ACCESS_TOKEN", "")

if not ACCESS_TOKEN:
    print(
        "[hubspot-mcp] Missing credentials: set HUBSPOT_ACCESS_TOKEN before tools will work.",
        file=sys.stderr,
    )

BASE_URL = "https://api.hubapi.com"
HEADERS = {"Authorization": f"Bearer {ACCESS_TOKEN}", "Content-Type": "application/json"}

VALID_OBJECT_TYPES = {"contacts", "companies", "deals", "tickets"}

mcp = FastMCP("hubspot")


def _validate_object_type(object_type: str) -> str:
    ot = object_type.strip().lower()
    if ot not in VALID_OBJECT_TYPES:
        raise ValueError(f"object_type must be one of {sorted(VALID_OBJECT_TYPES)}, got {object_type!r}")
    return ot


@mcp.tool()
async def hubspot_search_crm(object_type: str, query: str, limit: int = 25) -> str:
    """Search a HubSpot CRM object type by free text.

    object_type is one of: contacts, companies, deals, tickets.
    query is matched against the object's default searchable properties
    (name, email, company name, deal name, etc. depending on type).
    Returns id and the default properties HubSpot includes in search results
    for each match.
    """
    ot = _validate_object_type(object_type)
    limit = max(1, min(limit, 100))
    body = {"query": query, "limit": limit}
    async with httpx.AsyncClient(headers=HEADERS, timeout=30) as client:
        resp = await client.post(f"{BASE_URL}/crm/v3/objects/{ot}/search", json=body)
        resp.raise_for_status()
        data = resp.json()
    results = [
        {"id": r.get("id"), "properties": r.get("properties"), "createdAt": r.get("createdAt"), "updatedAt": r.get("updatedAt")}
        for r in data.get("results", [])
    ]
    return json.dumps({"total": data.get("total", len(results)), "results": results}, indent=2, default=str)


@mcp.tool()
async def hubspot_get_object(object_type: str, object_id: str, properties: list[str] | None = None) -> str:
    """Get a single HubSpot CRM object by ID.

    object_type is one of: contacts, companies, deals, tickets.
    properties is an optional list of property names to include; if omitted,
    HubSpot returns its default property set for that object type.
    """
    ot = _validate_object_type(object_type)
    params: dict[str, Any] = {}
    if properties:
        params["properties"] = ",".join(properties)
    async with httpx.AsyncClient(headers=HEADERS, timeout=30) as client:
        resp = await client.get(f"{BASE_URL}/crm/v3/objects/{ot}/{object_id}", params=params)
        resp.raise_for_status()
        data = resp.json()
    return json.dumps(data, indent=2, default=str)


if __name__ == "__main__":
    mcp.run(transport="stdio")
