from __future__ import annotations

import hashlib
import json
from typing import Any

import mlflow
from mlflow.tracking import MlflowClient

from insightforge.config import Settings


class MLflowTracker:
    def __init__(self, settings: Settings) -> None:
        self.enabled = settings.mlflow_enabled
        self.tracking_uri = settings.mlflow_tracking_uri
        self.experiment = settings.mlflow_experiment
        self.artifact_dir = settings.artifact_dir
        self.experiment_id: str | None = None
        if self.enabled:
            mlflow.set_tracking_uri(self.tracking_uri)
            if self.tracking_uri.startswith("sqlite:///"):
                artifact_root = (self.artifact_dir / "mlflow-runs").resolve()
                artifact_root.mkdir(parents=True, exist_ok=True)
                client = MlflowClient(tracking_uri=self.tracking_uri)
                experiment = client.get_experiment_by_name(self.experiment)
                self.experiment_id = (
                    experiment.experiment_id
                    if experiment is not None
                    else client.create_experiment(
                        self.experiment,
                        artifact_location=artifact_root.as_uri(),
                    )
                )
            else:
                self.experiment_id = mlflow.set_experiment(self.experiment).experiment_id

    def log_analysis(
        self,
        analysis_id: str,
        dataset_id: str,
        question: str,
        mode: str,
        result: dict[str, Any],
        coverage: float,
    ) -> str | None:
        if not self.enabled:
            return None
        question_hash = hashlib.sha256(question.encode("utf-8")).hexdigest()
        evidence = result.get("evidence", [])
        plan = result.get("plan", {})
        assert self.experiment_id is not None
        with mlflow.start_run(
            experiment_id=self.experiment_id,
            run_name=analysis_id,
            tags={"analysis_id": analysis_id},
        ) as run:
            mlflow.log_params(
                {
                    "dataset_id": dataset_id,
                    "question_hash": question_hash,
                    "mode": mode,
                    "query_count": len(plan.get("queries", [])),
                    "answer_type": plan.get("answer_type", "unknown"),
                }
            )
            mlflow.log_metrics(
                {
                    "evidence_coverage": float(coverage),
                    "evidence_count": float(len(evidence)),
                }
            )
            audit_path = self.artifact_dir / "mlflow" / analysis_id / "audit_summary.json"
            audit_path.parent.mkdir(parents=True, exist_ok=True)
            audit_path.write_text(
                json.dumps(
                    {
                        "analysis_id": analysis_id,
                        "evidence_keys": [item.get("key") for item in evidence],
                        "validation": result.get("validation", {}),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            mlflow.log_artifact(str(audit_path))
            return run.info.run_id
