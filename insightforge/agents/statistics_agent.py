from __future__ import annotations

from math import sqrt
from pathlib import Path
from time import perf_counter
from typing import Any

import pandas as pd
from scipy import stats

from insightforge.storage.database import TraceStore, utc_now


class StatisticsAgent:
    def run(
        self,
        dataset_path: Path,
        method: str,
        outcome: str | None = None,
        group: str | None = None,
        x: str | None = None,
        y: str | None = None,
        alpha: float = 0.05,
    ) -> dict[str, Any]:
        frame = self._load(dataset_path)
        selected = method.lower()
        if selected == "auto":
            if outcome and group and pd.api.types.is_numeric_dtype(frame[outcome]):
                selected = "compare_groups"
            elif x and y and pd.api.types.is_numeric_dtype(frame[x]) and pd.api.types.is_numeric_dtype(frame[y]):
                selected = "correlation"
            elif x and y:
                selected = "chi_square"
            else:
                raise ValueError("Auto statistics memerlukan outcome+group atau x+y.")
        if selected == "compare_groups":
            if not outcome or not group:
                raise ValueError("compare_groups memerlukan outcome dan group.")
            return self.compare_groups(frame, outcome, group, alpha)
        if selected == "correlation":
            if not x or not y:
                raise ValueError("correlation memerlukan x dan y.")
            return self.correlation(frame, x, y, alpha)
        if selected == "chi_square":
            if not x or not y:
                raise ValueError("chi_square memerlukan x dan y.")
            return self.chi_square(frame, x, y, alpha)
        raise ValueError(f"Metode statistik tidak didukung: {method}")

    def compare_groups(
        self, frame: pd.DataFrame, outcome: str, group: str, alpha: float
    ) -> dict[str, Any]:
        self._require_columns(frame, outcome, group)
        grouped = []
        labels = [value for value in frame[group].dropna().unique().tolist()]
        if len(labels) != 2:
            raise ValueError("compare_groups membutuhkan tepat dua grup.")
        for label in labels:
            values = pd.to_numeric(
                frame.loc[frame[group] == label, outcome], errors="coerce"
            ).dropna()
            if len(values) < 3:
                raise ValueError("Setiap grup membutuhkan minimal tiga observasi.")
            grouped.append(values.astype(float))
        first, second = grouped
        normality = [
            float(stats.shapiro(values.sample(min(len(values), 5000), random_state=0)).pvalue)
            for values in grouped
        ]
        levene_p = float(stats.levene(first, second, center="median").pvalue)
        if all(value > alpha for value in normality):
            test = stats.ttest_ind(first, second, equal_var=False)
            method = "welch_t_test"
            effect_size = self._cohen_d(first, second)
            confidence_interval = self._welch_ci(first, second, alpha)
        else:
            test = stats.mannwhitneyu(first, second, alternative="two-sided")
            method = "mann_whitney_u"
            effect_size = float((2 * test.statistic) / (len(first) * len(second)) - 1)
            confidence_interval = None
        return {
            "method": method,
            "outcome": outcome,
            "group": group,
            "groups": [str(value) for value in labels],
            "sample_sizes": [len(first), len(second)],
            "means": [float(first.mean()), float(second.mean())],
            "medians": [float(first.median()), float(second.median())],
            "statistic": float(test.statistic),
            "p_value": float(test.pvalue),
            "alpha": alpha,
            "significant": bool(test.pvalue < alpha),
            "effect_size": effect_size,
            "confidence_interval": confidence_interval,
            "assumptions": {
                "shapiro_p_values": normality,
                "levene_p_value": levene_p,
                "normality_passed": all(value > alpha for value in normality),
            },
            "limitations": ["Statistical association is not causal proof."],
        }

    def correlation(
        self, frame: pd.DataFrame, x: str, y: str, alpha: float
    ) -> dict[str, Any]:
        self._require_columns(frame, x, y)
        values = frame[[x, y]].apply(pd.to_numeric, errors="coerce").dropna()
        if len(values) < 4:
            raise ValueError("Correlation membutuhkan minimal empat pasangan observasi.")
        sample = values.sample(min(len(values), 5000), random_state=0)
        normal = all(float(stats.shapiro(sample[column]).pvalue) > alpha for column in (x, y))
        result = stats.pearsonr(values[x], values[y]) if normal else stats.spearmanr(values[x], values[y])
        return {
            "method": "pearson" if normal else "spearman",
            "x": x,
            "y": y,
            "sample_size": len(values),
            "coefficient": float(result.statistic),
            "p_value": float(result.pvalue),
            "alpha": alpha,
            "significant": bool(result.pvalue < alpha),
            "assumptions": {"normality_passed": normal},
            "limitations": ["Correlation does not imply causation."],
        }

    def chi_square(
        self, frame: pd.DataFrame, x: str, y: str, alpha: float
    ) -> dict[str, Any]:
        self._require_columns(frame, x, y)
        table = pd.crosstab(frame[x], frame[y])
        if table.shape[0] < 2 or table.shape[1] < 2:
            raise ValueError("Chi-square membutuhkan minimal tabel 2x2.")
        statistic, p_value, degrees_of_freedom, expected = stats.chi2_contingency(table)
        sample_size = int(table.to_numpy().sum())
        denominator = max(min(table.shape) - 1, 1)
        cramers_v = sqrt(float(statistic) / (sample_size * denominator))
        return {
            "method": "chi_square",
            "x": x,
            "y": y,
            "sample_size": sample_size,
            "statistic": float(statistic),
            "p_value": float(p_value),
            "degrees_of_freedom": int(degrees_of_freedom),
            "cramers_v": cramers_v,
            "alpha": alpha,
            "significant": bool(p_value < alpha),
            "minimum_expected_count": float(expected.min()),
            "limitations": ["Low expected counts can invalidate chi-square approximation."],
        }

    @staticmethod
    def _load(dataset_path: Path) -> pd.DataFrame:
        if dataset_path.suffix.lower() == ".csv":
            return pd.read_csv(dataset_path)
        if dataset_path.suffix.lower() == ".parquet":
            return pd.read_parquet(dataset_path)
        raise ValueError("Format dataset tidak didukung.")

    @staticmethod
    def _require_columns(frame: pd.DataFrame, *columns: str) -> None:
        missing = [column for column in columns if column not in frame.columns]
        if missing:
            raise ValueError("Kolom tidak tersedia: " + ", ".join(missing))

    @staticmethod
    def _cohen_d(first: pd.Series, second: pd.Series) -> float:
        pooled = sqrt(
            ((len(first) - 1) * first.var(ddof=1) + (len(second) - 1) * second.var(ddof=1))
            / (len(first) + len(second) - 2)
        )
        return float((first.mean() - second.mean()) / pooled) if pooled else 0.0

    @staticmethod
    def _welch_ci(first: pd.Series, second: pd.Series, alpha: float) -> list[float]:
        difference = float(first.mean() - second.mean())
        first_term = first.var(ddof=1) / len(first)
        second_term = second.var(ddof=1) / len(second)
        standard_error = sqrt(first_term + second_term)
        degrees_of_freedom = (first_term + second_term) ** 2 / (
            first_term**2 / (len(first) - 1) + second_term**2 / (len(second) - 1)
        )
        critical = float(stats.t.ppf(1 - alpha / 2, degrees_of_freedom))
        return [difference - critical * standard_error, difference + critical * standard_error]


