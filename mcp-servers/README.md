# MCP servers: Zendesk, Datadog, HubSpot, Monday.com

Four small, read-only MCP servers, one per system, built to fill the gap
between what the Neo AI web app can reach (all of these) and what this
Claude Code session could reach before (none of these). Each is a thin
wrapper over that system's public REST/GraphQL API using the official
MCP Python SDK.

## What's here

```
mcp-servers/
├── requirements.txt   shared deps for all four (mcp, httpx)
├── zendesk/server.py  zendesk_search_tickets, zendesk_get_ticket
├── datadog/server.py  datadog_search_logs, datadog_query_metrics, datadog_list_monitors
├── hubspot/server.py  hubspot_search_crm, hubspot_get_object
└── monday/server.py   monday_search_items, monday_get_item
```

All four are registered in `.mcp.json` at the repo root. Claude Code picks
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
- **Smoke-tested, not integration-tested.** All four were verified to
  import cleanly and register their tools with the expected schemas using
  dummy credentials. None have been run against real Zendesk / Datadog /
  HubSpot / Monday tenants, since no real credentials were used or sought
  out to build this. Sanity-check the first real call against each service
  once credentials are in place.
