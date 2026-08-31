# MCP servers: Zendesk, Datadog, HubSpot, Monday.com, Stripe, PayPal

Six small, read-only MCP servers, one per system. The first four fill the
gap between what the Neo AI web app can reach (all of these) and what this
Claude Code session could reach before (none of these). Stripe and PayPal
were added separately for the payment-forensics skill, which already names
them among the gateways it investigates. Each is a thin wrapper over that
system's public REST/GraphQL API using the official MCP Python SDK.

Not every gateway the skill names gets a server here — Adyen, Klarna, and
Worldpay were all deliberately skipped after checking. Adyen and Klarna
are both webhook-driven integrations at Global-e (Klarna's only outbound
call, `ReadHPPSession`, is narrowly scoped to redirect finalization, same
category as Adyen's `PaymentResultRequest`), so a live "look up this
payment" MCP tool would either not work or would duplicate what Coralogix
already has (see the skill's tool-grounding section for how that was
verified for Adyen). Worldpay refunds are also webhook-driven, and its
disputes arrive via a scheduled SFTP file drop, not any API — there's an
internal HLD documenting this. PayPal and Stripe, by contrast, are cases
where Global-e's own integration makes live outbound calls to the
gateway's real API, and the gateway has genuine GET-by-ID endpoints — check
before building, don't assume every gateway looks like Stripe.

## Coralogix is not one of these six, and this repo cannot register it

The payment-forensics skill treats `mcp__Coralogix__query_dataprime` as required
reading on nearly every case. That tool is **not provisioned by this repo** —
unlike the six servers below, it's not a local Python script this project owns
and registers in `.mcp.json` with a credential env var. It's a directly-connected,
hosted MCP server, the same category as the built-in `mcp__Neo__*` tools: something
the Claude Code environment grants at the account/session level, outside any config
checked into this repository.

That means a session running with only this repo's own `.mcp.json` and
`.claude/settings.json`, with no other grant, will **not** have
`mcp__Coralogix__*` available — there is nothing here to add that would fix
that, the same way there's nothing here that makes `mcp__Neo__*` appear. If a
session is missing it, that's an environment/connector question for whoever
administers Claude Code for this account, not a credential request against
this repo (contrast with the "Getting credentials" section below, which does
apply to the six servers here). The skill's own tool-grounding section already
says to confirm the tool resolves before relying on it rather than assuming
it's present, precisely because of this gap; if it's absent, report it as the
"no matching tool found" case documented there, not as a data-doesn't-exist
finding.

## What's here

```
mcp-servers/
├── requirements.txt   shared deps for all six (mcp, httpx)
├── zendesk/server.py  zendesk_search_tickets, zendesk_get_ticket
├── datadog/server.py  datadog_search_logs, datadog_query_metrics, datadog_list_monitors
├── hubspot/server.py  hubspot_search_crm, hubspot_get_object
├── monday/server.py   monday_search_items, monday_get_item
├── stripe/server.py   stripe_get_payment_intent, stripe_get_charge, stripe_search_charges,
│                       stripe_list_refunds, stripe_get_dispute
└── paypal/server.py   paypal_get_order, paypal_get_capture, paypal_get_refund,
                        paypal_get_authorization, paypal_get_dispute, paypal_search_disputes
```

All six are registered in `.mcp.json` at the repo root. Claude Code picks
that up automatically for sessions started in this repo.

## Setup

1. Install dependencies once:
   ```
   pip install -r mcp-servers/requirements.txt
   ```
2. Get real credentials for whichever service(s) you want live — see below.
   Nothing in this repo contains a secret; `.mcp.json` references
   environment variables (`${VAR_NAME}`), not literal values.
3. Set those environment variables in whatever shell/session launches
   Claude Code (or in this environment's env var configuration, if you're
   running in a remote/managed environment rather than locally).
4. Restart the Claude Code session so it picks up the new server
   registrations and the env vars.

Without credentials set, each server still starts and its tools still show
up, but every call will fail with the target API's own auth error (401 /
403) rather than doing anything silently wrong — that's intentional, so a
missing credential is loud, not a quiet empty result.

## Getting credentials (same principle as the Snowflake PAT earlier: request
through the system's own admin flow, don't reuse or search for an existing one)

