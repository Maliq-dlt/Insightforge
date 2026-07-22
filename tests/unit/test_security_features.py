from __future__ import annotations

import unittest
from pathlib import Path

from insightforge.agents.statistics_agent import StatisticsAgent
from insightforge.sandbox.python_executor import PythonPolicyError, validate_python


class SecurityFeatureTest(unittest.TestCase):
    def test_python_policy_allows_analysis_and_blocks_host_access(self) -> None:
        validate_python("import pandas as pd\nresult = {'rows': 1}")
        for code in (
            "import os\nresult = os.environ",
            "result = open('secret.txt').read()",
            "import subprocess\nresult = subprocess.run(['whoami'])",
        ):
            with self.subTest(code=code), self.assertRaises(PythonPolicyError):
                validate_python(code)

    def test_advanced_group_comparison_returns_inference(self) -> None:
        root = Path(".runtime/tests/unit_features")
        root.mkdir(parents=True, exist_ok=True)
        dataset = root / "groups.csv"
        dataset.write_text(
            "group,outcome\nA,1\nA,2\nA,3\nA,4\nB,10\nB,11\nB,12\nB,13\n",
            encoding="utf-8",
        )
        result = StatisticsAgent().run(
            dataset,
            method="compare_groups",
            outcome="outcome",
            group="group",
        )
        self.assertIn(result["method"], {"welch_t_test", "mann_whitney_u"})
        self.assertLess(result["p_value"], 0.05)
        self.assertTrue(result["significant"])
        self.assertIn("effect_size", result)


if __name__ == "__main__":
    unittest.main()
