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

## Writing boundary

Humanizing means clearer, more natural, person-to-person language. It does not
mean adding warmth, opinions, personal experience, certainty, or unsupported
facts. Evidence, identifiers, dates, amounts, uncertainty, audience rules, and
payment-forensics safety constraints always win over style preferences.
