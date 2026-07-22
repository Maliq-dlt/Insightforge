from __future__ import annotations

import csv
import re
import statistics
from pathlib import Path
from typing import Any

try:
    import duckdb
except ImportError:  # local fallback; production dependency remains DuckDB
    duckdb = None  # type: ignore[assignment]

from insightforge.sandbox.executor import quote_identifier, source_sql
from insightforge.serialization import json_value

_NUMERIC_MARKERS = ("INT", "DECIMAL", "DOUBLE", "FLOAT", "REAL", "HUGEINT")
_DATE_MARKERS = ("DATE", "TIME")
_PII_MARKERS = ("email", "phone", "mobile", "address", "ssn", "nik", "passport")
_TARGET_MARKERS = ("target", "label", "outcome", "converted", "churn", "revenue")


def _is_numeric(data_type: str) -> bool:
    upper = data_type.upper()
    return any(marker in upper for marker in _NUMERIC_MARKERS)


def _is_date(data_type: str) -> bool:
    upper = data_type.upper()
    return any(marker in upper for marker in _DATE_MARKERS)


def _fetchone(connection: Any, query: str) -> tuple[Any, ...]:
    row = connection.execute(query).fetchone()
    if row is None:
        raise RuntimeError("DuckDB mengembalikan hasil kosong.")
    return tuple(row)


