# Dudley production-readiness record

This document records release evidence. It does not change engine behavior.

## Release scope

- Product: Dudley payment-forensics engine
- Runtime mode: approval-gated operation
- Current repository verification date: 2026-09-06
- Engine behavior: investigation, reconciliation, evidence gating, Mode B/C validation

## Verified in this repository

| Check | Result | Evidence |
|---|---|---|
| Unit and regression suite | PASS | `.venv\\Scripts\\python.exe -m unittest discover -s tests` |
| Instruction-copy drift | PASS | `.venv\\Scripts\\python.exe tools\\check_instruction_drift.py` |
| Deterministic payment ledger | PRESENT | `payment_forensics/ledger.py` |
| Approved-evidence output gate | PRESENT | `payment_forensics/controller.py`, `output_validator.py` |
| Snapshot and replay metadata | PRESENT | `controller.py`, `audit.py` |
| Mode B/C persona checks | PRESENT | `persona_eval.py`, `engine.py` |
| Approval gate | EXTERNAL CONTROL | Verify in the host application |
| Repeatable local preflight | PRESENT | `tools/production_preflight.py` |

## Owner-attested checks

These cannot be proven from source inspection alone and require an owner to attach evidence.

- [ ] Live Admin connector test report
- [ ] Live payment-provider connector test report
- [ ] Live Coralogix connector test report
- [ ] Attachment and PDF test report
- [ ] Timeout, stale-result, duplicate-event, and contradiction tests
- [ ] Monitoring and alert links
- [ ] Rollback test result
- [ ] Privacy and security review
- [ ] Named production approver

## Release decision

Status: PENDING OWNER SIGN-OFF

The repository supports approval-gated deployment. Run
`.venv\\Scripts\\python.exe tools\\production_preflight.py` for the local gate.
Full production sign-off requires
the owner-attested checks above and an immutable release commit recorded below.

- Release commit: ____________________
- Approver: ____________________
- Approval date: ____________________
- Notes: ____________________
