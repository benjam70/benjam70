"""Optional local Vale integration for Mode B/C prose quality."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import shutil
import subprocess
import tempfile


@dataclass(frozen=True)
class ValeResult:
    available: bool
    allowed: bool
    skipped: bool = False
    messages: tuple[str, ...] = ()


def run_vale(text: str, *, mode: str, executable: str = "vale", styles_path: str | None = None) -> ValeResult:
    """Run Vale locally when installed; never send text to a hosted service."""
    project_root = Path(__file__).resolve().parents[1]
    binary = shutil.which(executable)
    if binary is None and executable == "vale":
        bundled = project_root / ".tools" / "vale" / "vale.exe"
        if bundled.is_file():
            binary = str(bundled)
    if not binary:
        return ValeResult(available=False, allowed=True, skipped=True)
    if styles_path is None:
        project_config = project_root / ".vale.ini"
        if project_config.exists():
            styles_path = str(project_config)
    with tempfile.TemporaryDirectory(prefix="payment-forensics-vale-") as directory:
        path = Path(directory) / ("mode-c.md" if str(mode).upper() == "C" else "mode-b.md")
        path.write_text(text, encoding="utf-8")
        command = [binary, "--output=JSON", "--no-exit", str(path)]
        if styles_path:
            command.insert(1, f"--config={styles_path}")
        try:
            completed = subprocess.run(command, capture_output=True, text=True, timeout=10, check=False)
        except (OSError, subprocess.TimeoutExpired):
            # A bundled checker may exist but be blocked by host policy. It is
            # optional quality feedback, never a reason to fail a case.
            return ValeResult(available=False, allowed=True, skipped=True)
        if completed.returncode not in {0, 1, 2}:
            return ValeResult(True, False, messages=(f"Vale failed: {completed.stderr.strip() or completed.returncode}",))
        try:
            payload = json.loads(completed.stdout or "{}")
        except json.JSONDecodeError:
            return ValeResult(True, False, messages=("Vale returned invalid JSON",))
        alerts_found = []
        for file_result in payload.values():
            if isinstance(file_result, dict):
                alerts_found.extend(file_result.get("alerts", []))
            elif isinstance(file_result, list):
                alerts_found.extend(file_result)
        messages = tuple(
            f"{alert.get('Severity', 'warning')}: {alert.get('Message', 'Vale style issue')}"
            for alert in alerts_found if isinstance(alert, dict)
        )
        errors = any(
            alert.get("Severity") == "error"
            for alert in alerts_found
            if isinstance(alert, dict)
        )
        return ValeResult(True, not errors, messages=messages)
