"""Fail-closed local preflight for a Dudley release.

This checks what can be proven from the repository. It deliberately reports
live connector, security, monitoring, rollback, and approval evidence as
external gates rather than guessing that they passed.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def _command(label: str, args: list[str]) -> dict[str, Any]:
    result = subprocess.run(args, cwd=ROOT, text=True, capture_output=True)
    return {
        "name": label,
        "status": "PASS" if result.returncode == 0 else "FAIL",
        "returncode": result.returncode,
        "output": (result.stdout + result.stderr).strip()[-4000:],
    }


def build_report() -> dict[str, Any]:
    required_files = [
        ".agents/skills/payment-forensics/SKILL.md",
        ".claude/skills/payment-forensics/SKILL.md",
        ".agents/skills/automatic-humanizer/SKILL.md",
        ".claude/skills/automatic-humanizer/SKILL.md",
        "VOICE.md",
        "persona_contract.json",
        "docs/production-readiness.md",
        "docs/connector-test-report.md",
    ]
    files = [
        {"path": path, "status": "PASS" if (ROOT / path).is_file() else "FAIL"}
        for path in required_files
    ]
    checks = [
        _command("instruction drift", [sys.executable, "tools/check_instruction_drift.py"]),
        _command("unit and regression tests", [sys.executable, "-m", "unittest", "discover", "-s", "tests"]),
    ]
    local_pass = all(item["status"] == "PASS" for item in files + checks)
    external_gates = [
        "live Admin connector test report",
        "live payment-provider connector test report",
        "live Coralogix connector test report",
        "attachment/PDF test report",
        "timeout, stale-result, duplicate-event, and contradiction tests",
        "monitoring and alert links",
        "rollback test result",
        "privacy and security review",
        "named production approver",
    ]
    return {
        "product": "Dudley payment-forensics engine",
        "local_status": "PASS" if local_pass else "FAIL",
        "release_status": "PENDING_EXTERNAL_SIGN_OFF",
        "checks": checks,
        "required_files": files,
        "external_gates": [{"name": name, "status": "PENDING"} for name in external_gates],
        "decision": (
            "Local repository checks pass; deployment is not approved until every external gate is attached."
            if local_pass
            else "Do not release: one or more local preflight checks failed."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args()
    report = build_report()
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Local preflight: {report['local_status']}")
        print(f"Release status: {report['release_status']}")
        for check in report["checks"]:
            print(f"- {check['name']}: {check['status']}")
        print(f"- external gates pending: {len(report['external_gates'])}")
        print(report["decision"])
    return 0 if report["local_status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
