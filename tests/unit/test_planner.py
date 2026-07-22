from __future__ import annotations

import unittest
from pathlib import Path

from insightforge.agents.planner import PlanBuilder
from insightforge.profiling.profiler import DatasetProfiler


class PlannerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.profile = DatasetProfiler().profile(Path("benchmark/datasets/retail_small.csv"))
        cls.schema = cls.profile["schema"]
        cls.planner = PlanBuilder()

    def test_total_question_is_not_grouped(self) -> None:
        plan = self.planner.build("Berapa total revenue?", self.schema, self.profile)
        self.assertEqual(plan.answer_type, "aggregate")
        self.assertIn("SUM", plan.queries[0].sql)
        self.assertNotIn("GROUP BY", plan.queries[0].sql)

    def test_root_cause_plan_has_period_and_segment_evidence(self) -> None:
        plan = self.planner.build(
            "Mengapa revenue Bandung turun pada April?", self.schema, self.profile
        )
        self.assertEqual([query.evidence_key for query in plan.queries], [
            "monthly_comparison",
            "segment_contribution",
        ])
        self.assertIn("city", plan.required_columns)
        self.assertIn("category", plan.required_columns)


if __name__ == "__main__":
    unittest.main()
