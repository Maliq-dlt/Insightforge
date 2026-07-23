from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

from insightforge.sandbox.executor import quote_identifier, sql_literal


@dataclass(frozen=True)
class QueryPlan:
    purpose: str
    evidence_key: str
    sql: str


@dataclass(frozen=True)
class AnalysisPlan:
    objective: str
    required_columns: list[str]
    steps: list[str]
    risks: list[str]
    queries: list[QueryPlan]
    answer_type: str = "aggregate"
    visualization: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_MONTHS = {
    "januari": 1,
    "january": 1,
    "februari": 2,
    "february": 2,
    "maret": 3,
    "march": 3,
    "april": 4,
    "mei": 5,
    "may": 5,
    "juni": 6,
    "june": 6,
    "juli": 7,
    "july": 7,
    "agustus": 8,
    "august": 8,
    "september": 9,
    "oktober": 10,
    "october": 10,
    "november": 11,
    "desember": 12,
    "december": 12,
}
_DIMENSION_ALIASES = {
    "kota": "city",
    "city": "city",
    "kategori": "category",
    "category": "category",
    "produk": "product",
    "product": "product",
    "channel": "channel",
    "segmen": "segment",
    "segment": "segment",
    "campaign": "campaign",
}
_NUMERIC_MARKERS = ("INT", "DECIMAL", "DOUBLE", "FLOAT", "REAL")


