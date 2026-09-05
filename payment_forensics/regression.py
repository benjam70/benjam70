"""Reusable cross-model regression runner for the shared fixture suite."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Mapping


@dataclass(frozen=True)
class RegressionResult:
    model_name: str
    passed: int
    failed: int
    failures: tuple[str, ...] = ()


def run_cross_model_regression(models: Mapping[str, Callable[[str], object]], fixtures: Iterable[tuple[str, str, Callable[[object], bool]]]) -> tuple[RegressionResult, ...]:
    results = []
    fixture_list = tuple(fixtures)
    for model_name, runner in models.items():
        failures = []
        for fixture_name, case_input, assertion in fixture_list:
            try:
                if not assertion(runner(case_input)):
                    failures.append(fixture_name)
            except Exception as exc:
                failures.append(f"{fixture_name}: {type(exc).__name__}")
        results.append(RegressionResult(model_name, len(fixture_list) - len(failures), len(failures), tuple(failures)))
    return tuple(results)
