from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from time import perf_counter
from typing import Any, cast

from insightforge.agents.statistics_agent import StatisticsService
from insightforge.evaluators.basic import numerical_score
from insightforge.graph.workflow import AnalysisWorkflow
from insightforge.ingestion.service import DatasetService
from insightforge.sandbox.executor import validate_read_only_sql


class BenchmarkRunner:
    def __init__(
        self,
        root: Path,
        datasets: DatasetService,
        workflow: AnalysisWorkflow,
        report_dir: Path | None = None,
        statistics: StatisticsService | None = None,
    ) -> None:
        self.root = root
        self.datasets = datasets
        self.workflow = workflow
        self.report_dir = report_dir or (root / "reports")
        self.statistics = statistics

    def run(self) -> dict[str, Any]:
        records = self._records()
        results = [self._run_record(record) for record in records]
        report = self._report(results)
        output = self.report_dir / "latest.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        return report

    def latest(self) -> dict[str, Any] | None:
        output = self.report_dir / "latest.json"
        if not output.exists():
            return None
        loaded = json.loads(output.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError("Format laporan benchmark tidak valid.")
        return cast(dict[str, Any], loaded)

    def _records(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for question_path in sorted((self.root / "questions").glob("*.json")):
            loaded = json.loads(question_path.read_text(encoding="utf-8-sig"))
            if isinstance(loaded, list):
                records.extend(cast(list[dict[str, Any]], loaded))
            elif isinstance(loaded, dict):
                records.append(loaded)
            else:
                raise ValueError(f"Format benchmark tidak valid: {question_path}")
        ids = [str(record.get("id", "")) for record in records]
        if any(not record_id for record_id in ids):
            raise ValueError("Setiap benchmark record wajib memiliki id.")
        duplicates = sorted({record_id for record_id in ids if ids.count(record_id) > 1})
        if duplicates:
            raise ValueError("Benchmark id duplikat: " + ", ".join(duplicates))
        return records

    def _run_record(self, record: dict[str, Any]) -> dict[str, Any]:
        started = perf_counter()
        base = {
            "id": record["id"],
            "kind": record.get("kind", "analysis"),
            "category": record.get("category", "uncategorized"),
            "difficulty": record.get("difficulty", "unknown"),
            "question": record.get("question"),
        }
        try:
            dataset = self.datasets.ingest_path(
                self.root / "datasets" / record["dataset"], record["dataset"]
            )
            if record.get("kind", "analysis") == "statistics":
                result = self._run_statistics(record, dataset)
            else:
                result = self._run_analysis(record, dataset)
        except Exception as error:
            result = {
                "actual": None,
                "expected": record.get("expected"),
                "score": 0.0,
                "execution_success": False,
                "evidence_coverage": None,
                "read_only_sql_valid": None,
                "reproducible": None,
                "analysis_id": None,
                "error": str(error),
                "numeric_case": self._is_numeric_expected(record.get("expected", {})),
            }
        result.update(base)
        result["latency_ms"] = int((perf_counter() - started) * 1000)
        checks = [bool(result["execution_success"]), result["score"] == 1.0]
        checks.extend(
            bool(value)
            for value in (result.get("read_only_sql_valid"), result.get("reproducible"))
            if value is not None
        )
        result["status"] = "passed" if all(checks) else "failed"
        return result

    def _run_analysis(self, record: dict[str, Any], dataset: dict[str, Any]) -> dict[str, Any]:
        analysis = self.workflow.create(dataset["id"], record["question"], "benchmark")
        evidence = (analysis.get("result") or {}).get("evidence", [])
        actual = self._select_evidence(evidence, record.get("selector", {}))
        score = self._score(actual, record["expected"])
        trace = self.workflow.store.trace(analysis["id"]) or {}
        evaluations = trace.get("evaluations", [])
        coverage = next(
            (item["score"] for item in evaluations if item["evaluator"] == "evidence_coverage"),
            None,
        )
        return {
            "actual": actual,
            "expected": record["expected"],
            "score": score,
            "execution_success": analysis.get("status") == "completed",
            "evidence_coverage": coverage,
            "read_only_sql_valid": self._sql_valid(evidence),
            "reproducible": self._reproducible(dataset, evidence),
            "analysis_id": analysis["id"],
            "error": analysis.get("error"),
            "numeric_case": self._is_numeric_expected(record["expected"]),
        }

    def _run_statistics(self, record: dict[str, Any], dataset: dict[str, Any]) -> dict[str, Any]:
        if self.statistics is None:
            raise RuntimeError("StatisticsService belum dikonfigurasi untuk benchmark.")
        analysis = self.statistics.run(dataset["id"], record["request"])
        statistics = (analysis.get("result") or {}).get("statistics", {})
        actual = self._select_path(statistics, record.get("selector", {}).get("path", ""))
        return {
            "actual": actual,
            "expected": record["expected"],
            "score": self._score(actual, record["expected"]),
            "execution_success": analysis.get("status") == "completed",
            "evidence_coverage": None,
            "read_only_sql_valid": None,
            "reproducible": None,
            "analysis_id": analysis["id"],
            "error": analysis.get("error"),
            "numeric_case": self._is_numeric_expected(record["expected"]),
        }

    @staticmethod
    def _select_evidence(evidence: list[dict[str, Any]], selector: dict[str, Any]) -> Any:
        evidence_key = selector.get("evidence_key")
        item = next(
            (entry for entry in evidence if not evidence_key or entry.get("key") == evidence_key),
            None,
        )
        if item is None:
            return None
        rows = item.get("rows", [])
        row_index = int(selector.get("row", 0))
        if row_index >= len(rows):
            return None
        return rows[row_index].get(selector.get("field", "metric_value"))

    @staticmethod
    def _select_path(value: dict[str, Any], path: str) -> Any:
        selected: Any = value
        for part in path.split(".") if path else []:
            if not isinstance(selected, dict):
                return None
            selected = selected.get(part)
        return selected

    @staticmethod
    def _score(actual: Any, expected: dict[str, Any]) -> float:
        if "one_of" in expected:
            return float(actual in expected["one_of"])
        if "lt" in expected:
            return float(
                isinstance(actual, int | float)
                and not isinstance(actual, bool)
                and actual < expected["lt"]
            )
        if "gt" in expected:
            return float(
                isinstance(actual, int | float)
                and not isinstance(actual, bool)
                and actual > expected["gt"]
            )
        target = expected.get("value")
        if (
            isinstance(actual, int | float)
            and not isinstance(actual, bool)
            and isinstance(target, int | float)
            and not isinstance(target, bool)
        ):
            return numerical_score(actual, target, expected.get("tolerance", 1e-6))
        return float(actual == target)

    @staticmethod
    def _is_numeric_expected(expected: dict[str, Any]) -> bool:
        target = expected.get("value")
        return (
            isinstance(target, int | float)
            and not isinstance(target, bool)
            or "lt" in expected
            or "gt" in expected
        )

    @staticmethod
    def _sql_valid(evidence: list[dict[str, Any]]) -> bool:
        if not evidence:
            return False
        try:
            for item in evidence:
                validate_read_only_sql(item["sql"])
        except (KeyError, ValueError):
            return False
        return True

    def _reproducible(self, dataset: dict[str, Any], evidence: list[dict[str, Any]]) -> bool:
        if not evidence:
            return False
        dataset_path = Path(dataset["storage_uri"])
        return all(
            self.workflow.executor.execute(dataset_path, item["sql"])["rows"] == item["rows"]
            for item in evidence
        )

    @staticmethod
    def _report(results: list[dict[str, Any]]) -> dict[str, Any]:
        total = len(results)
        passed = sum(item["status"] == "passed" for item in results)
        execution = [bool(item["execution_success"]) for item in results]
        numerical = [item["score"] for item in results if item["numeric_case"]]
        coverage = [
            item["evidence_coverage"]
            for item in results
            if item["evidence_coverage"] is not None
        ]
        sql_validity = [
            item["read_only_sql_valid"]
            for item in results
            if item["read_only_sql_valid"] is not None
        ]
        reproducibility = [
            item["reproducible"] for item in results if item["reproducible"] is not None
        ]
        categories: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in results:
            categories[item["category"]].append(item)

        def rate(values: list[bool]) -> float:
            return sum(values) / len(values) if values else 0.0

        category_summary = {
            name: {
                "total": len(items),
                "passed": sum(item["status"] == "passed" for item in items),
                "score": sum(item["score"] for item in items) / len(items),
            }
            for name, items in sorted(categories.items())
        }
        public_results = [
            {key: value for key, value in item.items() if key != "numeric_case"}
            for item in results
        ]
        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "total": total,
            "passed": passed,
            "failed": total - passed,
            "score": sum(item["score"] for item in results) / total if total else 0.0,
            "metrics": {
                "execution_success": {
                    "passed": sum(execution),
                    "total": len(execution),
                    "rate": rate(execution),
                },
                "numerical_accuracy": {
                    "passed": sum(score == 1.0 for score in numerical),
                    "total": len(numerical),
                    "rate": sum(numerical) / len(numerical) if numerical else 0.0,
                },
                "evidence_coverage": {
                    "total": len(coverage),
                    "score": sum(coverage) / len(coverage) if coverage else 0.0,
                },
                "read_only_sql_validity": {
                    "passed": sum(bool(value) for value in sql_validity),
                    "total": len(sql_validity),
                    "rate": rate([bool(value) for value in sql_validity]),
                },
                "reproducibility": {
                    "passed": sum(bool(value) for value in reproducibility),
                    "total": len(reproducibility),
                    "rate": rate([bool(value) for value in reproducibility]),
                },
                "median_latency_ms": median(item["latency_ms"] for item in results)
                if results
                else 0,
            },
            "categories": category_summary,
            "results": public_results,
        }