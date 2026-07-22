from __future__ import annotations

import operator
from pathlib import Path
from time import perf_counter
from typing import Annotated, Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from insightforge.agents.critic import Critic
from insightforge.agents.planner import AnalysisPlan
from insightforge.agents.report_agent import ReportAgent
from insightforge.agents.visualization_agent import VisualizationAgent
from insightforge.sandbox.executor import SQLExecutor


class AnalysisGraphState(TypedDict, total=False):
    question: str
    schema: list[dict[str, Any]]
    profile: dict[str, Any]
    dataset_path: str
    plan: AnalysisPlan
    execution_results: list[dict[str, Any]]
    validation: dict[str, Any]
    evidence: list[dict[str, Any]]
    final_answer: str
    visualization: dict[str, Any] | None
    error: str | None
    events: Annotated[list[dict[str, Any]], operator.add]


class LangGraphOrchestrator:
    def __init__(
        self,
        planner: Any,
        executor: SQLExecutor,
        critic: Critic,
        reporter: ReportAgent,
        visualizer: VisualizationAgent,
    ) -> None:
        self.planner = planner
        self.executor = executor
        self.critic = critic
        self.reporter = reporter
        self.visualizer = visualizer
        self.plan_graph = self._build_plan_graph()
        self.execution_graph = self._build_execution_graph()

    def plan(
        self, question: str, schema: list[dict[str, Any]], profile: dict[str, Any]
    ) -> AnalysisGraphState:
        return self.plan_graph.invoke(
            {"question": question, "schema": schema, "profile": profile, "events": []}
        )

    def execute(
        self,
        question: str,
        schema: list[dict[str, Any]],
        dataset_path: Path,
        plan: AnalysisPlan,
    ) -> AnalysisGraphState:
        return self.execution_graph.invoke(
            {
                "question": question,
                "schema": schema,
                "dataset_path": str(dataset_path),
                "plan": plan,
                "events": [],
            }
        )

    def _build_plan_graph(self):
        graph = StateGraph(AnalysisGraphState)
        graph.add_node("planner", self._plan_node)
        graph.add_edge(START, "planner")
        graph.add_edge("planner", END)
        return graph.compile()

    def _build_execution_graph(self):
        graph = StateGraph(AnalysisGraphState)
        graph.add_node("execute", self._execute_node)
        graph.add_node("critic", self._critic_node)
        graph.add_node("report", self._report_node)
        graph.add_edge(START, "execute")
        graph.add_conditional_edges(
            "execute",
            self._after_execution,
            {"critic": "critic", "end": END},
        )
        graph.add_conditional_edges(
            "critic",
            self._after_critic,
            {"report": "report", "end": END},
        )
        graph.add_edge("report", END)
        return graph.compile()

    def _plan_node(self, state: AnalysisGraphState) -> dict[str, Any]:
        started = perf_counter()
        plan = self.planner.build(state["question"], state["schema"], state["profile"])
        return {
            "plan": plan,
            "events": [
                {
                    "agent_name": "planner",
                    "input": {"question": state["question"]},
                    "output": plan.to_dict(),
                    "latency_ms": int((perf_counter() - started) * 1000),
                    "status": "success",
                }
            ],
        }

    def _execute_node(self, state: AnalysisGraphState) -> dict[str, Any]:
        results: list[dict[str, Any]] = []
        events: list[dict[str, Any]] = []
        for query in state["plan"].queries:
            started = perf_counter()
            try:
                result = self.executor.execute(Path(state["dataset_path"]), query.sql)
                result.update({"evidence_key": query.evidence_key, "purpose": query.purpose})
                results.append(result)
                events.append(
                    {
                        "agent_name": "sql_agent",
                        "input": {"purpose": query.purpose},
                        "output": result,
                        "code": query.sql,
                        "latency_ms": int((perf_counter() - started) * 1000),
                        "status": "success",
                    }
                )
            except Exception as error:
                failed = {"evidence_key": query.evidence_key, "error": str(error)}
                results.append(failed)
                events.append(
                    {
                        "agent_name": "sql_agent",
                        "input": {"purpose": query.purpose},
                        "output": failed,
                        "code": query.sql,
                        "latency_ms": int((perf_counter() - started) * 1000),
                        "status": "failure",
                    }
                )
                return {"execution_results": results, "events": events, "error": str(error)}
        return {"execution_results": results, "events": events, "error": None}

    def _critic_node(self, state: AnalysisGraphState) -> dict[str, Any]:
        started = perf_counter()
        validation = self.critic.validate(
            state["plan"], state["schema"], state["execution_results"]
        )
        return {
            "validation": validation,
            "events": [
                {
                    "agent_name": "critic",
                    "input": {"result_count": len(state["execution_results"])},
                    "output": validation,
                    "latency_ms": int((perf_counter() - started) * 1000),
                    "status": "success" if validation["status"] == "passed" else "failure",
                }
            ],
        }

    def _report_node(self, state: AnalysisGraphState) -> dict[str, Any]:
        started = perf_counter()
        evidence = self._evidence(state["execution_results"])
        answer = self.reporter.render(state["question"], state["plan"].to_dict(), evidence)
        visualization = self.visualizer.build(evidence)
        return {
            "evidence": evidence,
            "final_answer": answer,
            "visualization": visualization,
            "events": [
                {
                    "agent_name": "report_agent",
                    "input": {"evidence_ids": [item["id"] for item in evidence]},
                    "output": {"final_answer": answer, "visualization": visualization},
                    "latency_ms": int((perf_counter() - started) * 1000),
                    "status": "success",
                }
            ],
        }

    @staticmethod
    def _after_execution(state: AnalysisGraphState) -> Literal["critic", "end"]:
        return "end" if state.get("error") else "critic"

    @staticmethod
    def _after_critic(state: AnalysisGraphState) -> Literal["report", "end"]:
        validation = state.get("validation", {})
        return "report" if validation.get("status") == "passed" else "end"

    @staticmethod
    def _evidence(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "id": f"evidence_{item['evidence_key']}",
                "key": item["evidence_key"],
                "purpose": item["purpose"],
                "sql": item["sql"],
                "columns": item["columns"],
                "rows": item["rows"],
                "row_count": item["row_count"],
                "truncated": item["truncated"],
                "source": item.get("engine", "duckdb"),
            }
            for item in results
            if "error" not in item
        ]
