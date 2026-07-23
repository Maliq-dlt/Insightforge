.PHONY: install run test benchmark coverage lint typecheck check

install:
	uv sync --extra dev

run:
	uv run uvicorn apps.api.main:app --reload

test:
	uv run pytest

benchmark:
	uv run pytest tests/integration/test_benchmark.py -q

coverage:
	uv run coverage run -m pytest
	uv run coverage report
	uv run coverage html
	uv run coverage xml

lint:
	uv run ruff check apps insightforge tests

typecheck:
	uv run mypy insightforge apps

check: lint typecheck test