**Zendesk** — `ZENDESK_SUBDOMAIN`, `ZENDESK_EMAIL`, `ZENDESK_API_TOKEN`
Admin Center → Apps and integrations → APIs → Zendesk API → enable token
access, add an API token. The token is tied to the agent email you generate
it under, so requests are scoped to that agent's normal Zendesk
permissions, same as if they'd logged in.

**Datadog** — `DATADOG_API_KEY`, `DATADOG_APP_KEY` (`DATADOG_SITE` defaults
to `datadoghq.eu`, matching Global-e's EU instance)
Organization Settings → API Keys for the API key. Organization Settings →
Application Keys for the app key — create one scoped to a user with
`logs_read_data`, `metrics_read`, and `monitors_read`, not a broader grant
than the tools here actually use.

**HubSpot** — `HUBSPOT_ACCESS_TOKEN`
Settings → Integrations → Private Apps → create (or reuse) an app scoped to
at least `crm.objects.contacts.read`, `crm.objects.companies.read`,
`crm.objects.deals.read`. Copy the app's access token.

**Monday.com** — `MONDAY_API_TOKEN` (`MONDAY_API_VERSION` optional,
defaults to `2024-10` — bump it if Monday has shipped a newer API version
since)
Avatar menu → Administration → Connections → API, or a personal token from
your own Developer profile page if you don't have admin access.

**Stripe** — `STRIPE_API_KEY`
Dashboard → Developers → API keys → Create restricted key, scoped to
**read-only** on Charges, PaymentIntents, Refunds, and Disputes only —
nothing here needs write access, so don't hand it more than that. Use a
restricted key, not the account's full secret key, so a leak or misuse is
contained to exactly what these tools use.

**PayPal** — `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET` (`PAYPAL_ENV`
optional, defaults to `live`)
Developer Dashboard → Apps & Credentials → the REST API app tied to
Global-e's actual PayPal business account (not a personal sandbox app —
this needs to see real Global-e transactions) → Client ID and Secret.
These tools only call GET endpoints, but the underlying app credential may
also be capable of write actions depending on how it's scoped on PayPal's
side, so if a read-only-scoped app is an option when generating it, prefer
that.

If you're not the admin for one of these systems, the request goes to
whoever is — same escalation pattern as the BI team / Snowflake admin
conversation earlier, just for a different system each time.

## Design notes / limitations

- **Read-only.** None of the four servers expose a write/create/update
  tool. They only wrap search and get-by-id style GET/query endpoints.
- **Monday's search is client-side.** Monday.com's GraphQL API filters by
  column value, and column IDs are board-specific, so
  `monday_search_items` fetches a page of items from the given board and
  matches item names by substring rather than doing a server-side
  column-value filter. Fine for "find the item about X"; if you need
  precise column-value filtering on a specific board, extend the GraphQL
  query in `monday/server.py` with that board's actual column IDs.
- **No pagination beyond `limit`.** Each search tool takes a `limit`
  (capped per-service) and returns a single page. None of them loop to
  fetch "all" results — that mirrors the existing Neo tools' pattern
  (`neo_search_kb`, `jira_search`, etc., which are also single-page,
  bounded searches) rather than open-ended bulk export.
- **Smoke-tested, not integration-tested.** All six were verified to
  import cleanly and register their tools with the expected schemas using
  dummy credentials. None have been run against a real Zendesk / Datadog /
  HubSpot / Monday / Stripe / PayPal account, since no real credentials
  were used or sought out to build any of them. Sanity-check the first
  real call against each service once credentials are in place.
- **Stripe's API never returns full card numbers or CVVs**, by design —
  the richest `stripe_get_charge` ever surfaces is brand/last4/funding and
  AVS/CVC *check results* (match/no_match/unavailable). That's exactly the
  fraud-signal evidence the payment-forensics skill's Mode A expects;
  redaction for customer/merchant-facing output is that skill's Card Data
  Guard, not this server's job.
- **PayPal only covers the V2 REST API integration.** Global-e also has a
  legacy V1 (NVP) PayPal integration per the internal docs
  (`PayPalController` vs `PayPalV2Controller`); transactions processed
  through the legacy path before the V2 migration won't be reachable
  through these tools. PayPal disputes are also worth calling out: they
  route through their own dedicated path at Global-e, separate from the
  Justt-based chargeback pipeline other gateways use, so
  `paypal_get_dispute` / `paypal_search_disputes` are the only way to
  reach that data from Claude Code — there's no Coralogix/Justt shortcut
  for PayPal disputes the way there is for Adyen chargebacks.
