"""Startup checks for the authoritative local payment-forensics installation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class IntegrityResult:
    allowed: bool
    missing: tuple[str, ...] = ()


def check_startup_integrity(root: str | Path | None = None) -> IntegrityResult:
    project_root = Path(root) if root is not None else Path(__file__).resolve().parents[1]
    required = (
        project_root / "payment_forensics" / "controller.py",
        project_root / "payment_forensics" / "engine.py",
        project_root / "payment_forensics" / "output_validator.py",
        project_root / ".agents" / "skills" / "payment-forensics" / "SKILL.md",
        project_root / ".agents" / "skills" / "automatic-humanizer" / "SKILL.md",
        project_root / ".claude" / "skills" / "payment-forensics" / "SKILL.md",
        project_root / ".claude" / "skills" / "automatic-humanizer" / "SKILL.md",
        project_root / ".claude" / "hooks" / "session-start.sh",
        project_root / ".codex" / "hooks" / "session-start.sh",
        project_root / ".codex" / "config.toml",
        project_root / ".claude" / "settings.json",
    )
    missing = tuple(str(path) for path in required if not path.is_file())
    if missing:
        return IntegrityResult(False, missing)

    # Presence alone is not enough: catch an accidentally empty or incomplete
    # prompt copy before a session can rely on it.
    prompt_markers = (
        "RULE 0",
        "MODE B",
        "MODE C",
        "SOURCE-TAG RULE",
        "Coralogix",
    )
    incomplete = []
    for path in (
        project_root / ".agents" / "skills" / "payment-forensics" / "SKILL.md",
        project_root / ".claude" / "skills" / "payment-forensics" / "SKILL.md",
    ):
        content = path.read_text(encoding="utf-8")
        incomplete.extend(f"{path}: missing marker {marker}" for marker in prompt_markers if marker not in content)
    return IntegrityResult(not incomplete, tuple(incomplete))
