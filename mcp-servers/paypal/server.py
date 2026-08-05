"""PayPal MCP server — read-only lookup of orders, captures, refunds, authorizations, and disputes.

Requires these environment variables:
  PAYPAL_CLIENT_ID       from a PayPal REST API app (Developer Dashboard >
                          Apps & Credentials > your app > Client ID)
  PAYPAL_CLIENT_SECRET    same app's secret. Use an app whose live/sandbox
                          credentials correspond to Global-e's actual PayPal
                          business account, not a personal developer account
                          — this needs to see Global-e's real transactions.

Optional:
  PAYPAL_ENV              "live" (default) or "sandbox"

This targets PayPal's V2 REST API (Checkout Orders, Payments, Disputes),
which is what Global-e's PayPalV2Controller integration is built on.
Legacy V1 (NVP/SOAP) transactions predating the V2 migration are not
reachable through this server.

Run directly for a stdio smoke test: python3 server.py
"""
import json
import os
import sys
import time
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

CLIENT_ID = os.environ.get("PAYPAL_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("PAYPAL_CLIENT_SECRET", "")
ENV = os.environ.get("PAYPAL_ENV", "live")

if not all([CLIENT_ID, CLIENT_SECRET]):
    print(
        "[paypal-mcp] Missing credentials: set PAYPAL_CLIENT_ID and "
        "PAYPAL_CLIENT_SECRET before tools will work.",
        file=sys.stderr,
    )

BASE_URL = "https://api-m.paypal.com" if ENV == "live" else "https://api-m.sandbox.paypal.com"

# Simple in-memory token cache; PayPal access tokens are short-lived
# (typically ~9 hours) and re-requesting one per call would be wasteful
# and could hit rate limits under repeated investigation queries.
_token_cache: dict[str, Any] = {"access_token": None, "expires_at": 0}


async def _get_access_token() -> str:
    if _token_cache["access_token"] and time.time() < _token_cache["expires_at"] - 60:
        return _token_cache["access_token"]
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{BASE_URL}/v1/oauth2/token",
            auth=(CLIENT_ID, CLIENT_SECRET),
            data={"grant_type": "client_credentials"},
            headers={"Accept": "application/json", "Accept-Language": "en_US"},
        )
        resp.raise_for_status()
        data = resp.json()
    _token_cache["access_token"] = data["access_token"]
    _token_cache["expires_at"] = time.time() + data.get("expires_in", 32400)
    return _token_cache["access_token"]


async def _get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    token = await _get_access_token()
    async with httpx.AsyncClient(headers={"Authorization": f"Bearer {token}"}, timeout=30) as client:
        resp = await client.get(f"{BASE_URL}{path}", params=params)
        resp.raise_for_status()
        return resp.json()


mcp = FastMCP("paypal")


@mcp.tool()
async def paypal_get_order(order_id: str) -> str:
    """Get a PayPal Checkout Order by ID.

    Returns status, intent, purchase units (amount breakdown), payer info,
    and the nested payments object (captures/refunds/authorizations already
    linked to this order) so related transactions don't need a separate
    lookup in the common case.
    """
    data = await _get(f"/v2/checkout/orders/{order_id}")
    return json.dumps(data, indent=2, default=str)


@mcp.tool()
async def paypal_get_capture(capture_id: str) -> str:
    """Get a PayPal Capture by ID.

    Returns status (COMPLETED/DECLINED/PENDING/REFUNDED/PARTIALLY_REFUNDED),
    amount, final_capture flag, seller_receivable_breakdown (fees, net
    amount, any exchange rate applied), and disbursement_mode.
    """
    data = await _get(f"/v2/payments/captures/{capture_id}")
    return json.dumps(data, indent=2, default=str)


@mcp.tool()
async def paypal_get_refund(refund_id: str) -> str:
    """Get a PayPal Refund by ID.

    Returns status, amount, reason, note_to_payer, and
    seller_payable_breakdown (fee refunded, net amount, any exchange rate).
    """
    data = await _get(f"/v2/payments/refunds/{refund_id}")
    return json.dumps(data, indent=2, default=str)


@mcp.tool()
async def paypal_get_authorization(authorization_id: str) -> str:
    """Get a PayPal Authorization by ID.

    Returns status (CREATED/CAPTURED/DENIED/EXPIRED/VOIDED), amount,
    expiration_time, and links to any capture made against it.
    """
    data = await _get(f"/v2/payments/authorizations/{authorization_id}")
    return json.dumps(data, indent=2, default=str)


@mcp.tool()
async def paypal_get_dispute(dispute_id: str) -> str:
    """Get a PayPal Dispute (chargeback/claim) by ID.

    Returns status, reason, dispute_amount, dispute_life_cycle_stage,
    dispute_outcome (if resolved), and the messages/evidence timeline.
    PayPal disputes are a separate path from the Justt-based chargeback
    pipeline other gateways use at Global-e, so this is the only way to
    reach PayPal dispute detail from Claude Code.
    """
    data = await _get(f"/v1/customer/disputes/{dispute_id}")
    return json.dumps(data, indent=2, default=str)


@mcp.tool()
async def paypal_search_disputes(dispute_state: str = "", start_time: str = "", end_time: str = "", limit: int = 25) -> str:
    """Search/list PayPal disputes, optionally filtered by state and time range.

    dispute_state is one of PayPal's dispute_state values, e.g.
    'REQUIRED_ACTION', 'UNDER_REVIEW', 'RESOLVED'. start_time/end_time are
    ISO 8601 timestamps bounding dispute creation time. Returns each
    dispute's id, status, reason, and amount.
    """
    limit = max(1, min(limit, 50))
    params: dict[str, Any] = {"page_size": limit}
    if dispute_state:
        params["dispute_state"] = dispute_state
    if start_time:
        params["start_time"] = start_time
    if end_time:
        params["end_time"] = end_time
    data = await _get("/v1/customer/disputes", params)
    items = data.get("items", [])
    results = [
        {
            "dispute_id": d.get("dispute_id"),
            "status": d.get("status"),
            "reason": d.get("reason"),
            "dispute_amount": d.get("dispute_amount"),
            "create_time": d.get("create_time"),
        }
        for d in items
    ]
    return json.dumps({"count": len(results), "disputes": results}, indent=2, default=str)


if __name__ == "__main__":
    mcp.run(transport="stdio")
