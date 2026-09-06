"""Optional local AI-writing-tell detection for Mode B/C prose quality.

Vale (vale_linter.py) enforces house style, Harper (grammar.py) checks
grammar, the relevance checker (relevance.py) checks semantic overlap with a
question. None of those catch the fourth axis this module targets: text that
is stylistically clean and grammatically correct and relevant, but still
reads as AI-generated, defining-a-term cadence, negative parallelism ("not
just X, it's Y"), hedge stacks, puffed significance, banned AI vocabulary
clusters, and so on.

This wraps a standalone regex-based checker (slop-check.py), not a model, so
it is fully local and deterministic like Vale and Harper. Deliberately
opt-in: a missing script is a skip, not a failure, same pattern as the other
three optional checks.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


@dataclass(frozen=True)
class SlopCheckResult:
    available: bool
    allowed: bool
    skipped: bool = False
    messages: tuple[str, ...] = ()


def run_slop_check(text: str, *, script: str | None = None, timeout: float = 10.0) -> SlopCheckResult:
    """Run the local AI-writing-tell checker; never sends text anywhere."""
    project_root = Path(__file__).resolve().parents[1]
    path_to_script = Path(script) if script else project_root / ".tools" / "slop_check" / "slop_check.py"
    if not path_to_script.is_file():
        return SlopCheckResult(available=False, allowed=True, skipped=True)

    python = sys.executable or shutil.which("python3") or "python3"
    with tempfile.TemporaryDirectory(prefix="payment-forensics-slop-") as directory:
        target = Path(directory) / "draft.md"
        target.write_text(text, encoding="utf-8")
        payload = json.dumps({"tool_input": {"file_path": str(target)}})
        try:
            completed = subprocess.run(
                [python, str(path_to_script)],
                input=payload,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return SlopCheckResult(True, True, skipped=True, messages=(f"slop-check did not run: {exc}",))

        if completed.returncode == 0:
            return SlopCheckResult(True, True, messages=())
        if completed.returncode == 2:
            lines = tuple(line for line in completed.stderr.splitlines() if line.strip())
            return SlopCheckResult(True, False, messages=lines)
        return SlopCheckResult(True, True, skipped=True, messages=(f"slop-check exited {completed.returncode}: {completed.stderr.strip()}",))
