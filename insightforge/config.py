from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    app_env: str = "development"
    database_path: Path = Path(".runtime/data/insightforge.db")
    artifact_dir: Path = Path(".runtime/artifacts")
    dataset_dir: Path = Path(".runtime/datasets")
    temp_dir: Path = Path(".runtime/tmp")
    max_upload_mb: int = 100
    sql_timeout_seconds: int = 30
    sql_memory_limit_mb: int = 512
    sql_max_rows: int = 500
    max_retries: int = 1
    benchmark_dir: Path = Path("benchmark")
    benchmark_report_dir: Path = Path(".runtime/benchmark/reports")
    llm_provider: str = "deterministic"
    llm_model: str = "gpt-5-mini"
    openai_api_key: str | None = None
    python_sandbox_image: str = "insightforge:latest"
    python_timeout_seconds: int = 30
    python_memory_limit_mb: int = 1024
    python_max_output_kb: int = 512
    mlflow_enabled: bool = False
    mlflow_tracking_uri: str = "sqlite:///./.runtime/data/mlflow.db"
    mlflow_experiment: str = "insightforge"
    auth_enabled: bool = False
    auth_bootstrap_username: str | None = None
    auth_bootstrap_password: str | None = None
    auth_token_ttl_hours: int = 24

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            app_env=os.getenv("APP_ENV", "development"),
            database_path=Path(os.getenv("DATABASE_URL", "./.runtime/data/insightforge.db")),
            artifact_dir=Path(os.getenv("ARTIFACT_DIR", "./.runtime/artifacts")),
            dataset_dir=Path(os.getenv("DATASET_DIR", "./.runtime/datasets")),
            temp_dir=Path(os.getenv("TEMP_DIR", "./.runtime/tmp")),
            max_upload_mb=int(os.getenv("MAX_UPLOAD_MB", "100")),
            sql_timeout_seconds=int(os.getenv("SQL_TIMEOUT_SECONDS", "30")),
            sql_memory_limit_mb=int(os.getenv("SQL_MEMORY_LIMIT_MB", "512")),
            sql_max_rows=int(os.getenv("SQL_MAX_ROWS", "500")),
            max_retries=int(os.getenv("MAX_RETRIES", "1")),
            benchmark_dir=Path(os.getenv("BENCHMARK_DIR", "./benchmark")),
            benchmark_report_dir=Path(
                os.getenv("BENCHMARK_REPORT_DIR", "./.runtime/benchmark/reports")
            ),
            llm_provider=os.getenv("LLM_PROVIDER", "deterministic"),
            llm_model=os.getenv("LLM_MODEL", "gpt-5-mini"),
            openai_api_key=os.getenv("OPENAI_API_KEY"),
            python_sandbox_image=os.getenv("PYTHON_SANDBOX_IMAGE", "insightforge:latest"),
            python_timeout_seconds=int(os.getenv("PYTHON_TIMEOUT_SECONDS", "30")),
            python_memory_limit_mb=int(os.getenv("PYTHON_MEMORY_LIMIT_MB", "1024")),
            python_max_output_kb=int(os.getenv("PYTHON_MAX_OUTPUT_KB", "512")),
            mlflow_enabled=_bool_env("MLFLOW_ENABLED", False),
            mlflow_tracking_uri=os.getenv(
                "MLFLOW_TRACKING_URI", "sqlite:///./.runtime/data/mlflow.db"
            ),
            mlflow_experiment=os.getenv("MLFLOW_EXPERIMENT", "insightforge"),
            auth_enabled=_bool_env("AUTH_ENABLED", False),
            auth_bootstrap_username=os.getenv("AUTH_BOOTSTRAP_USERNAME"),
            auth_bootstrap_password=os.getenv("AUTH_BOOTSTRAP_PASSWORD"),
            auth_token_ttl_hours=int(os.getenv("AUTH_TOKEN_TTL_HOURS", "24")),
        )

    def ensure_directories(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        self.dataset_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.benchmark_report_dir.mkdir(parents=True, exist_ok=True)
        if self.mlflow_tracking_uri.startswith("sqlite:///"):
            tracking_path = Path(self.mlflow_tracking_uri.removeprefix("sqlite:///"))
            tracking_path.parent.mkdir(parents=True, exist_ok=True)


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}
