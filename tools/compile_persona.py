"""Compile the canonical Dudley persona for a selected host."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from payment_forensics.persona_contract import compile_persona


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("target", choices=("codex", "claude", "cursor", "grok"))
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(compile_persona(args.target), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
