from __future__ import annotations

from typing import Any


class ReactionsMixin:
    def __init__(self) -> None:
        self._reset_state()
        super().__init__()

    def _reset_state(self) -> None:
        self._reaction_cache: dict[str, list[dict[str, Any]]] = {}
        if hasattr(super(), "_reset_state"):
            super()._reset_state()

    # ------------------------------------------------------------------
    # Emoji string helper
    # ------------------------------------------------------------------

    @staticmethod
    def _emoji_api_string(emoji: dict[str, Any]) -> str:
        """Return the Discord API emoji string for use in URLs (name or name:id)."""
        name = str(emoji.get("name") or "")
        emoji_id = str(emoji.get("id") or "")
        if emoji_id and emoji_id != "None":
            return f"{name}:{emoji_id}"
        return name

    # ------------------------------------------------------------------
    # Format
    # ------------------------------------------------------------------

    def format_reactions(self, raw_reactions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result = []
        for r in (raw_reactions or []):
            if not isinstance(r, dict):
                continue
            emoji = r.get("emoji") or {}
            emoji_id = str(emoji.get("id") or "")
            animated = bool(emoji.get("animated", False))
            emoji_name = str(emoji.get("name") or "")
            api_string = self._emoji_api_string(emoji)
            is_custom = bool(emoji_id and emoji_id != "None")
            emoji_url = self.guild_emoji_url(emoji_id, animated) if is_custom else ""  # type: ignore[attr-defined]
            result.append({
                "emojiName": emoji_name,
                "emojiId": emoji_id if is_custom else "",
                "emojiUrl": emoji_url,
                "isCustom": is_custom,
                "animated": animated,
                "count": int(r.get("count") or 0),
                "me": bool(r.get("me", False)),
                "apiString": api_string,
            })
        return result

    # ------------------------------------------------------------------
    # Gateway updates
    # ------------------------------------------------------------------

    def update_message_reactions(
        self,
        message_id: str,
        event_type: str,
        event_data: dict[str, Any],
        my_user_id: str = "",
    ) -> list[dict[str, Any]] | None:
        """Patch the reaction cache in response to a gateway reaction event.

        Returns the updated formatted reaction list, or None if the message
        isn't in the cache.
        """
        if not message_id:
            return None

        cached = self._reaction_cache.get(message_id)

        if event_type == "MESSAGE_REACTION_REMOVE_ALL":
            self._reaction_cache[message_id] = []
            return []

        if cached is None:
            return None

        emoji_data = event_data.get("emoji") or {}
        api_str = self._emoji_api_string(emoji_data)
        user_id = str(event_data.get("user_id") or "")
        is_me = bool(my_user_id and user_id == my_user_id)

        if event_type == "MESSAGE_REACTION_REMOVE_EMOJI":
            self._reaction_cache[message_id] = [
                r for r in cached
                if self._emoji_api_string(r.get("emoji") or {}) != api_str
            ]
            return self.format_reactions(self._reaction_cache[message_id])

        found_idx = -1
        for i, r in enumerate(cached):
            if self._emoji_api_string(r.get("emoji") or {}) == api_str:
                found_idx = i
                break

        if event_type == "MESSAGE_REACTION_ADD":
            if found_idx == -1:
                cached.append({
                    "emoji": dict(emoji_data),
                    "count": 1,
                    "me": is_me,
                })
            else:
                entry = dict(cached[found_idx])
                entry["count"] = max(0, int(entry.get("count") or 0)) + 1
                if is_me:
                    entry["me"] = True
                cached[found_idx] = entry
        elif event_type == "MESSAGE_REACTION_REMOVE":
            if found_idx != -1:
                entry = dict(cached[found_idx])
                entry["count"] = max(0, int(entry.get("count") or 0) - 1)
                if is_me:
                    entry["me"] = False
                if entry["count"] <= 0:
                    cached.pop(found_idx)
                else:
                    cached[found_idx] = entry

        self._reaction_cache[message_id] = cached
        return self.format_reactions(cached)
