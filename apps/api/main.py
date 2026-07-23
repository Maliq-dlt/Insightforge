from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from insightforge.agents.critic import Critic
from insightforge.agents.report_agent import ReportAgent
from insightforge.agents.statistics_agent import StatisticsAgent, StatisticsService
from insightforge.agents.visualization_agent import VisualizationAgent
from insightforge.benchmark import BenchmarkRunner
from insightforge.config import Settings
from insightforge.graph.workflow import AnalysisWorkflow
from insightforge.ingestion.service import DatasetService
from insightforge.ingestion.validators import DatasetValidationError, safe_filename
from insightforge.models.llm import build_planner
from insightforge.observability.mlflow_tracker import MLflowTracker
from insightforge.profiling.profiler import DatasetProfiler
from insightforge.reporting import export_html_report
from insightforge.sandbox.executor import SQLExecutor
from insightforge.sandbox.python_executor import DockerPythonSandbox, PythonExecutionService
from insightforge.security.auth import (
    AuthContext,
    AuthenticationError,
    AuthorizationError,
    AuthService,
)
from insightforge.storage.database import TraceStore


class AnalysisCreateRequest(BaseModel):
    dataset_id: str
    question: str = Field(min_length=3, max_length=2000)
    mode: Literal["autonomous", "approval", "benchmark"] = "approval"


class LoginRequest(BaseModel):
    username: str
    password: str


class UserCreateRequest(BaseModel):
    username: str = Field(min_length=3, max_length=100)
    password: str = Field(min_length=12, max_length=256)
    role: Literal["viewer", "analyst", "admin"]


class StatisticsRequest(BaseModel):
    method: Literal["auto", "compare_groups", "correlation", "chi_square"] = "auto"
    outcome: str | None = None
    group: str | None = None
    x: str | None = None
    y: str | None = None
    alpha: float = Field(default=0.05, gt=0, lt=1)


class PythonExecutionRequest(BaseModel):
    code: str = Field(min_length=1, max_length=50_000)


@dataclass
class Services:
    settings: Settings
    store: TraceStore
    datasets: DatasetService
    workflow: AnalysisWorkflow
    benchmarks: BenchmarkRunner
    auth: AuthService
    statistics: StatisticsService
    python: PythonExecutionService


def _services(settings: Settings) -> Services:
    settings.ensure_directories()
    store = TraceStore(settings.database_path)
    store.initialize()
    profiler = DatasetProfiler()
    datasets = DatasetService(settings, store, profiler)
    tracker = MLflowTracker(settings)
    workflow = AnalysisWorkflow(
        settings=settings,
        store=store,
        planner=build_planner(settings),
        executor=SQLExecutor(settings),
        critic=Critic(),
        reporter=ReportAgent(),
        visualizer=VisualizationAgent(),
        tracker=tracker,
    )
    auth = AuthService(settings, store)
    statistics = StatisticsService(store, StatisticsAgent())
    python = PythonExecutionService(store, DockerPythonSandbox(settings))
    return Services(
        settings=settings,
        store=store,
        datasets=datasets,
        workflow=workflow,
        benchmarks=BenchmarkRunner(
            settings.benchmark_dir,
            datasets,
            workflow,
            settings.benchmark_report_dir,
            statistics,
        ),
        auth=auth,
        statistics=statistics,
        python=python,
    )


def _public(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _public(item) for key, item in value.items() if key != "storage_uri"}
    if isinstance(value, list):
        return [_public(item) for item in value]
    return value


