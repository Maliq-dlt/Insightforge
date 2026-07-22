from __future__ import annotations

import shutil
import unittest
from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient
from mlflow.tracking import MlflowClient

from apps.api.main import _services, create_app
from insightforge.config import Settings


class ExtendedFeatureIntegrationTest(unittest.TestCase):
    def test_rbac_and_statistics_api(self) -> None:
        root = Path(".runtime/tests/extended_api")
        shutil.rmtree(root, ignore_errors=True)
        settings = Settings(
            database_path=root / "insightforge.db",
            artifact_dir=root / "artifacts",
            dataset_dir=root / "datasets",
            benchmark_dir=Path("benchmark"),
            auth_enabled=True,
            auth_bootstrap_username="admin",
            auth_bootstrap_password="admin-password-123",
        )
        app = create_app(settings)
        with TestClient(app) as client:
            self.assertEqual(client.get("/api/v1/datasets").status_code, 401)
            admin_login = client.post(
                "/api/v1/auth/login",
                json={"username": "admin", "password": "admin-password-123"},
            )
            self.assertEqual(admin_login.status_code, 200, admin_login.text)
            admin_headers = {
                "Authorization": f"Bearer {admin_login.json()['access_token']}"
            }
            created_user = client.post(
                "/api/v1/admin/users",
                headers=admin_headers,
                json={
                    "username": "viewer",
                    "password": "viewer-password-123",
                    "role": "viewer",
                },
            )
            self.assertEqual(created_user.status_code, 200, created_user.text)
            viewer_login = client.post(
                "/api/v1/auth/login",
                json={"username": "viewer", "password": "viewer-password-123"},
            )
            viewer_headers = {
                "Authorization": f"Bearer {viewer_login.json()['access_token']}"
            }
            self.assertEqual(
                client.get("/api/v1/datasets", headers=viewer_headers).status_code,
                200,
            )
            denied_upload = client.post(
                "/api/v1/datasets",
                headers=viewer_headers,
                files={"file": ("groups.csv", b"group,outcome\nA,1\n", "text/csv")},
            )
            self.assertEqual(denied_upload.status_code, 403)

            csv_data = (
                b"group,outcome\nA,1\nA,2\nA,3\nA,4\n"
                b"B,10\nB,11\nB,12\nB,13\n"
            )
            upload = client.post(
                "/api/v1/datasets",
                headers=admin_headers,
                files={"file": ("groups.csv", csv_data, "text/csv")},
            )
            self.assertEqual(upload.status_code, 201, upload.text)
            statistics = client.post(
                f"/api/v1/statistics?dataset_id={upload.json()['id']}",
                headers=admin_headers,
                json={
                    "method": "compare_groups",
                    "outcome": "outcome",
                    "group": "group",
                },
            )
            self.assertEqual(statistics.status_code, 201, statistics.text)
            self.assertEqual(statistics.json()["status"], "completed")
            self.assertLess(
                statistics.json()["result"]["statistics"]["p_value"],
                0.05,
            )

    def test_parquet_langgraph_trace_and_mlflow_sqlite(self) -> None:
        root = Path(".runtime/tests/parquet_mlflow")
        shutil.rmtree(root, ignore_errors=True)
        root.mkdir(parents=True, exist_ok=True)
        parquet_path = root / "metrics.parquet"
        pd.DataFrame(
            {
                "segment": ["A", "A", "B", "B"],
                "revenue": [10.0, 20.0, 30.0, 40.0],
            }
        ).to_parquet(parquet_path, index=False)
        tracking_uri = f"sqlite:///{(root / 'mlflow.db').resolve().as_posix()}"
        services = _services(
            Settings(
                database_path=root / "insightforge.db",
                artifact_dir=root / "artifacts",
                dataset_dir=root / "datasets",
                benchmark_dir=Path("benchmark"),
                mlflow_enabled=True,
                mlflow_tracking_uri=tracking_uri,
                mlflow_experiment="insightforge-tests",
            )
        )
        dataset = services.datasets.ingest_path(parquet_path)
        self.assertEqual(dataset["profile"]["rows"], 4)
        analysis = services.workflow.create(
            dataset["id"],
            "Berapa total revenue?",
            "autonomous",
        )
        self.assertEqual(analysis["status"], "completed")
        self.assertEqual(
            analysis["result"]["evidence"][0]["rows"][0]["metric_value"],
            100.0,
        )
        agent_names = [
            step["agent_name"] for step in services.store.trace(analysis["id"])["steps"]
        ]
        self.assertEqual(
            agent_names,
            ["planner", "sql_agent", "critic", "report_agent"],
        )
        run_id = analysis["result"]["mlflow_run_id"]
        run = MlflowClient(tracking_uri=tracking_uri).get_run(run_id)
        self.assertEqual(run.data.tags["analysis_id"], analysis["id"])
        self.assertEqual(run.data.metrics["evidence_coverage"], 1.0)
        self.assertFalse(Path("mlruns").exists())


if __name__ == "__main__":
    unittest.main()
