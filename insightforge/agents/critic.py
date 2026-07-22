from __future__ import annotations

from typing import Any

from insightforge.agents.planner import AnalysisPlan
from insightforge.sandbox.executor import SQLSafetyError, validate_read_only_sql


class Critic:
    def validate(
        self,
        plan: AnalysisPlan,
        schema: list[dict[str, Any]],
        results: list[dict[str, Any]],
    ) -> dict[str, Any]:
        available = {item["name"] for item in schema}
        issues: list[dict[str, str]] = []
        missing_columns = [column for column in plan.required_columns if column not in available]
        if missing_columns:
            issues.append({"type": "missing_column", "message": ", ".join(missing_columns)})
        if not results:
            issues.append({"type": "empty_execution", "message": "Tidak ada hasil eksekusi."})
        for query in plan.queries:
            try:
                validate_read_only_sql(query.sql)
            except SQLSafetyError as error:
                issues.append({"type": "unsafe_sql", "message": str(error)})
        for result in results:
            if result.get("error"):
                issues.append({"type": "execution_error", "message": str(result["error"])})
        return {
            "status": "revision_required" if issues else "passed",
            "issues": issues,
            "checks": {
                "required_columns_exist": not missing_columns,
                "queries_read_only": not any(issue["type"] == "unsafe_sql" for issue in issues),
                "results_reproducible": not any(issue["type"] == "execution_error" for issue in issues),
            },
        }
