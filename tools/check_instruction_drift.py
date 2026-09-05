"""Fail-closed checks for duplicated agent instructions."""

from __future__ import annotations

from pathlib import Path
import sys


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

    payment_markers = (
        "RULE 0",
        "STRICT INVESTIGATION CONTROLLER",
        "SOURCE-TAG RULE",
        "MODE B",
        "MODE C",
        "Coralogix",
    )
    for path in (
        ROOT / ".agents/skills/payment-forensics/SKILL.md",
        ROOT / ".claude/skills/payment-forensics/SKILL.md",
    ):
        if not path.is_file():
            errors.append(f"missing: {path}")
            continue
        text = path.read_text(encoding="utf-8")
        for marker in payment_markers:
            if marker not in text:
                errors.append(f"{path}: missing marker {marker}")

    if errors:
        print("Instruction drift check failed:", file=sys.stderr)
        print("\n".join(f"- {error}" for error in errors), file=sys.stderr)
        return 1
    print("Instruction drift check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
