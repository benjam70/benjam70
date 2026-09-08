"""Fail-closed checks for duplicated agent instructions.

The payment-forensics check is generation-based, not marker-based: every
platform SKILL.md must byte-match what `tools/render_skills.py` would produce
right now from the single canonical source in `skills/payment-forensics/`.
That closes the gap a marker check leaves open, where a file keeps the right
section headings but the methodology underneath has quietly diverged, or
someone hand-edits a generated file directly instead of the shared source.
"""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from render_skills import TARGETS, render_all  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    errors: list[str] = []
    humanizer_paths = (
        ROOT / ".agents/skills/automatic-humanizer/SKILL.md",
        ROOT / ".claude/skills/automatic-humanizer/SKILL.md",
    )
    humanizers = []
    for path in humanizer_paths:
        if not path.is_file():
            errors.append(f"missing: {path}")
        else:
            humanizers.append(path.read_bytes())
    if len(humanizers) == 2 and humanizers[0] != humanizers[1]:
        errors.append("automatic-humanizer skill copies differ")

    rendered = render_all()
    for platform, expected in rendered.items():
        path = TARGETS[platform]
        if not path.is_file():
            errors.append(f"missing: {path}")
            continue
        actual = path.read_bytes()
        if actual != expected:
            errors.append(
                f"{path}: does not match generated output from skills/payment-forensics/ "
                f"(edit the canonical source and run `python tools/render_skills.py`, "
                f"do not hand-edit this file)"
            )

    if errors:
        print("Instruction drift check failed:", file=sys.stderr)
        print("\n".join(f"- {error}" for error in errors), file=sys.stderr)
        return 1
    print("Instruction drift check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
