# Dudley connector test report

This is a template for recording live connector evidence. Use anonymized case IDs
and never paste full card data, CVV/CVC values, or authentication secrets.

| Connector | Case fixture | Expected behavior | Actual behavior | Evidence link or run ID | Result | Owner |
|---|---|---|---|---|---|---|
| Admin |  |  |  |  | PENDING |  |
| Payment provider |  |  |  |  | PENDING |  |
| Coralogix |  |  |  |  | PENDING |  |
| Ticket system |  |  |  |  | PENDING |  |
| PDF attachment |  |  |  |  | PENDING |  |

## Required scenarios

- Full refund with ARN
- Partial refund
- Missing refund
- Split capture or split refund
- Authorization greater than capture
- Duplicate webhook
- Failed lookup and timeout
- Contradictory Admin and provider records
- Unreadable or contradictory PDF
- Provider-specific no-path case
