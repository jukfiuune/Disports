from __future__ import annotations

from functools import lru_cache
from typing import Any

from .emoji_cldr_order import EMOJI_CLDR_ORDER


@lru_cache(maxsize=1)
def unicode_emoji_catalog() -> tuple[dict[str, Any], ...]:
    """Return emoji in Unicode CLDR keyboard order, grouped for the picker."""
    return tuple(
        {
            "char": emoji,
            "name": label.replace(" ", "_"),
            "label": label,
            "category": category,
        }
        for emoji, category, label in EMOJI_CLDR_ORDER
    )
