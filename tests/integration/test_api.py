from __future__ import annotations

import shutil
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from apps.api.main import create_app
from insightforge.config import Settings


class APIIntegrationTest(unittest.TestCase):
    def test_upload_approval_and_trace(self) -> None:
        root = Path(".runtime/tests/api")
        shutil.rmtree(root, ignore_errors=True)
        root.mkdir(parents=True, exist_ok=True)
        app = create_app(
            Settings(
                database_path=root / "insightforge.db",
                artifact_dir=root / "artifacts",
                dataset_dir=root / "datasets",
                benchmark_dir=Path("benchmark"),
            )
        )
        with TestClient(app) as client:
            upload = client.post(
                "/api/v1/datasets",
                files={
                    "file": (
                        "retail.csv",
                        Path("benchmark/datasets/retail_small.csv").read_bytes(),
                        "text/csv",
                    )
                },
            )
            self.assertEqual(upload.status_code, 201, upload.text)
            self.assertNotIn("storage_uri", upload.json())
            created = client.post(
                "/api/v1/analyses",
                json={
                    "dataset_id": upload.json()["id"],
                    "question": "Berapa total revenue?",
                    "mode": "approval",
                },
            )
            self.assertEqual(created.status_code, 201, created.text)
            self.assertEqual(created.json()["status"], "awaiting_approval")
            approved = client.post(f"/api/v1/analyses/{created.json()['id']}/approve")
            self.assertEqual(approved.status_code, 200, approved.text)
            self.assertEqual(approved.json()["status"], "completed")
            trace = client.get(f"/api/v1/analyses/{created.json()['id']}/trace")
            self.assertEqual(trace.status_code, 200)
            self.assertGreaterEqual(len(trace.json()["steps"]), 4)
            report = client.get(f"/api/v1/analyses/{created.json()['id']}/report")
            self.assertEqual(report.status_code, 200, report.text)
            self.assertIn("text/html", report.headers["content-type"])
            self.assertIn("attachment", report.headers["content-disposition"])
            self.assertIn("Evidence and SQL", report.text)
            self.assertIn("SELECT", report.text)

if __name__ == "__main__":
    unittest.main()

