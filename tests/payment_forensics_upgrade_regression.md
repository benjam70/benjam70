# Payment Forensics Upgrade Regression Set

This is an anonymized controller regression manifest. It is intentionally separate from the payment-domain skill, so benchmark coverage can evolve without changing Mode A/B/C instructions.

| ID | Case shape | Expected terminal state | Required control | Expected key facts |
|---|---|---|---|---|
| R01 | Successful refund with ARN | Refunded, customer-bank receipt not proven | Positive-event acceptance, funds-location distinction | Provider refund event, ARN, amount, currency |
| R02 | Provider refund failure | Captured or settled, refund unresolved | Negative-claim standard | Failed refund, no successful provider event only after covered searches |
| R03 | Initial refund failure, later success | Refunded | Iterative loop, temporal pass, retry check | Later authoritative success supersedes failure |
| R04 | Open dispute blocks refund | Held by dispute process or unknown | Competing hypotheses, dispute source check | Dispute ID/status and refund attempt kept separate |
| R05 | Duplicate capture | Duplicate or unresolved funds movement | Idempotency and contradiction pass | Same intent/IDs, two capture attempts, amounts |
| R06 | Partial refund | Partially refunded, remaining amount explicit | Currency and reconciliation rules | Original, refund, outstanding amounts in one currency |
| R07 | Multiple refunds on one order | Fully or partially refunded | Immutable ledger and event linking | Each refund remains a separate event and reference |
| R08 | Admin/provider mismatch | Provider-priority state, or unknown if unresolved | Source priority, freshness, third-source search | Both facts retained, conflict disclosed or resolved |
| R09 | Coralogix event buried in unrelated logs | State from validated matching event | Result validation, search diversification | Correct order/payment/event fields, unrelated hit rejected |
| R10 | Missing order identifier | Candidate or explicitly unknown | Identity validation and no false confirmation | Alternate identifiers searched, candidate never promoted |
| R11 | FX/tax discrepancy | Reconciled only with sourced FX, otherwise unknown | Currency rule and evidence ledger | Tax/FX source, native amounts, conversion or disclosed gap |
| R12 | Source timeout or partial result | Unknown or provisional | Coverage gate and source-failure disclosure | PARTIAL/FAILED does not count as CHECKED |

## Scorecard

Run each case against the current controller and the upgraded controller. Record pass/fail for:

```text
terminal state correct
amount correct
currency correct
provider state correct
ARN/reference found when available
dispute detected
retry detected
contradictions resolved or disclosed
negative claims sufficiently supported
critical evidence missed
hallucinated fact
stopped too early
Mode B facts accurate
Mode C facts accurate
```

The repository contains no historical or anonymized case payloads, so this manifest defines the required regression shapes and assertions. It is not a claim that live case execution occurred.
