# Dudley failure runbook

## Immediate rule

If a required source fails, returns stale or partial data, or cannot be tied to the
case, leave the investigation blocked. Do not manually convert the gap into a finding.

## Coralogix or connector failure

1. Keep the case blocked.
2. Record the source, query, time window, error, and run ID.
3. Retry only with the approved retry policy.
4. If the retry remains incomplete, route the case to a human investigator.

## Contradictory sources

1. Keep both evidence items.
2. Check identifiers, event dates, amounts, and source priority.
3. Search a third source when available.
4. Resolve explicitly or leave the case blocked.

## Duplicate event or webhook

1. Preserve the raw event references.
2. Check the deterministic ledger's deduplication result.
3. Do not issue or recommend a second refund.
4. Escalate only with the event IDs and source evidence.

## Incorrect draft

1. Do not send the draft.
2. Record the missing, altered, or unsupported fact.
3. Re-run from the saved snapshot when possible.
4. If the corrected draft still fails validation, keep the case blocked.

## Rollback

1. Disable automatic progression to the next processing stage.
2. Return to the last approved engine version.
3. Preserve the audit record and replay hash.
4. Record the incident, affected cases, and approver.