class StatisticsService:
    def __init__(self, store: TraceStore, agent: StatisticsAgent) -> None:
        self.store = store
        self.agent = agent

    def run(self, dataset_id: str, request: dict[str, Any]) -> dict[str, Any]:
        dataset = self.store.get_dataset(dataset_id)
        if dataset is None:
            raise KeyError(dataset_id)
        plan = {"type": "statistics", **request}
        analysis = self.store.create_analysis(
            dataset_id,
            f"Statistical analysis: {request.get('method', 'auto')}",
            "autonomous",
            "running",
            plan,
        )
        started = perf_counter()
        try:
            result = self.agent.run(Path(dataset["storage_uri"]), **request)
            latency = int((perf_counter() - started) * 1000)
            self.store.add_step(
                analysis["id"], "statistics_agent", request, result, latency, "success"
            )
            answer = (
                f"Metode {result['method']}; p-value={result['p_value']:.6g}; "
                f"significant={result['significant']}."
            )
            self.store.add_evaluation(
                analysis["id"], "statistical_validity", 1.0, {"method": result["method"]}
            )
            return self.store.update_analysis(
                analysis["id"],
                status="completed",
                result_json={"statistics": result},
                final_answer=answer,
                completed_at=utc_now(),
            )
        except Exception as error:
            self.store.add_step(
                analysis["id"],
                "statistics_agent",
                request,
                {"error": str(error)},
                int((perf_counter() - started) * 1000),
                "failure",
            )
            return self.store.update_analysis(
                analysis["id"], status="failed", error=str(error), completed_at=utc_now()
            )
