from __future__ import annotations

import csv
import re
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from pathlib import Path
from typing import Any

try:
    import duckdb
except ImportError:  # local fallback; production dependency remains DuckDB
    duckdb = None  # type: ignore[assignment]

from insightforge.config import Settings
from insightforge.serialization import json_row


class SQLSafetyError(ValueError):
    pass


class SQLTimeoutError(TimeoutError):
    pass


_FORBIDDEN_SQL = (
    "insert",
    "update",
    "delete",
    "drop",
    "alter",
    "create",
    "replace",
    "truncate",
    "merge",
    "copy",
    "export",
    "import",
    "attach",
    "detach",
    "install",
    "load",
    "pragma",
    "call",
)
_FORBIDDEN_FUNCTIONS = ("read_csv", "read_parquet", "httpfs", "sqlite_scan", "parquet_scan")


def quote_identifier(identifier: str) -> str:
    if not identifier or "\x00" in identifier:
        raise SQLSafetyError("Identifier tidak valid.")
    return '"' + identifier.replace('"', '""') + '"'


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def validate_read_only_sql(sql: str) -> str:
    normalized = sql.strip()
    if not normalized:
        raise SQLSafetyError("Query kosong.")
    normalized = normalized.rstrip(";").strip()
    if ";" in normalized:
        raise SQLSafetyError("Hanya satu statement SQL yang diizinkan.")
    if not re.match(r"^(select|with)\b", normalized, re.IGNORECASE):
        raise SQLSafetyError("Hanya SELECT atau WITH yang diizinkan.")
    if "--" in normalized or "/*" in normalized or "*/" in normalized:
        raise SQLSafetyError("Komentar SQL tidak diizinkan.")
    lowered = normalized.lower()
    if any(re.search(rf"\b{keyword}\b", lowered) for keyword in _FORBIDDEN_SQL):
        raise SQLSafetyError("Query mengandung operasi mutasi atau akses berbahaya.")
    if any(function_name in lowered for function_name in _FORBIDDEN_FUNCTIONS):
        raise SQLSafetyError("Akses file atau network dari query tidak diizinkan.")
    return normalized


def source_sql(dataset_path: Path) -> str:
    path = dataset_path.resolve().as_posix()
    if dataset_path.suffix.lower() == ".csv":
        return f"read_csv_auto({sql_literal(path)}, header=true, delim=',', strict_mode=false, sample_size=-1)"
    if dataset_path.suffix.lower() == ".parquet":
        return f"read_parquet({sql_literal(path)})"
    raise ValueError("Format dataset tidak didukung.")


def _sqlite_value(value: str) -> int | float | str | None:
    if value == "":
        return None
    try:
        return int(value)
    except ValueError:
        try:
            return float(value)
        except ValueError:
            return value


def _sqlite_dataset(path: Path) -> sqlite3.Connection:
    if path.suffix.lower() != ".csv":
        raise RuntimeError("Fallback SQLite hanya mendukung CSV; install DuckDB untuk Parquet.")
    connection = sqlite3.connect(":memory:")
    with path.open(newline="", encoding="utf-8-sig") as file_handle:
        reader = csv.DictReader(file_handle)
        fields = reader.fieldnames or []
        if not fields:
            raise ValueError("CSV tidak memiliki header.")
        definitions = ", ".join(f"{quote_identifier(field)} TEXT" for field in fields)
        connection.execute(f"CREATE TABLE dataset ({definitions})")
        connection.executemany(
            f"INSERT INTO dataset VALUES ({', '.join('?' for _ in fields)})",
            [[_sqlite_value(row.get(field, "")) for field in fields] for row in reader],
        )
    return connection


class SQLExecutor:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def execute(self, dataset_path: Path, sql: str) -> dict[str, Any]:
        query = validate_read_only_sql(sql)
        if duckdb is None:
            return self._execute_sqlite(dataset_path, query)
        connection = duckdb.connect(database=":memory:")
        try:
            connection.execute(
                f"SET memory_limit = {sql_literal(f'{self.settings.sql_memory_limit_mb}MB')}"
            )
            connection.execute("SET threads = 1")
            connection.execute(f"CREATE TEMP TABLE dataset AS SELECT * FROM {source_sql(dataset_path)}")
            try:
                connection.execute("SET enable_external_access = false")
            except duckdb.Error:
                pass
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(self._fetch_duckdb, connection, query)
                try:
                    return future.result(timeout=self.settings.sql_timeout_seconds)
                except FutureTimeoutError as error:
                    connection.interrupt()
                    try:
                        future.result(timeout=2)
                    except Exception:
                        pass
                    raise SQLTimeoutError(
                        f"Query melebihi timeout {self.settings.sql_timeout_seconds} detik."
                    ) from error
        finally:
            connection.close()

    def _fetch_duckdb(self, connection: Any, query: str) -> dict[str, Any]:
        connection.execute(f"EXPLAIN {query}")
        limited_query = (
            f"SELECT * FROM ({query}) AS insightforge_result LIMIT {self.settings.sql_max_rows}"
        )
        result = connection.execute(limited_query)
        columns = [item[0] for item in result.description]
        rows = [json_row(columns, tuple(row)) for row in result.fetchall()]
        return {
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
            "truncated": len(rows) >= self.settings.sql_max_rows,
            "sql": query,
            "engine": "duckdb",
        }

    def _execute_sqlite(self, dataset_path: Path, query: str) -> dict[str, Any]:
        connection = _sqlite_dataset(dataset_path)
        deadline = time.monotonic() + self.settings.sql_timeout_seconds
        connection.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
        try:
            sqlite_query = re.sub(
                r'EXTRACT\s*\(\s*MONTH\s+FROM\s+("[^"\n]+"|[A-Za-z_][A-Za-z0-9_]*)\s*\)',
                r"CAST(strftime('%m', \1) AS INTEGER)",
                query,
                flags=re.IGNORECASE,
            )
            connection.execute(f"EXPLAIN QUERY PLAN {sqlite_query}")
            result = connection.execute(
                f"SELECT * FROM ({sqlite_query}) AS insightforge_result "
                f"LIMIT {self.settings.sql_max_rows}"
            )
            columns = [item[0] for item in result.description]
            rows = [json_row(columns, tuple(row)) for row in result.fetchall()]
            return {
                "columns": columns,
                "rows": rows,
                "row_count": len(rows),
                "truncated": len(rows) >= self.settings.sql_max_rows,
                "sql": query,
                "engine": "sqlite-fallback",
            }
        except sqlite3.OperationalError as error:
            if time.monotonic() > deadline:
                raise SQLTimeoutError(
                    f"Query melebihi timeout {self.settings.sql_timeout_seconds} detik."
                ) from error
            raise
        finally:
            connection.set_progress_handler(None, 0)
            connection.close()
