# Development

## Install

```bash
uv sync --extra dev
```

Use `.runtime/cache/uv/` for dependency cache and `.runtime/` for generated runtime files, including `temp` uploads. Network-restricted environments can run CSV fallback checks only when DuckDB is unavailable; Parquet, SciPy, MLflow, and LangGraph checks require installed dependencies.

## Verify

```bash
uv run pytest
uv run ruff check apps insightforge tests
uv run mypy insightforge apps
uv run coverage run -m pytest
uv run coverage report
```

The test suite stores generated databases and datasets under `.runtime/tests/`, which is ignored by Git. Docker sandbox execution additionally requires Docker CLI and daemon access.
