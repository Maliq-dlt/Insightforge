from __future__ import annotations

from math import isclose
from typing import Any


def numerical_score(actual: Any, expected: Any, tolerance: float = 1e-6) -> float:
    try:
        return 1.0 if isclose(float(actual), float(expected), rel_tol=tolerance, abs_tol=tolerance) else 0.0
    except (TypeError, ValueError):
        return 1.0 if actual == expected else 0.0


def evidence_coverage(report: str, evidence_keys: list[str]) -> float:
    if not evidence_keys:
        return 0.0
    covered = sum(f"evidence:{key}" in report for key in evidence_keys)
    return covered / len(evidence_keys)
