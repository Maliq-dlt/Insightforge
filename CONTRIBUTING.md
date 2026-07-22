# Contributing

## Setup

```bash
uv sync --extra dev
```

## Before submitting

```bash
uv run ruff check .
uv run mypy insightforge apps
uv run pytest
```

Keep changes focused. New execution features require security tests. New planner behavior requires at least one deterministic benchmark record.
