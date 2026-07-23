# Architecture

## Runtime path

1. `DatasetService` streams and validates upload, computes SHA-256, stores source file, and calls `DatasetProfiler`.
2. `PlanBuilder` maps supported natural-language patterns to a typed `AnalysisPlan`; `OpenAIPlanBuilder` is optional and validates structured output before use.
3. `LangGraphOrchestrator` records planner, SQL, critic, and report nodes as auditable events.
4. `SQLExecutor` materializes dataset into an in-memory DuckDB table, validates read-only SQL, runs `EXPLAIN`, caps output rows, and returns JSON-safe rows.
5. `StatisticsService` runs validated statistical methods through pandas and SciPy, then persists assumptions, p-value, effect size, and limitations.
6. `DockerPythonSandbox` validates AST policy and runs approved code in a read-only, no-network, resource-limited container.
7. `ReportAgent` writes answers with evidence keys; `VisualizationAgent` writes JSON chart artifacts.
8. `TraceStore` persists every stage in SQLite. `MLflowTracker` optionally records parameters, metrics, and an audit artifact.
9. `AuthService` optionally enforces viewer, analyst, and admin permissions at the API boundary.

## State model

Analysis status values:

- `awaiting_approval`: plan exists, no execution yet.
- `planned`: autonomous or benchmark analysis created.
- `running`: SQL, statistics, or Python execution is in progress.
- `completed`: report, evidence, and trace persisted.
- `failed`: execution or validation error persisted.

## Deliberate simplifications

- Planner intents remain bounded and deterministic by default; the OpenAI adapter is opt-in.
- SQLite remains the default trace store for a portable portfolio deployment.
- Python execution is isolated with Docker, but Compose intentionally does not expose the host Docker socket to the API.
- Chart artifacts include JSON data and rendered SVG output; standalone HTML report export is available, while PDF export remains future work.
