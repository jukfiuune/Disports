from __future__ import annotations

from typing import Any


def merge_dict(target: dict[str, Any], source: dict[str, Any]) -> None:
    for key, value in source.items():
        if value is None:
            continue
        if isinstance(value, str) and value == "":
            continue
        target[key] = value


def int_value(raw_value: Any) -> int:
    try:
        return max(0, int(raw_value or 0))
    except (TypeError, ValueError):
        return 0


def snowflake_ge(lhs: str, rhs: str) -> bool:
    if not lhs:
        return False
    if not rhs:
        return True
    try:
        return int(lhs) >= int(rhs)
    except (TypeError, ValueError):
        return lhs >= rhs


def last_message_sort_value(last_message_id: str | None) -> int:
    if not last_message_id:
        return 0
    try:
        return int(last_message_id)
    except (TypeError, ValueError):
        return 0


def message_type_value(raw_value: Any) -> int:
    try:
        return int(raw_value or 0)
    except (TypeError, ValueError):
        return 0
