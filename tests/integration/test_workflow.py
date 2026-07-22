from __future__ import annotations

import shutil
import unittest
from pathlib import Path

from apps.api.main import _services
from insightforge.config import Settings


class WorkflowIntegrationTest(unittest.TestCase):
    def test_csv_to_profile_answer_and_trace(self) -> None:
        root = Path(".runtime/tests/workflow")
        shutil.rmtree(root, ignore_errors=True)
        root.mkdir(parents=True, exist_ok=True)
        services = _services(
            Settings(
                database_path=root / "insightforge.db",
                artifact_dir=root / "artifacts",
                dataset_dir=root / "datasets",
                benchmark_dir=Path("benchmark"),
            )
        )
        dataset = services.datasets.ingest_path(Path("benchmark/datasets/retail_small.csv"))
        analysis = services.workflow.create(
            dataset["id"], "Mengapa revenue Bandung turun pada April?", "autonomous"
        )
        self.assertEqual(analysis["status"], "completed")
        self.assertIn("evidence:monthly_comparison", analysis["final_answer"])
        self.assertEqual(analysis["result"]["evidence"][1]["rows"][0]["segment"], "Home")
        trace = services.store.trace(analysis["id"])
        self.assertIsNotNone(trace)
        assert trace is not None
        self.assertGreaterEqual(len(trace["steps"]), 5)
        self.assertEqual(trace["evaluations"][0]["score"], 1.0)


if __name__ == "__main__":
    unittest.main()
