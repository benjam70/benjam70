"""CLI entry point for a configured Dudley hybrid investigation."""

from __future__ import annotations

import argparse
import importlib
from pathlib import Path

from payment_forensics import BGEReranker, HybridEngine, OpenAIResponsesModel, RerankingSearchExecutor, check_startup_integrity


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a Dudley payment-forensics investigation")
    parser.add_argument("case_file", type=Path)
    parser.add_argument("--instructions", type=Path, default=Path(".agents/skills/payment-forensics/SKILL.md"))
    parser.add_argument("--adapter-module", required=True, help="Python module exposing build_search_executor()")
    parser.add_argument("--bge-rerank", action="store_true", help="Rerank returned case-scoped facts with the local BGE model")
    args = parser.parse_args()
    integrity = check_startup_integrity(Path(__file__).resolve().parent)
    if not integrity.allowed:
        parser.error("payment-forensics startup integrity check failed: " + "; ".join(integrity.missing))
    instructions = args.instructions.read_text(encoding="utf-8")
    model = OpenAIResponsesModel(instructions=instructions)
    adapter_module = importlib.import_module(args.adapter_module)
    tools = adapter_module.build_search_executor()
    if args.bge_rerank:
        tools = RerankingSearchExecutor(tools, BGEReranker.from_pretrained())
    result = HybridEngine(model, tools).investigate(args.case_file.read_text(encoding="utf-8"))
    print(result.output if result.output else {"status": result.status, "gate": result.gate.reasons})
    return 0 if result.status == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
