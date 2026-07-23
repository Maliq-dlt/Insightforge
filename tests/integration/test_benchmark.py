from __future__ import annotations

import shutil
import unittest
from pathlib import Path

from apps.api.main import _services
from insightforge.config import Settings


class BenchmarkIntegrationTest(unittest.TestCase):
    def test_portfolio_benchmark_has_100_passing_cases_and_auditable_metrics(self) -> None:
        root = Path(".runtime/tests/benchmark")
        shutil.rmtree(root, ignore_errors=True)
        services = _services(
            Settings(
                database_path=root / "insightforge.db",
                artifact_dir=root / "artifacts",
                dataset_dir=root / "datasets",
                temp_dir=root / "tmp",
                benchmark_dir=Path("benchmark"),
                benchmark_report_dir=root / "reports",
            )
        )

        report = services.benchmarks.run()

        self.assertEqual(report["total"], 100)
        self.assertEqual(report["passed"], 100)
        self.assertEqual(report["failed"], 0)
        self.assertEqual(report["metrics"]["execution_success"]["rate"], 1.0)
        self.assertEqual(report["metrics"]["evidence_coverage"]["score"], 1.0)
        self.assertEqual(report["metrics"]["read_only_sql_validity"]["rate"], 1.0)
        self.assertEqual(report["metrics"]["reproducibility"]["rate"], 1.0)
        self.assertEqual(set(report["categories"]), {
            "adversarial_injection",
            "aggregation",
            "ambiguous_question",
            "data_quality",
            "segmentation",
            "statistical_reasoning",
            "time_series_comparison",
        })
        self.assertEqual(services.benchmarks.latest()["total"], 100)


if __name__ == "__main__":
    unittest.main()