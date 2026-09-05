# Dudley release checklist

This checklist is non-runtime and does not alter the engine.

- [ ] Review `docs/production-readiness.md`.
- [ ] Attach live connector results in `docs/connector-test-report.md`.
- [ ] Run the failure scenarios in the connector report.
- [ ] Run `.venv\\Scripts\\python.exe tools\\check_instruction_drift.py`.
- [ ] Run `.venv\\Scripts\\python.exe -m unittest discover -s tests`.
- [ ] Confirm approval-gated behavior in the host application.
- [ ] Confirm monitoring and alerts.
- [ ] Test rollback.
- [ ] Confirm privacy and security review.
- [ ] Record the release commit and approver.
- [ ] Run `.venv\\Scripts\\python.exe tools\\production_preflight.py` and attach its output.

## Current repository result

- Instruction drift: PASS on 2026-09-05.
- Automated tests: 114 passed on 2026-09-06.
- Full production sign-off: PENDING owner-attested evidence.
