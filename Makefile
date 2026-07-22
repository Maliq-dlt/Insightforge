.PHONY: install run test lint typecheck check

install:
	uv sync --extra dev

run:
	uv run uvicorn apps.api.main:app --reload

test:
	uv run pytest

lint:
	uv run ruff check apps insightforge tests

typecheck:
	uv run mypy insightforge apps

check: lint typecheck test
