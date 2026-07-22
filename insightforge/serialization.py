from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any


def json_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bytes):
        return value.hex()
    return value


def json_row(columns: list[str], row: tuple[Any, ...]) -> dict[str, Any]:
    return {column: json_value(value) for column, value in zip(columns, row, strict=True)}
