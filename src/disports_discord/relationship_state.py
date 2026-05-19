from __future__ import annotations

from typing import Any

RELATIONSHIP_FRIEND  = 1
RELATIONSHIP_BLOCKED = 2


class RelationshipStateMixin:
    def __init__(self) -> None:
        self._relationships: dict[str, int] = {}
        super().__init__()

    def _reset_state(self) -> None:
        self._relationships = {}
        if hasattr(super(), "_reset_state"):
            super()._reset_state()  # type: ignore[misc]

    def apply_relationships(self, relationships: list[dict[str, Any]]) -> None:
        self._relationships = {}
        for rel in relationships or []:
            user_id = str((rel.get("user") or {}).get("id") or rel.get("id") or "")
            rel_type = int(rel.get("type") or 0)
            if user_id and rel_type:
                self._relationships[user_id] = rel_type

    def apply_relationship_add(self, data: dict[str, Any]) -> None:
        user_id = str((data.get("user") or {}).get("id") or data.get("id") or "")
        rel_type = int(data.get("type") or 0)
        if user_id and rel_type:
            self._relationships[user_id] = rel_type

    def apply_relationship_remove(self, data: dict[str, Any]) -> None:
        user_id = str((data.get("user") or {}).get("id") or data.get("id") or "")
        self._relationships.pop(user_id, None)

    def relationship_type(self, user_id: str) -> int:
        return self._relationships.get(str(user_id or ""), 0)

    def is_blocked(self, user_id: str) -> bool:
        return self.relationship_type(user_id) == RELATIONSHIP_BLOCKED

    def is_friend(self, user_id: str) -> bool:
        return self.relationship_type(user_id) == RELATIONSHIP_FRIEND

    def message_notification_visibility(self, message: dict[str, Any]) -> str:
        author_id = str((message.get("author") or {}).get("id") or "")
        me_id = str((self.me or {}).get("id") or "")  # type: ignore[attr-defined]

        if author_id and author_id == me_id:
            return "show"

        if self.is_blocked(author_id):
            return getattr(self, "client_preferences", {}).get("blockedMessageVisibility", "reveal")

        return "show"