def _normalized(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _contains(question: str, words: tuple[str, ...]) -> bool:
    lowered = question.lower()
    return any(word in lowered for word in words)


# ponytail: Rule planner covers deterministic MVP intents; add structured LLM planning after benchmark and injection gates.
class PlanBuilder:
    def build(self, question: str, schema: list[dict[str, Any]], profile: dict[str, Any]) -> AnalysisPlan:
        if not question.strip():
            raise ValueError("Pertanyaan tidak boleh kosong.")
        names = [item["name"] for item in schema]
        numeric_names = [
            item["name"]
            for item in schema
            if any(marker in item["type"].upper() for marker in _NUMERIC_MARKERS)
        ]
        metric = self._metric(question, numeric_names)
        dimension = self._dimension(question, names)
        date_column = self._date_column(schema)
        filters = self._filters(question, profile)
        lowered = question.lower()

        if _contains(lowered, ("missing", "kosong", "null")):
            return AnalysisPlan(
                objective=question,
                required_columns=names,
                steps=["periksa missing value", "urutkan kolom bermasalah", "susun batasan kualitas data"],
                risks=["missing value tidak selalu berarti data invalid"],
                queries=[QueryPlan("Mengukur missing value setiap kolom", "missing_values", self._missing_query(names))],
                answer_type="quality",
                visualization={"type": "bar", "x": "column", "y": "missing_rate"},
            )

        months = [number for word, number in _MONTHS.items() if re.search(rf"\b{word}\b", lowered)]
        comparison_requested = _contains(
            lowered, ("turun", "menurun", "decline", "dibanding", "growth", "pertumbuhan")
        )
        if date_column and metric and months and comparison_requested:
            current_month = max(months)
            previous_month = 12 if current_month == 1 else current_month - 1
            breakdown = dimension or next(
                (name for name in names if "category" in name.lower() or "kategori" in name.lower()), None
            )
            year = self._latest_year(profile, date_column)
            date_filter = self._date_filter(date_column, year, previous_month, current_month)
            where = self._where(filters)
            if where:
                date_filter += " AND " + where
            month_expression = self._month_expression(date_column)
            queries = [
                QueryPlan(
                    "Membandingkan metrik bulan sebelumnya dan bulan saat ini",
                    "monthly_comparison",
                    (
                        f"SELECT {month_expression} AS month, "
                        f"SUM({quote_identifier(metric)}) AS metric_value "
                        f"FROM dataset WHERE {date_filter} GROUP BY 1 ORDER BY 1"
                    ),
                )
            ]
            if breakdown:
                queries.append(
                    QueryPlan(
                        f"Mengurutkan kontribusi perubahan berdasarkan {breakdown}",
                        "segment_contribution",
                        self._segment_comparison(
                            date_column,
                            metric,
                            breakdown,
                            year,
                            previous_month,
                            current_month,
                            filters,
                        ),
                    )
                )
            return AnalysisPlan(
                objective=question,
                required_columns=self._required([date_column, metric, breakdown, *filters.keys()]),
                steps=[
                    "filter periode dan segmen",
                    "bandingkan dua bulan",
                    "urai perubahan per segmen",
                    "susun evidence-backed answer",
                ],
                risks=["perbandingan belum mengontrol seasonality", "association bukan causal proof"],
                queries=queries,
                answer_type="comparison",
                visualization={"type": "bar", "x": breakdown or "month", "y": "delta"},
            )

        if _contains(lowered, ("top", "tertinggi", "teratas", "paling besar", "paling tinggi")) and dimension and metric:
            query = (
                f"SELECT {quote_identifier(dimension)} AS segment, "
                f"SUM({quote_identifier(metric)}) AS metric_value "
                f"FROM dataset{self._where_clause(filters)} "
                "GROUP BY 1 ORDER BY metric_value DESC LIMIT 10"
            )
            return AnalysisPlan(
                objective=question,
                required_columns=self._required([metric, dimension, *filters.keys()]),
                steps=["agregasikan metrik", "ranking segmen", "ambil top 10", "susun evidence"],
                risks=["ranking sensitif terhadap definisi metrik dan periode"],
                queries=[QueryPlan("Ranking segmen", "top_segments", query)],
                visualization={"type": "bar", "x": "segment", "y": "metric_value"},
            )

        if dimension and metric:
            query = (
                f"SELECT {quote_identifier(dimension)} AS segment, "
                f"SUM({quote_identifier(metric)}) AS metric_value, COUNT(*) AS row_count "
                f"FROM dataset{self._where_clause(filters)} "
                "GROUP BY 1 ORDER BY metric_value DESC"
            )
            return AnalysisPlan(
                objective=question,
                required_columns=self._required([metric, dimension, *filters.keys()]),
                steps=["filter data", "agregasikan per segmen", "validasi hasil", "susun evidence"],
                risks=["agregasi tidak membuktikan hubungan sebab-akibat"],
                queries=[QueryPlan("Agregasi berdasarkan segmen", "grouped_aggregate", query)],
                visualization={"type": "bar", "x": "segment", "y": "metric_value"},
            )

        if _contains(lowered, ("jumlah baris", "berapa baris", "count", "jumlah data")):
            query = f"SELECT COUNT(*) AS row_count FROM dataset{self._where_clause(filters)}"
            required = list(filters)
        elif metric:
            function = "AVG" if _contains(lowered, ("rata", "average", "mean")) else "SUM"
            query = (
                f"SELECT {function}({quote_identifier(metric)}) AS metric_value, "
                f"COUNT({quote_identifier(metric)}) AS non_null_count "
                f"FROM dataset{self._where_clause(filters)}"
            )
            required = [metric, *filters]
        else:
            raise ValueError("Planner tidak menemukan kolom numerik yang dapat dianalisis.")
        return AnalysisPlan(
            objective=question,
            required_columns=self._required(required),
            steps=["filter data", "hitung agregasi", "validasi hasil", "susun evidence-backed answer"],
            risks=["definisi metrik mengikuti kolom yang tersedia"],
            queries=[QueryPlan("Agregasi utama", "aggregate", query)],
            visualization={"type": "kpi", "x": None, "y": "metric_value"},
        )

    @staticmethod
    def _metric(question: str, numeric_names: list[str]) -> str | None:
        normalized_question = _normalized(question)
        for name in numeric_names:
            if _normalized(name) in normalized_question:
                return name
        for preferred in ("revenue", "sales", "amount", "total", "quantity", "value"):
            for name in numeric_names:
                if preferred in _normalized(name):
                    return name
        return numeric_names[0] if numeric_names else None

    @staticmethod
    def _dimension(question: str, names: list[str]) -> str | None:
        normalized_names = {_normalized(name): name for name in names}
        lowered = question.lower()
        for alias, canonical in _DIMENSION_ALIASES.items():
            if alias not in lowered:
                continue
            for normalized, actual in normalized_names.items():
                if canonical in normalized or alias in normalized:
                    return actual
        return None

    @staticmethod
    def _date_column(schema: list[dict[str, Any]]) -> str | None:
        for item in schema:
            if "DATE" in item["type"].upper() or "TIME" in item["type"].upper():
                return item["name"]
        return next(
            (
                item["name"]
                for item in schema
                if any(word in item["name"].lower() for word in ("date", "time", "timestamp"))
            ),
            None,
        )

    @staticmethod
    def _filters(question: str, profile: dict[str, Any]) -> dict[str, str]:
        lowered = question.lower()
        filters: dict[str, str] = {}
        for column, details in profile.get("columns", {}).items():
            for value in details.get("sample_values", []):
                if isinstance(value, str) and len(value) >= 3 and re.search(
                    rf"\b{re.escape(value.lower())}\b", lowered
                ):
                    filters[column] = value
                    break
        return filters

    @staticmethod
    def _where(filters: dict[str, str]) -> str:
        return " AND ".join(
            f"{quote_identifier(column)} = {sql_literal(value)}" for column, value in filters.items()
        )

    @classmethod
    def _where_clause(cls, filters: dict[str, str]) -> str:
        where = cls._where(filters)
        return f" WHERE {where}" if where else ""

    @staticmethod
    def _latest_year(profile: dict[str, Any], date_column: str) -> int | None:
        value = profile.get("date_range", {}).get(date_column, {}).get("end")
        match = re.match(r"(\d{4})", str(value))
        return int(match.group(1)) if match else None

    @staticmethod
    def _month_expression(date_column: str) -> str:
        return f"EXTRACT(MONTH FROM {quote_identifier(date_column)})"

    @classmethod
    def _date_filter(
        cls, date_column: str, year: int | None, previous_month: int, current_month: int
    ) -> str:
        column = quote_identifier(date_column)
        if year is None:
            return f"{cls._month_expression(date_column)} IN ({previous_month}, {current_month})"
        start_year = year - 1 if previous_month == 12 and current_month == 1 else year
        next_year, next_month = (year + 1, 1) if current_month == 12 else (year, current_month + 1)
        return (
            f"{column} >= '{start_year:04d}-{previous_month:02d}-01' AND "
            f"{column} < '{next_year:04d}-{next_month:02d}-01'"
        )

    @classmethod
    def _segment_comparison(
        cls,
        date_column: str,
        metric: str,
        dimension: str,
        year: int | None,
        previous_month: int,
        current_month: int,
        filters: dict[str, str],
    ) -> str:
        date_filter = cls._date_filter(date_column, year, previous_month, current_month)
        where = cls._where(filters)
        if where:
            date_filter += " AND " + where
        return (
            "WITH monthly AS ("
            f"SELECT {quote_identifier(dimension)} AS segment, "
            f"{cls._month_expression(date_column)} AS month, "
            f"SUM({quote_identifier(metric)}) AS metric_value FROM dataset "
            f"WHERE {date_filter} GROUP BY 1, 2"
            "), comparison AS ("
            "SELECT segment, "
            f"COALESCE(SUM(metric_value) FILTER (WHERE month = {previous_month}), 0) AS previous_value, "
            f"COALESCE(SUM(metric_value) FILTER (WHERE month = {current_month}), 0) AS current_value "
            "FROM monthly GROUP BY 1"
            ") SELECT segment, previous_value, current_value, "
            "current_value - previous_value AS delta "
            "FROM comparison ORDER BY delta ASC LIMIT 10"
        )

    @staticmethod
    def _missing_query(names: list[str]) -> str:
        parts = [
            f"SELECT {sql_literal(name)} AS column, "
            f"COUNT(*) FILTER (WHERE {quote_identifier(name)} IS NULL) AS missing_count, "
            f"CAST(COUNT(*) FILTER (WHERE {quote_identifier(name)} IS NULL) AS DOUBLE) "
            "/ NULLIF(COUNT(*), 0) AS missing_rate FROM dataset"
            for name in names
        ]
        return " UNION ALL ".join(parts) + " ORDER BY missing_rate DESC"

    @staticmethod
    def _required(values: Sequence[str | None]) -> list[str]:
        return list(dict.fromkeys(value for value in values if value))

