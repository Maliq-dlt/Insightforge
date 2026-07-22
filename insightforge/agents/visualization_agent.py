from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class VisualizationAgent:
    def build(self, evidence: list[dict[str, Any]]) -> dict[str, Any] | None:
        for item in evidence:
            rows = item.get("rows", [])
            if len(rows) < 2:
                continue
            if item.get("key") == "segment_contribution":
                x_key, y_key = "segment", "delta"
            elif item.get("key") == "missing_values":
                x_key, y_key = "column", "missing_rate"
            elif "segment" in rows[0] and "metric_value" in rows[0]:
                x_key, y_key = "segment", "metric_value"
            elif "month" in rows[0] and "metric_value" in rows[0]:
                x_key, y_key = "month", "metric_value"
            else:
                continue
            points = [{"x": row.get(x_key), "y": row.get(y_key)} for row in rows[:10]]
            return {
                "type": "bar",
                "x": x_key,
                "y": y_key,
                "points": points,
                "alt_text": f"Bar chart {y_key} berdasarkan {x_key}; sumber {item.get('key')}.",
                "evidence_key": item.get("key"),
            }
        return None

    @staticmethod
    def save(spec: dict[str, Any], artifact_dir: Path, analysis_id: str) -> Path:
        path = artifact_dir / f"{analysis_id}_chart.json"
        path.write_text(json.dumps(spec, indent=2, ensure_ascii=False), encoding="utf-8")
        return path
