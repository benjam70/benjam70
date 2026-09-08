"""Render platform SKILL.md copies from one canonical Dudley engine source.

Dudley's investigation methodology (payment lifecycle rules, evidence
hierarchy, Mode A/B/C, gateway integration notes) lives in exactly one place:
`skills/payment-forensics/CORE.md`. Each platform only contributes a small
tool-grounding section describing how to reach evidence in that environment
(`skills/payment-forensics/adapters/<platform>.md`). This script concatenates
frontmatter + adapter + core for each platform and writes the result to the
path each host actually reads its skill from.

Never hand-edit a generated `SKILL.md` directly — edit the source pieces here
and re-run this script. `tools/check_instruction_drift.py` fails the build if
a generated file no longer matches what this script would produce.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "skills" / "payment-forensics"

TARGETS = {
    "claude": ROOT / ".claude" / "skills" / "payment-forensics" / "SKILL.md",
    "codex": ROOT / ".agents" / "skills" / "payment-forensics" / "SKILL.md",
}


def render(platform: str) -> bytes:
    frontmatter = (SOURCE / "frontmatter.md").read_bytes()
    adapter = (SOURCE / "adapters" / f"{platform}.md").read_bytes()
    core = (SOURCE / "CORE.md").read_bytes()
    return frontmatter + adapter + core


def render_all() -> dict[str, bytes]:
    return {platform: render(platform) for platform in TARGETS}


def main() -> int:
    for platform, content in render_all().items():
        target = TARGETS[platform]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        print(f"wrote {target.relative_to(ROOT)} ({len(content)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
