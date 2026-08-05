"""Stripe MCP server — read-only lookup of payments, charges, refunds, and disputes.

Requires this environment variable:
  STRIPE_API_KEY   a *restricted* API key (Developers > API keys > Create
                    restricted key in the Stripe dashboard) scoped to
                    read-only access on: Charges, PaymentIntents, Refunds,
                    Disputes. Do not use an account's full secret key here;
                    a restricted key limits the blast radius if it ever
                    leaks, and this server never needs write access to
                    anything.

Note: Stripe's API never returns a full card number or CVV under any
circumstance, by design (PCI scope stays on Stripe's side) — the richest
this ever gets is brand/last4/funding and the AVS/CVC check *results*
(match/no_match/unavailable), which is exactly the kind of fraud-signal
data the payment-forensics skill's Mode A investigation expects as
source-tagged evidence. Redaction for customer/merchant-facing output
(Mode B/C) is handled by that skill's own Card Data Guard, not by this
server — this server's job is just to surface what Stripe actually has.

Run directly for a stdio smoke test: python3 server.py
"""
import json
import os
import sys
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

API_KEY = os.environ.get("STRIPE_API_KEY", "")

if not API_KEY:
    print(
        "[stripe-mcp] Missing credentials: set STRIPE_API_KEY (a restricted, "
        "read-only key) before tools will work.",
        file=sys.stderr,
    )

BASE_URL = "https://api.stripe.com/v1"
HEADERS = {"Authorization": f"Bearer {API_KEY}"}

mcp = FastMCP("stripe")


async def _get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    async with httpx.AsyncClient(headers=HEADERS, timeout=30) as client:
        resp = await client.get(f"{BASE_URL}{path}", params=params)
        resp.raise_for_status()
        return resp.json()


@mcp.tool()
async def stripe_get_payment_intent(payment_intent_id: str) -> str:
    """Get a Stripe PaymentIntent by ID (starts with 'pi_').

    Returns status, amount, currency, creation time, customer, description,
    and the latest associated charge, expanded inline so the charge-level
    detail (capture/refund state) doesn't need a second lookup.
    """
    data = await _get(f"/payment_intents/{payment_intent_id}", {"expand[]": "latest_charge"})
    return json.dumps(data, indent=2, default=str)


@mcp.tool()
async def stripe_get_charge(charge_id: str) -> str:
    """Get a Stripe Charge by ID (starts with 'ch_').

    Returns status, amount, amount_refunded, currency, captured/paid/
    refunded/disputed flags, payment_method_details (card brand, last4,
    funding, and AVS/CVC check results, never a full card number),
    outcome (risk_level, risk_score, network_status), and receipt_url.
    """
    data = await _get(f"/charges/{charge_id}")
    return json.dumps(data, indent=2, default=str)


@mcp.tool()
async def stripe_search_charges(query: str, limit: int = 25) -> str:
    """Search Stripe charges using Stripe's search query syntax.

    Examples: "status:'succeeded' AND amount:8999",
    "metadata['order_id']:'GE20458812DE'", "customer:'cus_ABC123'".
    See Stripe's Search API docs for the full query language. Returns each
    matching charge's id, status, amount, currency, created, and customer.
    """
    limit = max(1, min(limit, 100))
    data = await _get("/charges/search", {"query": query, "limit": limit})
    results = [
        {
            "id": c.get("id"),
            "status": c.get("status"),
            "amount": c.get("amount"),
            "currency": c.get("currency"),
            "created": c.get("created"),
            "customer": c.get("customer"),
            "payment_intent": c.get("payment_intent"),
        }
        for c in data.get("data", [])
    ]
    return json.dumps({"count": len(results), "has_more": data.get("has_more"), "results": results}, indent=2, default=str)


@mcp.tool()
async def stripe_list_refunds(charge_id: str = "", payment_intent_id: str = "", limit: int = 25) -> str:
    """List refunds for a given charge or payment intent (pass exactly one).

    Returns each refund's id, status, amount, currency, reason, and
    creation time, most recent first.
    """
    if not charge_id and not payment_intent_id:
        return json.dumps({"error": "pass either charge_id or payment_intent_id"}, indent=2)
    limit = max(1, min(limit, 100))
    params: dict[str, Any] = {"limit": limit}
    if charge_id:
        params["charge"] = charge_id
    if payment_intent_id:
        params["payment_intent"] = payment_intent_id
    data = await _get("/refunds", params)
    refunds = [
        {
            "id": r.get("id"),
            "status": r.get("status"),
            "amount": r.get("amount"),
            "currency": r.get("currency"),
            "reason": r.get("reason"),
            "created": r.get("created"),
        }
        for r in data.get("data", [])
    ]
    return json.dumps({"count": len(refunds), "has_more": data.get("has_more"), "refunds": refunds}, indent=2, default=str)


@mcp.tool()
async def stripe_get_dispute(dispute_id: str) -> str:
    """Get a Stripe Dispute (chargeback) by ID (starts with 'dp_').

    Returns status, reason, amount, currency, the associated charge id,
    and evidence_details (due_by date, submission_count) so you can tell
    at a glance whether a response is still owed and when it's due.
    """
    data = await _get(f"/disputes/{dispute_id}")
    return json.dumps(data, indent=2, default=str)


if __name__ == "__main__":
    mcp.run(transport="stdio")
