from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from insightforge.evaluators.basic import numerical_score
from insightforge.graph.workflow import AnalysisWorkflow
from insightforge.ingestion.service import DatasetService


class BenchmarkRunner:
    def __init__(
        self,
        root: Path,
        datasets: DatasetService,
        workflow: AnalysisWorkflow,
        report_dir: Path | None = None,
    ) -> None:
        self.root = root
        self.datasets = datasets
        self.workflow = workflow
        self.report_dir = report_dir or (root / "reports")

    def run(self) -> dict[str, Any]:
        records: list[dict[str, Any]] = []
        for question_path in sorted((self.root / "questions").glob("*.json")):
            loaded = json.loads(question_path.read_text(encoding="utf-8-sig"))
            if isinstance(loaded, list):
                records.extend(cast(list[dict[str, Any]], loaded))
            elif isinstance(loaded, dict):
                records.append(loaded)
            else:
                raise ValueError(f"Format benchmark tidak valid: {question_path}")
        results: list[dict[str, Any]] = []
        for record in records:
            dataset = self.datasets.ingest_path(
                self.root / "datasets" / record["dataset"], record["dataset"]
            )
            analysis = self.workflow.create(dataset["id"], record["question"], "benchmark")
            evidence = (analysis.get("result") or {}).get("evidence", [])
            rows = evidence[0].get("rows", []) if evidence else []
            actual = rows[0].get(record.get("field", "metric_value")) if rows else None
            expected = record["expected"]["value"]
            score = numerical_score(actual, expected, record["expected"].get("tolerance", 1e-6))
            results.append(
                {
                    "id": record["id"],
                    "question": record["question"],
                    "actual": actual,
                    "expected": expected,
                    "score": score,
                    "status": "passed" if score == 1.0 else "failed",
                    "analysis_id": analysis["id"],
                }
            )
        score = sum(item["score"] for item in results) / len(results) if results else 0.0
        report = {"total": len(results), "score": score, "results": results}
        output = self.report_dir / "latest.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        return report

