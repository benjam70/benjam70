"""Startup checks for the authoritative local payment-forensics installation.

This module deliberately separates two different concerns that used to be
checked together:

- ``check_startup_integrity`` answers "is the engine itself safe to run":
  are its core modules present, and is the one authoritative instructions
  file it actually loads (``.agents/skills/payment-forensics/SKILL.md``)
  present and free of dropped safety markers. This must hold in any
  checkout, regardless of which coding host (if any) is being used.
- ``check_host_integration`` answers "which hosts are wired up here": it
  reports presence of Claude Code's and Codex's own integration files as
  informational data. A host not being configured in a given checkout is
  normal (e.g. an isolated worktree, a CI runner, or a Cursor-only setup)
  and must never fail engine startup.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class IntegrityResult:
    allowed: bool
    missing: tuple[str, ...] = ()


@dataclass(frozen=True)
class HostStatus:
    """Presence of one host's integration files. Informational only."""

    present: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    skill_copies_match: bool | None = None


def check_startup_integrity(root: str | Path | None = None) -> IntegrityResult:
    """Check that the engine and its authoritative instructions are intact.

    Host-specific integration files (Claude Code's or Codex's own hooks,
    config, and settings) are intentionally out of scope here - see
    ``check_host_integration`` for those.
    """
    project_root = Path(root) if root is not None else Path(__file__).resolve().parents[1]
    required = (
        project_root / "payment_forensics" / "controller.py",
        project_root / "payment_forensics" / "engine.py",
        project_root / "payment_forensics" / "output_validator.py",
        project_root / ".agents" / "skills" / "payment-forensics" / "SKILL.md",
        project_root / ".agents" / "skills" / "automatic-humanizer" / "SKILL.md",
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
    authoritative = project_root / ".agents" / "skills" / "payment-forensics" / "SKILL.md"
    content = authoritative.read_text(encoding="utf-8")
    incomplete = tuple(f"{authoritative}: missing marker {marker}" for marker in prompt_markers if marker not in content)
    return IntegrityResult(not incomplete, incomplete)


def check_host_integration(root: str | Path | None = None) -> dict[str, HostStatus]:
    """Report which coding hosts have their own integration files wired up.

    This is informational: a missing host is never a failure, since not
    every checkout (or every host) needs every other host's files present.
    """
    project_root = Path(root) if root is not None else Path(__file__).resolve().parents[1]

    def status(paths: dict[str, Path]) -> HostStatus:
        present = tuple(name for name, path in paths.items() if path.is_file())
        missing = tuple(name for name, path in paths.items() if not path.is_file())
        return HostStatus(present=present, missing=missing)

    claude_paths = {
        ".claude/hooks/session-start.sh": project_root / ".claude" / "hooks" / "session-start.sh",
        ".claude/settings.json": project_root / ".claude" / "settings.json",
        ".claude/skills/payment-forensics/SKILL.md": project_root / ".claude" / "skills" / "payment-forensics" / "SKILL.md",
        ".claude/skills/automatic-humanizer/SKILL.md": project_root / ".claude" / "skills" / "automatic-humanizer" / "SKILL.md",
    }
    claude_status = status(claude_paths)

    agents_skill = project_root / ".agents" / "skills" / "payment-forensics" / "SKILL.md"
    claude_skill = project_root / ".claude" / "skills" / "payment-forensics" / "SKILL.md"
    skill_copies_match = None
    if agents_skill.is_file() and claude_skill.is_file():
        skill_copies_match = agents_skill.read_text(encoding="utf-8") == claude_skill.read_text(encoding="utf-8")
    claude_status = HostStatus(claude_status.present, claude_status.missing, skill_copies_match)

    codex_paths = {
        ".codex/config.toml": project_root / ".codex" / "config.toml",
        ".codex/hooks/session-start.sh": project_root / ".codex" / "hooks" / "session-start.sh",
    }
    codex_status = status(codex_paths)

    return {"claude_code": claude_status, "codex": codex_status}
