# Agent operating contract

This repository contains a payment-forensics workflow. The domain skill is the
source of truth for investigations and must be read before changing behavior:

- `.agents/skills/payment-forensics/SKILL.md` for the Codex-compatible skill.
- `.claude/skills/payment-forensics/SKILL.md` for the Claude-compatible copy.
- `.agents/skills/automatic-humanizer/SKILL.md` and
  `.claude/skills/automatic-humanizer/SKILL.md` for Mode B and Mode C wording.
- `VOICE.md` for the shared writing target.
- `DUDLEY_PERSONA.md` and `DUDLEY_EXAMPLES.md` for Dudley's stable identity and
  conversational repair patterns.

## Drift controls

- Treat the two payment-forensics skill files as one policy with small,
  explicitly environment-specific tool sections.
- Keep the two automatic-humanizer files byte-for-byte identical.
- Run `python tools/check_instruction_drift.py` after changing either skill.
- Run the test suite before committing: `python -m unittest discover -s tests`.
- Keep important workflow state in structured controller state or a checked-in
  file, not only in conversation history.

## Writing boundary

Humanizing means clearer, more natural, person-to-person language. It does not
mean adding warmth, opinions, personal experience, certainty, or unsupported
facts. Evidence, identifiers, dates, amounts, uncertainty, audience rules, and
payment-forensics safety constraints always win over style preferences.
