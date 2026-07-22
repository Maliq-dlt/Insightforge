# Deployment

## Docker Compose

Copy `.env.example` to `.env`, then run:

```bash
docker compose up --build
```

The API image is tagged `insightforge:latest`, matching `PYTHON_SANDBOX_IMAGE`. Persistent state lives in named volume `insightforge-data`, mounted at `/app/.runtime`.

## Environment

- `DATABASE_URL`: SQLite trace database path.
- `DATASET_DIR`: uploaded source directory.
- `ARTIFACT_DIR`: chart, MLflow audit, MLflow run artifacts, and Python-run artifact directory.
- `MAX_UPLOAD_MB`: upload limit.
- `SQL_MEMORY_LIMIT_MB`: DuckDB memory limit.
- `SQL_MAX_ROWS`: response row cap.
- `SQL_TIMEOUT_SECONDS`: SQL execution timeout.
- `LLM_PROVIDER` and `OPENAI_API_KEY`: optional structured planner configuration.
- `MLFLOW_ENABLED` and `MLFLOW_TRACKING_URI`: optional experiment tracking; local default is SQLite.
- `AUTH_ENABLED`, `AUTH_BOOTSTRAP_USERNAME`, and `AUTH_BOOTSTRAP_PASSWORD`: optional RBAC bootstrap.
- `PYTHON_SANDBOX_IMAGE`, `PYTHON_MEMORY_LIMIT_MB`, and `PYTHON_TIMEOUT_SECONDS`: Docker sandbox limits.

## Python sandbox deployment

Host execution requires Docker CLI and a reachable Docker daemon. The Compose file does not mount `/var/run/docker.sock` or a Windows Docker socket into the API container. Keep Python execution on a host API with Docker access, or deploy a separate sandbox runner before enabling it in Compose.

## Health check

```bash
curl http://localhost:8000/health
```