class DatasetProfiler:
    def profile(self, dataset_path: Path) -> dict[str, Any]:
        if duckdb is None:
            return self._profile_csv_fallback(dataset_path)
        connection = duckdb.connect(database=":memory:")
        try:
            connection.execute(f"CREATE TEMP VIEW dataset AS SELECT * FROM {source_sql(dataset_path)}")
            description = connection.execute("DESCRIBE dataset").fetchall()
            schema = [{"name": row[0], "type": row[1], "nullable": row[2] == "YES"} for row in description]
            row_count = int(_fetchone(connection, "SELECT COUNT(*) FROM dataset")[0])
            duplicate_count = int(
                _fetchone(
                    connection,
                    "SELECT COUNT(*) - (SELECT COUNT(*) FROM (SELECT DISTINCT * FROM dataset)) "
                    "FROM dataset",
                )[0]
            )
            columns: dict[str, dict[str, Any]] = {}
            identifiers: list[str] = []
            pii_columns: list[str] = []
            target_columns: list[str] = []
            date_range: dict[str, dict[str, Any]] = {}

            for item in schema:
                name = item["name"]
                data_type = item["type"]
                identifier = quote_identifier(name)
                missing_count, distinct_count = _fetchone(
                    connection,
                    f"SELECT COUNT(*) FILTER (WHERE {identifier} IS NULL), "
                    f"COUNT(DISTINCT {identifier}) FROM dataset"
                )
                samples = connection.execute(
                    f"SELECT {identifier} FROM dataset WHERE {identifier} IS NOT NULL LIMIT 5"
                ).fetchall()
                details: dict[str, Any] = {
                    "type": data_type,
                    "missing_count": int(missing_count),
                    "missing_rate": float(missing_count / row_count) if row_count else 0.0,
                    "distinct_count": int(distinct_count),
                    "sample_values": [json_value(row[0]) for row in samples],
                }
                if _is_numeric(data_type):
                    minimum, maximum, mean, standard_deviation, median = _fetchone(
                        connection,
                        f"SELECT MIN({identifier}), MAX({identifier}), AVG({identifier}), "
                        f"STDDEV_POP({identifier}), MEDIAN({identifier}) FROM dataset"
                    )
                    details["statistics"] = {
                        "min": json_value(minimum),
                        "max": json_value(maximum),
                        "mean": json_value(mean),
                        "stddev": json_value(standard_deviation),
                        "median": json_value(median),
                    }
                elif _is_date(data_type):
                    minimum, maximum = _fetchone(
                        connection,
                        f"SELECT MIN({identifier}), MAX({identifier}) FROM dataset"
                    )
                    date_range[name] = {"start": json_value(minimum), "end": json_value(maximum)}
                self._classify(name, row_count, int(distinct_count), identifiers, pii_columns, target_columns)
                columns[name] = details
            return self._result(row_count, schema, columns, duplicate_count, date_range, identifiers, pii_columns, target_columns)
        finally:
            connection.close()

    def _profile_csv_fallback(self, dataset_path: Path) -> dict[str, Any]:
        if dataset_path.suffix.lower() != ".csv":
            raise RuntimeError("Fallback profiler hanya mendukung CSV; install DuckDB untuk Parquet.")
        with dataset_path.open(newline="", encoding="utf-8-sig") as file_handle:
            rows = list(csv.DictReader(file_handle))
        names = list(rows[0].keys()) if rows else []
        schema: list[dict[str, Any]] = []
        columns: dict[str, dict[str, Any]] = {}
        identifiers: list[str] = []
        pii_columns: list[str] = []
        target_columns: list[str] = []
        date_range: dict[str, dict[str, Any]] = {}
        for name in names:
            values = [row.get(name, "") for row in rows]
            non_empty = [value for value in values if value not in {None, ""}]
            data_type = self._infer_type(non_empty)
            typed_values = [self._coerce(value, data_type) for value in non_empty]
            numeric_values = [
                value for value in typed_values if isinstance(value, (int, float))
            ]
            missing_count = len(values) - len(non_empty)
            distinct_count = len(set(non_empty))
            details: dict[str, Any] = {
                "type": data_type,
                "missing_count": missing_count,
                "missing_rate": missing_count / len(rows) if rows else 0.0,
                "distinct_count": distinct_count,
                "sample_values": non_empty[:5],
            }
            if _is_numeric(data_type) and numeric_values:
                details["statistics"] = {
                    "min": min(numeric_values),
                    "max": max(numeric_values),
                    "mean": statistics.fmean(numeric_values),
                    "stddev": statistics.pstdev(numeric_values),
                    "median": statistics.median(numeric_values),
                }
            if _is_date(data_type) and non_empty:
                date_range[name] = {"start": min(non_empty), "end": max(non_empty)}
            self._classify(name, len(rows), distinct_count, identifiers, pii_columns, target_columns)
            schema.append({"name": name, "type": data_type, "nullable": True})
            columns[name] = details
        duplicate_count = len(rows) - len({tuple(row.get(name) for name in names) for row in rows})
        return self._result(len(rows), schema, columns, duplicate_count, date_range, identifiers, pii_columns, target_columns)

    @staticmethod
    def _infer_type(values: list[str]) -> str:
        if values and all(re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:[T ].*)?", value) for value in values):
            return "DATE"
        if values:
            try:
                [int(value) for value in values]
                return "BIGINT"
            except ValueError:
                try:
                    [float(value) for value in values]
                    return "DOUBLE"
                except ValueError:
                    pass
        return "VARCHAR"

    @staticmethod
    def _coerce(value: str, data_type: str) -> int | float | str:
        if "INT" in data_type:
            return int(value)
        if _is_numeric(data_type):
            return float(value)
        return value

    @staticmethod
    def _classify(
        name: str,
        row_count: int,
        distinct_count: int,
        identifiers: list[str],
        pii_columns: list[str],
        target_columns: list[str],
    ) -> None:
        lowered = name.lower()
        if lowered == "id" or lowered.endswith("_id") or (row_count and distinct_count / row_count >= 0.98):
            identifiers.append(name)
        if any(marker in lowered for marker in _PII_MARKERS):
            pii_columns.append(name)
        if any(marker in lowered for marker in _TARGET_MARKERS):
            target_columns.append(name)

    @staticmethod
    def _result(
        row_count: int,
        schema: list[dict[str, Any]],
        columns: dict[str, dict[str, Any]],
        duplicate_count: int,
        date_range: dict[str, dict[str, Any]],
        identifiers: list[str],
        pii_columns: list[str],
        target_columns: list[str],
    ) -> dict[str, Any]:
        warnings: list[str] = []
        if row_count == 0:
            warnings.append("Dataset tidak memiliki baris.")
        if duplicate_count:
            warnings.append(f"Ditemukan {duplicate_count} baris duplikat.")
        high_missing = [name for name, item in columns.items() if item["missing_rate"] >= 0.2]
        if high_missing:
            warnings.append("Kolom dengan missing >=20%: " + ", ".join(high_missing))
        if pii_columns:
            warnings.append("Potensi PII: " + ", ".join(pii_columns))
        return {
            "rows": row_count,
            "column_count": len(schema),
            "schema": schema,
            "columns": columns,
            "duplicate_count": duplicate_count,
            "duplicate_rate": duplicate_count / row_count if row_count else 0.0,
            "date_range": date_range,
            "potential_identifier_columns": identifiers,
            "potential_target_columns": target_columns,
            "potential_pii_columns": pii_columns,
            "warnings": warnings,
        }
