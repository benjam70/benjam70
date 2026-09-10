# Agent operating contract

This repository contains a payment-forensics workflow. Dudley's investigation
methodology lives in exactly one place and must be read before changing
behavior:

- `skills/payment-forensics/CORE.md` is the canonical engine: mandatory
  investigation steps, evidence hierarchy, Mode A/B/C, and everything else
  that is not host-specific. Edit this, never a generated `SKILL.md`.
- `skills/payment-forensics/adapters/*.md` are thin, host-specific tool
  grounding notes (which MCP tools resolve, their exact names). These should
  describe how to reach evidence in that host, never repeat or fork the
  methodology in `CORE.md`.
- `.agents/skills/payment-forensics/SKILL.md` and
  `.claude/skills/payment-forensics/SKILL.md` are **generated** by
  `python tools/render_skills.py` from the two sources above. Do not hand-edit
  them; `tools/check_instruction_drift.py` fails the build if they no longer
  match what the generator would produce.
- `.agents/skills/automatic-humanizer/SKILL.md` and
  `.claude/skills/automatic-humanizer/SKILL.md` for Mode B and Mode C wording
  (still hand-synced, kept byte-identical by the same drift check).
- `VOICE.md` for the shared writing target.
- `DUDLEY_PERSONA.md` and `DUDLEY_EXAMPLES.md` for Dudley's stable identity and
  conversational repair patterns.

## Drift controls

- No payment-forensics investigation logic is allowed inside a host-specific
  adapter or a generated `SKILL.md`. If a change makes Dudley better at
  investigating payments, it belongs in `skills/payment-forensics/CORE.md` so
  it improves every host, not one.
- After editing `skills/payment-forensics/CORE.md` or any file under
  `skills/payment-forensics/adapters/`, run
  `python tools/render_skills.py` to regenerate the platform copies, then
  `python tools/check_instruction_drift.py` to confirm they match.
- Keep the two automatic-humanizer files byte-for-byte identical.
- Run the test suite before committing: `python -m unittest discover -s tests`.
- Keep important workflow state in structured controller state or a checked-in
  file, not only in conversation history.
- The model backend (Claude, Codex, Gemini, or anything else) is a swappable
  `ProposalModel` implementation (see `payment_forensics/adapters.py`), never
  a reason to fork the engine or the skill text.

## Loop prevention

`HybridEngine`/`CaseController` enforce these automatically; they need no
model cooperation and no skill-text instruction to work:

- `CaseController.find_prior_search` / `note_skipped_search`: an exact-duplicate
  search (same source, query, identifiers, window) is not re-executed against
  a real tool a second time.
- `CaseController.circuit_breaker_open` (`CIRCUIT_BREAKER_THRESHOLD = 2`): a
  source that has failed twice in a row this case is not retried; a Data Gap
  should be recorded instead.
- `CaseController._consecutive_no_novelty` / `_replan_required`: three
  searches in a row that add no new evidence block completion until the model
  explicitly re-plans (`accept_replan`).
- Avenue checklist + round verdicts (`PRODUCTIVE` / `QUERY_STALE` /
  `EXHAUSTED`): completion is blocked while predicates remain `OPEN`; stale
  rounds force pivots; `complete=true` is ignored until avenues close or the
  budget is exhausted with an exhaustion certificate.
- CoVe, FineVerify subclaims, read-gate, claim entailment, and terminal-state
  consistency run before Mode A/B/C output is accepted.
- `HybridEngine(max_rounds=16)` is a hard backstop, not the primary defense.

All four survive `CaseController.snapshot()`/`from_snapshot()` round-trips, so
a resumed multi-turn investigation does not silently lose this state.

`tools/dudley_canary.py` runs the same golden case, same canned tool data,
through every model backend with a credential set (`OPENAI_API_KEY`,
`ANTHROPIC_API_KEY`, `GEMINI_API_KEY`), the daily-canary pattern for catching
model drift a provider introduces silently. `tests/golden_cases.json`
currently has spec tags only (id/mode/tier/required), no `case_input` or
`canned_results` yet. Populating real fixtures is separate work; the script
reports incomplete cases as skipped rather than fabricating fixture data.

## Writing boundary

Humanizing means clearer, more natural, person-to-person language. It does not
mean adding warmth, opinions, personal experience, certainty, or unsupported
facts. Evidence, identifiers, dates, amounts, uncertainty, audience rules, and
payment-forensics safety constraints always win over style preferences.
