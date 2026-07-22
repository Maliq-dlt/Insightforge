from __future__ import annotations

from pathlib import Path
from typing import Any

from insightforge.agents.critic import Critic
from insightforge.agents.planner import AnalysisPlan, QueryPlan
from insightforge.agents.report_agent import ReportAgent
from insightforge.agents.visualization_agent import VisualizationAgent
from insightforge.config import Settings
from insightforge.evaluators.basic import evidence_coverage
from insightforge.graph.langgraph_workflow import LangGraphOrchestrator
from insightforge.sandbox.executor import SQLExecutor
from insightforge.storage.database import TraceStore, utc_now


class AnalysisWorkflow:
    def __init__(
        self,
        settings: Settings,
        store: TraceStore,
        planner: Any,
        executor: SQLExecutor,
        critic: Critic,
        reporter: ReportAgent,
        visualizer: VisualizationAgent,
        tracker: Any | None = None,
    ) -> None:
        self.settings = settings
        self.store = store
        self.planner = planner
        self.executor = executor
        self.critic = critic
        self.reporter = reporter
        self.visualizer = visualizer
        self.tracker = tracker
        self.graph = LangGraphOrchestrator(planner, executor, critic, reporter, visualizer)

    def create(self, dataset_id: str, question: str, mode: str = "approval") -> dict[str, Any]:
        if mode not in {"autonomous", "approval", "benchmark"}:
            raise ValueError("Mode harus autonomous, approval, atau benchmark.")
        dataset = self.store.get_dataset(dataset_id)
        if dataset is None:
            raise KeyError(dataset_id)
        planned = self.graph.plan(question, dataset["schema"], dataset["profile"])
        plan = planned["plan"]
        status = "awaiting_approval" if mode == "approval" else "planned"
        analysis = self.store.create_analysis(dataset_id, question, mode, status, plan.to_dict())
        self._persist_events(analysis["id"], planned.get("events", []))
        if mode == "approval":
            return self.store.get_analysis(analysis["id"]) or analysis
        return self._execute(analysis["id"], dataset, question, plan)

    def approve(self, analysis_id: str) -> dict[str, Any]:
        analysis = self.store.get_analysis(analysis_id)
        if analysis is None:
            raise KeyError(analysis_id)
        if analysis["status"] != "awaiting_approval":
            raise ValueError("Analysis tidak menunggu approval.")
        dataset = self.store.get_dataset(analysis["dataset_id"])
        if dataset is None:
            raise KeyError(analysis["dataset_id"])
        plan = self._plan_from_dict(analysis["plan"])
        return self._execute(analysis_id, dataset, analysis["question"], plan)

    def _execute(
        self,
        analysis_id: str,
        dataset: dict[str, Any],
        question: str,
        plan: AnalysisPlan,
    ) -> dict[str, Any]:
        self.store.update_analysis(analysis_id, status="running", error=None)
        state = self.graph.execute(
            question,
            dataset["schema"],
            self._dataset_path(dataset["storage_uri"]),
            plan,
        )
        self._persist_events(analysis_id, state.get("events", []))
        if state.get("error"):
            return self.store.update_analysis(
                analysis_id,
                status="failed",
                result_json={
                    "plan": plan.to_dict(),
                    "execution_results": state.get("execution_results", []),
                },
                error=state["error"],
                completed_at=utc_now(),
            )
        validation = state.get("validation", {})
        if validation.get("status") != "passed":
            error = "Validator meminta revisi: " + str(validation.get("issues", []))
            return self.store.update_analysis(
                analysis_id,
                status="failed",
                result_json={"plan": plan.to_dict(), "validation": validation},
                error=error,
                completed_at=utc_now(),
            )

        evidence = state.get("evidence", [])
        answer = state.get("final_answer", "")
        visualization = state.get("visualization")
        artifact = None
        if visualization:
            path = self.visualizer.save(visualization, self.settings.artifact_dir, analysis_id)
            artifact = self.store.add_artifact(
                analysis_id, "chart_spec", str(path.resolve()), visualization
            )
        coverage = evidence_coverage(answer, [item["key"] for item in evidence])
        self.store.add_evaluation(
            analysis_id,
            "evidence_coverage",
            coverage,
            {"evidence_count": len(evidence)},
        )
        result = {
            "plan": plan.to_dict(),
            "evidence": evidence,
            "validation": validation,
            "visualization": visualization,
            "artifact": artifact,
        }
        updated = self.store.update_analysis(
            analysis_id,
            status="completed",
            result_json=result,
            final_answer=answer,
            completed_at=utc_now(),
        )
        if self.tracker is not None:
            run_id = self.tracker.log_analysis(
                analysis_id=analysis_id,
                dataset_id=dataset["id"],
                question=question,
                mode=updated["mode"],
                result=result,
                coverage=coverage,
            )
            if run_id:
                result["mlflow_run_id"] = run_id
                updated = self.store.update_analysis(analysis_id, result_json=result)
        return updated

    def _persist_events(self, analysis_id: str, events: list[dict[str, Any]]) -> None:
        for event in events:
            self.store.add_step(
                analysis_id,
                event["agent_name"],
                event.get("input", {}),
                event.get("output", {}),
                int(event.get("latency_ms", 0)),
                event.get("status", "success"),
                code=event.get("code"),
            )

    @staticmethod
    def _plan_from_dict(value: dict[str, Any]) -> AnalysisPlan:
        return AnalysisPlan(
            objective=value["objective"],
            required_columns=value["required_columns"],
            steps=value["steps"],
            risks=value["risks"],
            queries=[QueryPlan(**query) for query in value["queries"]],
            answer_type=value.get("answer_type", "aggregate"),
            visualization=value.get("visualization", {}),
        )

    @staticmethod
    def _dataset_path(storage_uri: str) -> Path:
        return Path(storage_uri)
