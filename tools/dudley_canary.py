"""Run the same golden cases through every configured model backend.

This is the daily-canary pattern for catching model drift: the same case
input, the same canned tool data, and the same HybridEngine/CaseController
rules go to every model backend, so a difference in the result is
attributable to the model, not to different tools, different prompts, or
different rules. See `payment_forensics/regression.py` for the underlying
`run_cross_model_regression` primitive this wraps.

Requirements this script does NOT satisfy on its own:

- It only runs a model backend whose API key is present in the environment
  (OPENAI_API_KEY, ANTHROPIC_API_KEY, GEMINI_API_KEY/GOOGLE_API_KEY). Missing
  keys are reported and that backend is skipped, not treated as a failure.
- It only runs a golden case that actually has a "case_input" string and a
  "canned_results" mapping of source -> canned tool result. As of this
  writing, `tests/golden_cases.json` has neither: it only has id/mode/tier/
  required tags, a spec for what a case should cover, not a runnable fixture.
  Fabricating realistic-looking payment data here to make the demo look more
  complete would be exactly the kind of unsourced fact this whole engine
  exists to prevent, so incomplete cases are skipped and reported, not
  invented. Turning them into real fixtures (real or carefully constructed
  case input, canned evidence per source, and per-tag assertions) is
  separate, deliberate authoring work.

Usage:
    python tools/dudley_canary.py [path/to/golden_cases.json]
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Callable, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from payment_forensics.controller import EvidenceItem, ToolResult, SearchResultState  # noqa: E402
from payment_forensics.engine import EngineResult, HybridEngine, SearchExecutor, SearchRequest  # noqa: E402
from payment_forensics.regression import RegressionResult, run_cross_model_regression  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GOLDEN_CASES_PATH = ROOT / "tests" / "golden_cases.json"
DEFAULT_INSTRUCTIONS_PATH = ROOT / ".agents" / "skills" / "payment-forensics" / "SKILL.md"

# Mirrors this skill's own Mode B/C gateway-naming rule: PayPal and Klarna may
# be named, other PSP brands and the log source itself may not.
BANNED_GATEWAY_NAMES = (
    "adyen", "stripe", "checkout.com", "worldpay", "coralogix", "smart2pay",
    "newebpay", "mondu", "revolut", "dlocal", "amazon pay", "virtual payment",
)
BANNED_INTERNAL_JARGON = (
    "coralogix", "psp_reference", "mcp__", "dataprime", "controller_state", "evidence_ledger",
)
DATE_PATTERN = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
REFERENCE_PATTERN = re.compile(r"\b[A-Za-z]{2,5}\d{6,}[A-Za-z]{0,2}\b|\b(?:pi|ch|re|du)_[A-Za-z0-9]{6,}\b")
AMOUNT_PATTERN = re.compile(r"\b\d+(?:[.,]\d{2})\b")
TERMINAL_STATE_WORDS = ("refunded", "reversed", "settlement", "pending", "disputed", "unknown", "chargeback")


class CannedSearchExecutor(SearchExecutor):
    """Serves the same fixed evidence to every model for one golden case.

    Only the model backend varies between runs; the tool data is identical,
    so a difference in the finding is attributable to the model's
    investigation, not to different data reaching it.
    """

    def __init__(self, canned_results: Mapping[str, Mapping[str, Any]]) -> None:
        self._canned = canned_results

    def search(self, request: SearchRequest) -> ToolResult:
        raw = self._canned.get(request.source)
        if raw is None:
            return ToolResult(request.source, SearchResultState.NO_RESULT, True)
        return ToolResult(
            source=request.source,
            result_state=SearchResultState(raw.get("result_state", "NO_RESULT")),
            scoped_to_case=bool(raw.get("scoped_to_case", True)),
            truncated=bool(raw.get("truncated", False)),
            error=raw.get("error"),
            facts=tuple(EvidenceItem(**fact) for fact in raw.get("facts", ())),
        )


def tag_checkers() -> dict[str, Callable[[str, str], bool]]:
    """Heuristic, text-only checks per `required` tag. Not a substitute for the

    real evidence-based validators in output_validator.py/humanize.py, which
    need fact-id/ledger context this script doesn't reconstruct. Useful only
    for catching gross regressions: a missing subject line, a leaked gateway
    name, no date or reference at all.
    """
    return {
        "date": lambda output, case_input: bool(DATE_PATTERN.search(output)),
        "refund": lambda output, case_input: "refund" in output.lower(),
        "reference": lambda output, case_input: bool(REFERENCE_PATTERN.search(output)),
        "no-new-facts": lambda output, case_input: all(amount in case_input for amount in AMOUNT_PATTERN.findall(output)),
        "subject": lambda output, case_input: "subject:" in output.lower(),
        "plain-language": lambda output, case_input: not any(term in output.lower() for term in BANNED_INTERNAL_JARGON),
        "no-gateway": lambda output, case_input: not any(name in output.lower() for name in BANNED_GATEWAY_NAMES),
        "timeline": lambda output, case_input: len(DATE_PATTERN.findall(output)) >= 2 or "timeline" in output.lower(),
        "contradiction": lambda output, case_input: "contradiction" in output.lower() or "conflict" in output.lower(),
        "terminal-state": lambda output, case_input: any(word in output.lower() for word in TERMINAL_STATE_WORDS),
    }


def build_backends() -> dict[str, Callable[[str], Any]]:
    """Return {backend_name: instructions -> ProposalModel} for every backend with a credential set."""
    from payment_forensics.adapters import LiteLLMModel, OpenAIResponsesModel

    backends: dict[str, Callable[[str], Any]] = {}
    if os.environ.get("OPENAI_API_KEY"):
        backends["openai"] = lambda instructions: OpenAIResponsesModel(instructions=instructions)
    if os.environ.get("ANTHROPIC_API_KEY"):
        backends["claude"] = lambda instructions: LiteLLMModel(instructions=instructions, model=os.environ.get("DUDLEY_CLAUDE_MODEL", "claude-opus-4-6"))
    if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
        backends["gemini"] = lambda instructions: LiteLLMModel(instructions=instructions, model=os.environ.get("DUDLEY_GEMINI_MODEL", "gemini/gemini-3-pro"))
    return backends


def load_golden_cases(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def runnable_and_skipped_cases(cases: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    runnable, skipped = [], []
    for case in cases:
        if "case_input" in case and "canned_results" in case:
            runnable.append(case)
        else:
            skipped.append(f"{case.get('id', '<unknown>')}: missing case_input and/or canned_results, not a runnable fixture yet")
    return runnable, skipped


def build_fixtures(cases: list[dict[str, Any]], checkers: Mapping[str, Callable[[str, str], bool]]) -> list[tuple[str, str, Callable[[Any], bool]]]:
    fixtures = []
    for case in cases:
        case_input = case["case_input"]
        required_tags = tuple(case.get("required", ()))

        def assertion(result: EngineResult, case_input=case_input, required_tags=required_tags) -> bool:
            if result.status != "completed" or not result.output:
                return False
            return all(checkers[tag](result.output, case_input) for tag in required_tags if tag in checkers)

        fixtures.append((case["id"], case_input, assertion))
    return fixtures


def build_model_runner(model_factory: Callable[[str], Any], instructions: str, cases_by_input: Mapping[str, Mapping[str, Any]]) -> Callable[[str], EngineResult]:
    model = model_factory(instructions)

    def runner(case_input: str) -> EngineResult:
        canned = cases_by_input[case_input].get("canned_results", {})
        executor = CannedSearchExecutor(canned)
        return HybridEngine(model, executor).investigate(case_input)

    return runner


def run_canary(cases: list[dict[str, Any]], backends: Mapping[str, Callable[[str], Any]], instructions: str) -> tuple[RegressionResult, ...]:
    checkers = tag_checkers()
    fixtures = build_fixtures(cases, checkers)
    cases_by_input = {case["case_input"]: case for case in cases}
    models = {name: build_model_runner(factory, instructions, cases_by_input) for name, factory in backends.items()}
    return run_cross_model_regression(models, fixtures)


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    golden_cases_path = Path(args[0]) if args else DEFAULT_GOLDEN_CASES_PATH
    cases = load_golden_cases(golden_cases_path)
    runnable, skipped = runnable_and_skipped_cases(cases)
    for message in skipped:
        print(f"SKIPPED: {message}")

    backends = build_backends()
    if not backends:
        print("No model API key set (OPENAI_API_KEY / ANTHROPIC_API_KEY / GEMINI_API_KEY). Nothing to run.")
        return 2
    if not runnable:
        print("No runnable golden cases (each needs case_input and canned_results). Nothing to run.")
        return 2

    instructions = DEFAULT_INSTRUCTIONS_PATH.read_text(encoding="utf-8")
    results = run_canary(runnable, backends, instructions)
    exit_code = 0
    for result in results:
        status = "PASS" if result.failed == 0 else "FAIL"
        print(f"{result.model_name}: {status} ({result.passed}/{result.passed + result.failed})")
        for failure in result.failures:
            print(f"  - {failure}")
        if result.failed:
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
