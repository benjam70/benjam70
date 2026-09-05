"""Portable Dudley persona contract and host-neutral compiler."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "persona_contract.json"


def load_persona_contract(path: str | Path = CONTRACT_PATH) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict) or not value.get("name") or not value.get("version"):
        raise ValueError("persona contract must contain name and version")
    return value


def persona_hash(contract: Mapping[str, Any] | None = None) -> str:
    value = contract or load_persona_contract()
    material = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return sha256(material).hexdigest()


def compile_persona(target: str, contract: Mapping[str, Any] | None = None) -> str:
    """Compile one contract into plain instructions for any host."""
    value = dict(contract or load_persona_contract())
    target_name = str(target).strip().lower()
    header = {
        "codex": "Read this as Dudley's identity contract for the current task.",
        "claude": "Use this as Dudley's identity contract for the current task.",
        "cursor": "Apply this as Dudley's identity contract while assisting.",
        "grok": "Use this as Dudley's stable identity and communication contract."
    }.get(target_name, "Use this as Dudley's stable identity contract.")
    return "\n".join((header, f"Persona version: {value['version']}", f"Persona hash: {persona_hash(value)}", json.dumps(value, indent=2, ensure_ascii=False), "Payment-forensics rules and evidence always override this contract."))


def compile_all(contract: Mapping[str, Any] | None = None) -> dict[str, str]:
    return {target: compile_persona(target, contract) for target in ("codex", "claude", "cursor", "grok")}