def _bearer(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    return token if scheme.lower() == "bearer" and token else None


def _context(request: Request) -> AuthContext:
    services: Services = request.app.state.services
    try:
        return services.auth.resolve(_bearer(request))
    except AuthenticationError as error:
        raise HTTPException(
            status_code=401,
            detail=str(error),
            headers={"WWW-Authenticate": "Bearer"},
        ) from error


def _authorize(request: Request, permission: str) -> AuthContext:
    context = _context(request)
    try:
        request.app.state.services.auth.require(context, permission)
    except AuthorizationError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    return context


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.services = _services(Settings.from_env())
    yield


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(
        title="InsightForge",
        version="0.2.0",
        description="Auditable, evidence-backed data analysis MVP.",
        lifespan=lifespan if settings is None else None,
    )
    if settings is not None:
        app.state.services = _services(settings)

    def get_services(request: Request) -> Services:
        return request.app.state.services

    @app.get("/", include_in_schema=False)
    async def dashboard() -> FileResponse:
        return FileResponse(Path(__file__).parent / "static" / "index.html")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "insightforge"}

    @app.post("/api/v1/auth/login")
    async def login(payload: LoginRequest, request: Request) -> dict[str, Any]:
        try:
            return get_services(request).auth.login(payload.username, payload.password)
        except AuthenticationError as error:
            raise HTTPException(status_code=401, detail=str(error)) from error

    @app.get("/api/v1/auth/me")
    async def me(request: Request) -> dict[str, Any]:
        context = _context(request)
        return {"user_id": context.user_id, "username": context.username, "role": context.role}

    @app.post("/api/v1/auth/logout")
    async def logout(request: Request) -> dict[str, str]:
        _context(request)
        token = _bearer(request)
        if token:
            get_services(request).auth.revoke(token)
        return {"status": "logged_out"}

    @app.post("/api/v1/admin/users")
    async def create_user(payload: UserCreateRequest, request: Request) -> dict[str, Any]:
        _authorize(request, "admin")
        try:
            return get_services(request).auth.create_user(
                payload.username, payload.password, payload.role
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.get("/api/v1/admin/users")
    async def list_users(request: Request) -> list[dict[str, Any]]:
        _authorize(request, "admin")
        return get_services(request).store.list_users()

    @app.post("/api/v1/datasets", status_code=201)
    async def upload_dataset(request: Request, file: UploadFile = File(...)) -> dict[str, Any]:
        _authorize(request, "analyze")
        services = get_services(request)
        try:
            name = safe_filename(file.filename or "")
        except DatasetValidationError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        temporary = services.settings.temp_dir / f"._upload_{uuid.uuid4().hex}{Path(name).suffix.lower()}"
        size = 0
        try:
            with temporary.open("wb") as output:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > services.settings.max_upload_mb * 1024 * 1024:
                        raise HTTPException(status_code=413, detail="Ukuran file terlalu besar.")
                    output.write(chunk)
            return _public(services.datasets.ingest_path(temporary, name))
        except DatasetValidationError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except HTTPException:
            raise
        except Exception as error:
            raise HTTPException(status_code=422, detail=f"Dataset gagal diproses: {error}") from error
        finally:
            temporary.unlink(missing_ok=True)
            await file.close()

    @app.get("/api/v1/datasets")
    async def list_datasets(request: Request) -> list[dict[str, Any]]:
        _authorize(request, "read")
        return _public(get_services(request).store.list_datasets())

    @app.get("/api/v1/datasets/{dataset_id}")
    async def get_dataset(dataset_id: str, request: Request) -> dict[str, Any]:
        _authorize(request, "read")
        dataset = get_services(request).store.get_dataset(dataset_id)
        if dataset is None:
            raise HTTPException(status_code=404, detail="Dataset tidak ditemukan.")
        return _public(dataset)

    @app.post("/api/v1/analyses", status_code=201)
    async def create_analysis(payload: AnalysisCreateRequest, request: Request) -> dict[str, Any]:
        _authorize(request, "analyze")
        try:
            analysis = get_services(request).workflow.create(
                payload.dataset_id, payload.question, payload.mode
            )
            return _public(analysis)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Dataset tidak ditemukan.") from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.get("/api/v1/analyses/{analysis_id}")
    async def get_analysis(analysis_id: str, request: Request) -> dict[str, Any]:
        _authorize(request, "read")
        analysis = get_services(request).store.get_analysis(analysis_id)
        if analysis is None:
            raise HTTPException(status_code=404, detail="Analysis tidak ditemukan.")
        return _public(analysis)

    @app.post("/api/v1/analyses/{analysis_id}/approve")
    async def approve_analysis(analysis_id: str, request: Request) -> dict[str, Any]:
        _authorize(request, "analyze")
        try:
            return _public(get_services(request).workflow.approve(analysis_id))
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Analysis tidak ditemukan.") from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.get("/api/v1/analyses/{analysis_id}/trace")
    async def read_trace(analysis_id: str, request: Request) -> dict[str, Any]:
        _authorize(request, "read")
        trace = get_services(request).store.trace(analysis_id)
        if trace is None:
            raise HTTPException(status_code=404, detail="Analysis tidak ditemukan.")
        return _public(trace)

    @app.get("/api/v1/analyses/{analysis_id}/report")
    async def download_report(analysis_id: str, request: Request) -> FileResponse:
        _authorize(request, "read")
        services = get_services(request)
        trace = services.store.trace(analysis_id)
        if trace is None:
            raise HTTPException(status_code=404, detail="Analysis tidak ditemukan.")
        output = services.settings.artifact_dir / "reports" / f"{analysis_id}.html"
        export_html_report(trace, output)
        return FileResponse(
            output,
            media_type="text/html; charset=utf-8",
            filename=f"insightforge-{analysis_id}.html",
        )
    @app.post("/api/v1/analyses/{analysis_id}/python")
    async def execute_python(
        analysis_id: str, payload: PythonExecutionRequest, request: Request
    ) -> dict[str, Any]:
        _authorize(request, "execute_python")
        analysis = get_services(request).store.get_analysis(analysis_id)
        if analysis is None:
            raise HTTPException(status_code=404, detail="Analysis tidak ditemukan.")
        try:
            return _public(get_services(request).python.run(analysis["dataset_id"], payload.code))
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Dataset tidak ditemukan.") from error
        except Exception as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.post("/api/v1/statistics", status_code=201)
    async def run_statistics(
        dataset_id: str, payload: StatisticsRequest, request: Request
    ) -> dict[str, Any]:
        _authorize(request, "analyze")
        try:
            return _public(
                get_services(request).statistics.run(dataset_id, payload.model_dump(exclude_none=True))
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Dataset tidak ditemukan.") from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.post("/api/v1/benchmarks/run")
    async def run_benchmark(request: Request) -> dict[str, Any]:
        _authorize(request, "admin")
        try:
            return _public(get_services(request).benchmarks.run())
        except Exception as error:
            raise HTTPException(status_code=422, detail=f"Benchmark gagal: {error}") from error

    @app.get("/api/v1/benchmarks/latest")
    async def latest_benchmark(request: Request) -> dict[str, Any]:
        _authorize(request, "read")
        report = get_services(request).benchmarks.latest()
        if report is None:
            raise HTTPException(status_code=404, detail="Laporan benchmark belum tersedia.")
        return _public(report)

    return app


app = create_app()
