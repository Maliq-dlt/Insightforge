from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

_JSON_FIELDS = {
    "schema_json",
    "profile_json",
    "plan_json",
    "result_json",
    "input_json",
    "output_json",
    "token_usage_json",
    "metadata_json",
    "details_json",
}


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class TraceStore:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS datasets (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    fingerprint TEXT NOT NULL UNIQUE,
                    schema_json TEXT NOT NULL,
                    profile_json TEXT NOT NULL,
                    storage_uri TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS analysis_sessions (
                    id TEXT PRIMARY KEY,
                    dataset_id TEXT NOT NULL REFERENCES datasets(id),
                    question TEXT NOT NULL,
                    mode TEXT NOT NULL CHECK (mode IN ('autonomous', 'approval', 'benchmark')),
                    status TEXT NOT NULL,
                    plan_json TEXT NOT NULL,
                    result_json TEXT,
                    final_answer TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    completed_at TEXT
                );

                CREATE TABLE IF NOT EXISTS execution_steps (
                    id TEXT PRIMARY KEY,
                    analysis_id TEXT NOT NULL REFERENCES analysis_sessions(id),
                    sequence INTEGER NOT NULL,
                    agent_name TEXT NOT NULL,
                    input_json TEXT NOT NULL,
                    output_json TEXT NOT NULL,
                    code TEXT,
                    latency_ms INTEGER NOT NULL,
                    token_usage_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE (analysis_id, sequence)
                );

                CREATE TABLE IF NOT EXISTS artifacts (
                    id TEXT PRIMARY KEY,
                    analysis_id TEXT NOT NULL REFERENCES analysis_sessions(id),
                    artifact_type TEXT NOT NULL,
                    storage_uri TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS evaluations (
                    id TEXT PRIMARY KEY,
                    analysis_id TEXT NOT NULL REFERENCES analysis_sessions(id),
                    evaluator TEXT NOT NULL,
                    score REAL NOT NULL,
                    details_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL CHECK (role IN ('viewer', 'analyst', 'admin')),
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS auth_tokens (
                    token_hash TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id),
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

    @staticmethod
    def _decode(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        result = dict(row)
        for field in _JSON_FIELDS & result.keys():
            value = result[field]
            result[field.removesuffix("_json")] = json.loads(value) if value else None
            del result[field]
        return result

    def get_user_by_username(self, username: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE username = ?", (username,)
            ).fetchone()
        return self._decode(row)

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return self._decode(row)

    def create_user(self, username: str, password_hash: str, role: str) -> dict[str, Any]:
        if role not in {"viewer", "analyst", "admin"}:
            raise ValueError("Role tidak didukung.")
        user_id = f"usr_{uuid4().hex[:12]}"
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO users (id, username, password_hash, role, created_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, username, password_hash, role, utc_now()),
            )
        user = self.get_user(user_id)
        assert user is not None
        return user

    def list_users(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, username, role, active, created_at FROM users ORDER BY created_at"
            ).fetchall()
        return [dict(row) for row in rows]

    def create_token(self, token_hash: str, user_id: str, expires_at: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO auth_tokens (token_hash, user_id, expires_at, created_at) VALUES (?, ?, ?, ?)",
                (token_hash, user_id, expires_at, utc_now()),
            )

    def get_user_by_token(self, token_hash: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT users.* FROM auth_tokens
                JOIN users ON users.id = auth_tokens.user_id
                WHERE auth_tokens.token_hash = ?
                  AND users.active = 1
                  AND auth_tokens.expires_at > ?
                """,
                (token_hash, utc_now()),
            ).fetchone()
        return self._decode(row)

    def revoke_token(self, token_hash: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM auth_tokens WHERE token_hash = ?", (token_hash,))

    def create_dataset(self, record: dict[str, Any]) -> dict[str, Any]:
        dataset_id = record.get("id", f"ds_{uuid4().hex[:12]}")
        created_at = utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO datasets (
                    id, name, fingerprint, schema_json, profile_json,
                    storage_uri, size_bytes, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    dataset_id,
                    record["name"],
                    record["fingerprint"],
                    json.dumps(record["schema"], default=str),
                    json.dumps(record["profile"], default=str),
                    record["storage_uri"],
                    record["size_bytes"],
                    created_at,
                ),
            )
        created = self.get_dataset(dataset_id)
        assert created is not None
        return created

    def find_dataset_by_fingerprint(self, fingerprint: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM datasets WHERE fingerprint = ?", (fingerprint,)
            ).fetchone()
        return self._decode(row)

    def get_dataset(self, dataset_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM datasets WHERE id = ?", (dataset_id,)).fetchone()
        return self._decode(row)

    def list_datasets(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM datasets ORDER BY created_at DESC").fetchall()
        return [decoded for row in rows if (decoded := self._decode(row)) is not None]

    def create_analysis(
        self,
        dataset_id: str,
        question: str,
        mode: str,
        status: str,
        plan: dict[str, Any],
    ) -> dict[str, Any]:
        analysis_id = f"an_{uuid4().hex[:12]}"
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO analysis_sessions (
                    id, dataset_id, question, mode, status, plan_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (analysis_id, dataset_id, question, mode, status, json.dumps(plan), utc_now()),
            )
        created = self.get_analysis(analysis_id)
        assert created is not None
        return created

    def update_analysis(self, analysis_id: str, **updates: Any) -> dict[str, Any]:
        allowed = {"status", "result_json", "final_answer", "error", "completed_at"}
        unknown = set(updates) - allowed
        if unknown:
            raise ValueError(f"Unsupported analysis fields: {sorted(unknown)}")
        assignments: list[str] = []
        values: list[Any] = []
        for field, value in updates.items():
            assignments.append(f"{field} = ?")
            values.append(json.dumps(value, default=str) if field == "result_json" else value)
        values.append(analysis_id)
        with self._connect() as connection:
            connection.execute(
                f"UPDATE analysis_sessions SET {', '.join(assignments)} WHERE id = ?", values
            )
        updated = self.get_analysis(analysis_id)
        if updated is None:
            raise KeyError(analysis_id)
        return updated

    def get_analysis(self, analysis_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM analysis_sessions WHERE id = ?", (analysis_id,)
            ).fetchone()
        return self._decode(row)

    def add_step(
        self,
        analysis_id: str,
        agent_name: str,
        input_data: dict[str, Any],
        output_data: dict[str, Any],
        latency_ms: int,
        status: str,
        code: str | None = None,
    ) -> dict[str, Any]:
        with self._connect() as connection:
            sequence = connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 FROM execution_steps WHERE analysis_id = ?",
                (analysis_id,),
            ).fetchone()[0]
            step_id = f"st_{uuid4().hex[:12]}"
            connection.execute(
                """
                INSERT INTO execution_steps (
                    id, analysis_id, sequence, agent_name, input_json, output_json,
                    code, latency_ms, token_usage_json, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    step_id,
                    analysis_id,
                    sequence,
                    agent_name,
                    json.dumps(input_data, default=str),
                    json.dumps(output_data, default=str),
                    code,
                    latency_ms,
                    "{}",
                    status,
                    utc_now(),
                ),
            )
            row = connection.execute(
                "SELECT * FROM execution_steps WHERE id = ?", (step_id,)
            ).fetchone()
        decoded = self._decode(row)
        assert decoded is not None
        return decoded

    def add_artifact(
        self,
        analysis_id: str,
        artifact_type: str,
        storage_uri: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        artifact_id = f"ar_{uuid4().hex[:12]}"
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO artifacts (
                    id, analysis_id, artifact_type, storage_uri, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact_id,
                    analysis_id,
                    artifact_type,
                    storage_uri,
                    json.dumps(metadata, default=str),
                    utc_now(),
                ),
            )
            row = connection.execute("SELECT * FROM artifacts WHERE id = ?", (artifact_id,)).fetchone()
        decoded = self._decode(row)
        assert decoded is not None
        return decoded

    def add_evaluation(
        self, analysis_id: str, evaluator: str, score: float, details: dict[str, Any]
    ) -> dict[str, Any]:
        evaluation_id = f"evl_{uuid4().hex[:12]}"
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO evaluations (
                    id, analysis_id, evaluator, score, details_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    evaluation_id,
                    analysis_id,
                    evaluator,
                    score,
                    json.dumps(details, default=str),
                    utc_now(),
                ),
            )
            row = connection.execute(
                "SELECT * FROM evaluations WHERE id = ?", (evaluation_id,)
            ).fetchone()
        decoded = self._decode(row)
        assert decoded is not None
        return decoded

    def trace(self, analysis_id: str) -> dict[str, Any] | None:
        analysis = self.get_analysis(analysis_id)
        if analysis is None:
            return None
        with self._connect() as connection:
            steps = connection.execute(
                "SELECT * FROM execution_steps WHERE analysis_id = ? ORDER BY sequence",
                (analysis_id,),
            ).fetchall()
            artifacts = connection.execute(
                "SELECT * FROM artifacts WHERE analysis_id = ? ORDER BY created_at",
                (analysis_id,),
            ).fetchall()
            evaluations = connection.execute(
                "SELECT * FROM evaluations WHERE analysis_id = ? ORDER BY created_at",
                (analysis_id,),
            ).fetchall()
        return {
            "analysis": analysis,
            "steps": [self._decode(row) for row in steps],
            "artifacts": [self._decode(row) for row in artifacts],
            "evaluations": [self._decode(row) for row in evaluations],
        }
