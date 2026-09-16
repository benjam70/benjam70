"""Run the same golden cases through every configured model backend.

This is the daily-canary pattern for catching model drift: the same case
input, the same canned tool data, and the same HybridEngine/CaseController
rules go to every model backend, so a difference in the result is
attributable to the model, not to different tools, different prompts, or
different rules. See `payment_forensics/regression.py` for the underlying
`run_cross_model_regression` primitive this wraps.

Requirements this script does NOT satisfy on its own:

- It only runs a configured model backend. Provider API credentials are read
  from environment variables; missing configuration skips that backend.
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
import shutil
import sys
import time
import argparse
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from payment_forensics.controller import EvidenceItem, ToolResult, SearchResultState  # noqa: E402
from payment_forensics.engine import EngineResult, HybridEngine, SearchExecutor, SearchRequest  # noqa: E402
from payment_forensics.regression import RegressionResult, run_cross_model_regression  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GOLDEN_CASES_PATH = ROOT / "tests" / "golden_cases.json"
DEFAULT_INSTRUCTIONS_PATH = ROOT / "skills" / "payment-forensics" / "CORE.md"

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


@dataclass(frozen=True)
class CanaryCaseResult:
    backend: str
    case_id: str
    passed: bool
    reasons: tuple[str, ...]
    status: str
    mode: str | None
    rounds: int
    duration_ms: int
    token_usage: Mapping[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


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
    from payment_forensics.adapters import ClaudeCodeProposalModel, LiteLLMModel, OpenAIResponsesModel

    backends: dict[str, Callable[[str], Any]] = {}
    if os.environ.get("OPENAI_API_KEY"):
        backends["openai"] = lambda instructions: OpenAIResponsesModel(instructions=instructions)
    if os.environ.get("ANTHROPIC_API_KEY"):
        backends["claude"] = lambda instructions: LiteLLMModel(instructions=instructions, model=os.environ.get("DUDLEY_CLAUDE_MODEL", "claude-opus-4-6"))
    if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
        backends["gemini"] = lambda instructions: LiteLLMModel(instructions=instructions, model=os.environ.get("DUDLEY_GEMINI_MODEL", "gemini/gemini-3-pro"))
    # Claude Code uses the signed-in local subscription, not an API key. Keep
    # it opt-in because a canary consumes that subscription, even though it is
    # isolated from live tools and uses only the synthetic fixtures below.
    if os.environ.get("DUDLEY_CANARY_CLAUDE_CODE") == "1":
        executable = shutil.which("claude")
        if executable:
            backends["claude_code"] = lambda instructions: ClaudeCodeProposalModel(
                instructions=instructions,
                executable=executable,
            )
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
        expected = dict(case.get("expected", {}))

        def assertion(result: EngineResult, case={**case, "required": list(required_tags)}) -> bool:
            return not evaluate_result(result, case)

        fixtures.append((case["id"], case_input, assertion))
    return fixtures


def evaluate_result(result: EngineResult, case: Mapping[str, Any]) -> tuple[str, ...]:
    """Return precise benchmark failures instead of a single opaque boolean."""
    reasons: list[str] = []
    expected = dict(case.get("expected", {}))
    expected_status = str(expected.get("status", "completed"))
    if result.status != expected_status:
        reasons.append(f"status: expected {expected_status}, got {result.status}")
    if expected_status == "completed" and not result.output:
        reasons.append("output: completed result has no output")
    if result.output:
        for tag in case.get("required", ()):
            checker = tag_checkers().get(str(tag))
            if checker and not checker(result.output, str(case.get("case_input", ""))):
                reasons.append(f"output rule failed: {tag}")
    if expected.get("mode") and result.mode != expected["mode"]:
        reasons.append(f"mode: expected {expected['mode']}, got {result.mode}")
    state = result.state
    if expected.get("terminal_state") and state.get("terminal_state") != expected["terminal_state"]:
        reasons.append(f"terminal_state: expected {expected['terminal_state']}, got {state.get('terminal_state')}")
    if expected.get("funds_location") and state.get("funds_location") != expected["funds_location"]:
        reasons.append(f"funds_location: expected {expected['funds_location']}, got {state.get('funds_location')}")
    evidence = state.get("evidence", ())
    minimum = int(expected.get("min_evidence", 0))
    if len(evidence) < minimum:
        reasons.append(f"evidence: expected at least {minimum}, got {len(evidence)}")
    for source in expected.get("checked_sources", ()):
        actual = state.get("coverage", {}).get(source)
        if actual != "CHECKED":
            reasons.append(f"coverage {source}: expected CHECKED, got {actual}")
    event_types = {item.get("event_type") for item in evidence}
    for event_type in expected.get("required_event_types", ()):
        if event_type not in event_types:
            reasons.append(f"evidence: missing event type {event_type}")
    for phrase in expected.get("output_contains", ()):
        if not result.output or str(phrase).casefold() not in result.output.casefold():
            reasons.append(f"output: missing required phrase {phrase!r}")
    return tuple(reasons)


def run_canary_detailed(
    cases: list[dict[str, Any]],
    backends: Mapping[str, Callable[[str], Any]],
    instructions: str,
) -> tuple[CanaryCaseResult, ...]:
    results: list[CanaryCaseResult] = []
    for backend_name, model_factory in backends.items():
        model = model_factory(instructions)
        for case in cases:
            started = time.perf_counter()
            try:
                executor = CannedSearchExecutor(case.get("canned_results", {}))
                engine_result = HybridEngine(model, executor).investigate(case["case_input"])
                reasons = evaluate_result(engine_result, case)
                results.append(CanaryCaseResult(
                    backend=backend_name,
                    case_id=case["id"],
                    passed=not reasons,
                    reasons=reasons,
                    status=engine_result.status,
                    mode=engine_result.mode,
                    rounds=engine_result.rounds,
                    duration_ms=round((time.perf_counter() - started) * 1000),
                    token_usage=engine_result.state.get("model_usage"),
                ))
            except Exception as exc:
                results.append(CanaryCaseResult(
                    backend=backend_name,
                    case_id=case["id"],
                    passed=False,
                    reasons=(f"execution error: {type(exc).__name__}: {exc}",),
                    status="error",
                    mode=None,
                    rounds=0,
                    duration_ms=round((time.perf_counter() - started) * 1000),
                ))
    return tuple(results)


def routing_verdict(results: tuple[CanaryCaseResult, ...], backend: str) -> dict[str, Any]:
    selected = [item for item in results if item.backend == backend]
    if not selected:
        return {"eligible": False, "pass_rate": 0.0, "reason": "backend has no evaluation results"}
    passed = sum(item.passed for item in selected)
    pass_rate = passed / len(selected)
    failed_ids = [item.case_id for item in selected if not item.passed]
    eligible = pass_rate == 1.0
    return {
        "eligible": eligible,
        "pass_rate": round(pass_rate, 4),
        "passed": passed,
        "total": len(selected),
        "failed_cases": failed_ids,
        "reason": "100% of evaluated cases passed" if eligible else "automatic routing remains disabled",
    }


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
    parser = argparse.ArgumentParser(description="Run Dudley's cross-model synthetic evaluation pack.")
    parser.add_argument("golden_cases", nargs="?", type=Path, default=DEFAULT_GOLDEN_CASES_PATH)
    parser.add_argument("--json", action="store_true", dest="json_output")
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    golden_cases_path = args.golden_cases
    cases = load_golden_cases(golden_cases_path)
    runnable, skipped = runnable_and_skipped_cases(cases)
    for message in skipped:
        print(f"SKIPPED: {message}")

    backends = build_backends()
    if not backends:
        print("No model provider API key configured. Nothing to run.")
        return 2
    if not runnable:
        print("No runnable golden cases (each needs case_input and canned_results). Nothing to run.")
        return 2

    instructions = DEFAULT_INSTRUCTIONS_PATH.read_text(encoding="utf-8")
    detailed = run_canary_detailed(runnable, backends, instructions)
    verdicts = {name: routing_verdict(detailed, name) for name in backends}
    if args.json_output:
        print(json.dumps({"cases": [item.as_dict() for item in detailed], "routing": verdicts}, indent=2, default=str))
    else:
        for backend_name in backends:
            selected = [item for item in detailed if item.backend == backend_name]
            passed = sum(item.passed for item in selected)
            status = "PASS" if passed == len(selected) else "FAIL"
            print(f"{backend_name}: {status} ({passed}/{len(selected)})")
            for item in selected:
                if not item.passed:
                    print(f"  - {item.case_id}: {'; '.join(item.reasons)}")
            verdict = verdicts[backend_name]
            route = "ELIGIBLE" if verdict["eligible"] else "DISABLED"
            print(f"  automatic routine routing: {route} ({verdict['pass_rate']:.0%})")
    return 0 if all(item.passed for item in detailed) else 1


if __name__ == "__main__":
    raise SystemExit(main())
