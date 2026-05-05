from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from typing import Any

from ._utils import int_value, snowflake_ge


class ReadStateMixin:
    def __init__(self) -> None:
        self._reset_state()
        self._load_read_states()
        super().__init__()

    def _reset_state(self) -> None:
        self.active_channel_id: str | None = None
        self.read_states: dict[str, dict[str, Any]] = {}
        self.session_start_id: str = str(int((time.time() * 1000) - 1420070400000) << 22)
        self.read_states_file = os.path.join(
            os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share")),
            "disports",
            "read_states.json",
        )
        if hasattr(super(), "_reset_state"):
            super()._reset_state()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load_read_states(self) -> None:
        try:
            if os.path.exists(self.read_states_file):
                with open(self.read_states_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        normalized = {}
                        for channel_id, entry in data.items():
                            normalized_id = str(channel_id or "")
                            if not normalized_id:
                                continue
                            normalized[normalized_id] = self._normalize_read_state_entry(entry)
                        self.read_states = normalized
        except Exception:
            self.read_states = {}

    def _save_read_states(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.read_states_file), exist_ok=True)
            with open(self.read_states_file, "w", encoding="utf-8") as f:
                json.dump(self.read_states, f)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Read-state helpers
    # ------------------------------------------------------------------

    def _normalize_read_state_entry(self, entry: Any) -> dict[str, Any]:
        if isinstance(entry, str):
            return {
                "last_message_id": entry,
                "badge_count": 0,
                "mention_count": 0,
            }
        if not isinstance(entry, dict):
            return {
                "last_message_id": "",
                "badge_count": 0,
                "mention_count": 0,
            }
        return {
            "last_message_id": str(entry.get("last_message_id", "") or ""),
            "badge_count": int_value(entry.get("badge_count")),
            "mention_count": int_value(entry.get("mention_count")),
        }

    def _read_state(self, channel_id: str) -> dict[str, Any]:
        return dict(self._normalize_read_state_entry(self.read_states.get(channel_id)))

    def _merge_ready_read_state(
        self,
        existing: dict[str, Any],
        incoming: dict[str, Any],
    ) -> dict[str, Any]:
        existing_last = str(existing.get("last_message_id", "") or "")
        incoming_last = str(incoming.get("last_message_id", "") or "")

        if snowflake_ge(incoming_last, existing_last):
            return {
                "last_message_id": incoming_last,
                "badge_count": int_value(incoming.get("badge_count")),
                "mention_count": int_value(incoming.get("mention_count")),
            }

        return {
            "last_message_id": existing_last,
            "badge_count": int_value(existing.get("badge_count")),
            "mention_count": int_value(existing.get("mention_count")),
        }

    # ------------------------------------------------------------------
    # Active channel
    # ------------------------------------------------------------------

    def set_active_channel(self, channel_id: str) -> None:
        self.active_channel_id = channel_id
        if channel_id:
            self.mark_channel_read(channel_id)

    # ------------------------------------------------------------------
    # Mark / query read state
    # ------------------------------------------------------------------

    def mark_channel_read(self, channel_id: str, message_id: str | None = None) -> None:
        if not channel_id:
            return
        state = self._read_state(channel_id)
        state["badge_count"] = 0
        state["mention_count"] = 0
        if message_id:
            state["last_message_id"] = str(message_id)
            self.read_states[channel_id] = state
            self._save_read_states()
        else:
            last_id = None
            for ch in self.private_channels:  # type: ignore[attr-defined]
                if ch.get("id") == channel_id:
                    last_id = ch.get("last_message_id")
                    break
            if not last_id:
                for channels in self.guild_channels.values():  # type: ignore[attr-defined]
                    for ch in channels:
                        if ch.get("id") == channel_id:
                            last_id = ch.get("last_message_id")
                            break
                    if last_id:
                        break
            if last_id:
                state["last_message_id"] = str(last_id)
            self.read_states[channel_id] = state
            self._save_read_states()

    def is_channel_unread(self, channel: dict[str, Any]) -> int:
        channel_id = channel.get("id")
        if not channel_id:
            return 0
        if channel_id == self.active_channel_id:
            return 0
        last_message_id = channel.get("last_message_id")
        if not last_message_id:
            return 0
        try:
            last_val = int(last_message_id)
            read_id = self._read_state(channel_id).get("last_message_id", "")
            read_val = int(read_id) if read_id else int(self.session_start_id)
            return 1 if last_val > read_val else 0
        except (ValueError, TypeError):
            return 0

    def channel_badge_count(self, channel: dict[str, Any]) -> int:
        channel_id = str(channel.get("id", "") or "")
        if not channel_id:
            return 0

        state = self._read_state(channel_id)
        if int(channel.get("type", -1)) in (1, 3):
            badge_count = int_value(state.get("badge_count"))
            if badge_count > 0:
                return badge_count
            return 1 if self.is_channel_unread(channel) else 0

        mention_count = int_value(state.get("mention_count"))
        if mention_count > 0:
            return mention_count
        return 0

    def channel_unread_kind(self, channel: dict[str, Any]) -> str:
        if not channel:
            return "none"
        count = self.channel_badge_count(channel)
        if count > 0:
            return "count"
        if int(channel.get("type", -1)) not in (1, 3) and self.is_channel_muted(channel):  # type: ignore[attr-defined]
            return "none"
        if self.is_channel_unread(channel):
            return "dot"
        return "none"

    # ------------------------------------------------------------------
    # Guild / DM unread aggregates
    # ------------------------------------------------------------------

    def get_dm_unread_count(self) -> int:
        count = 0
        for channel in self.private_channels:  # type: ignore[attr-defined]
            count += self.channel_badge_count(channel)
        return count

    def get_guild_mention_count(self, guild_id: str) -> int:
        count = 0
        for channel in self.iter_visible_guild_channels(guild_id):  # type: ignore[attr-defined]
            channel_id = str(channel.get("id", "") or "")
            if not channel_id:
                continue
            count += int_value(self._read_state(channel_id).get("mention_count"))
        return count

    def get_guild_unread_count(self, guild_id: str) -> int:
        mentions = self.get_guild_mention_count(guild_id)
        if mentions > 0:
            return mentions
        if self.is_guild_muted(guild_id):  # type: ignore[attr-defined]
            return 0
        count = 0
        for channel in self.iter_visible_guild_channels(guild_id):  # type: ignore[attr-defined]
            if self.is_channel_muted(channel):  # type: ignore[attr-defined]
                continue
            count += self.is_channel_unread(channel)
        return count

    def guild_has_unread(self, guild_id: str) -> bool:
        if self.is_guild_muted(guild_id) and self.get_guild_mention_count(guild_id) == 0:  # type: ignore[attr-defined]
            return False
        for channel in self.iter_visible_guild_channels(guild_id):  # type: ignore[attr-defined]
            if self.channel_unread_kind(channel) != "none":
                return True
        return False

    def guild_unread_kind(self, guild_id: str) -> str:
        if self.get_guild_mention_count(guild_id) > 0:
            return "count"
        if self.guild_has_unread(guild_id):
            return "dot"
        return "none"

    # ------------------------------------------------------------------
    # Activity handlers (gateway MESSAGE_CREATE)
    # ------------------------------------------------------------------

    def apply_private_channel_activity(self, message: dict[str, Any]) -> bool:
        channel_id = message.get("channel_id", "")
        if not channel_id:
            return False

        author_id = str((message.get("author") or {}).get("id", ""))
        is_own_message = author_id != "" and author_id == str((self.me or {}).get("id", ""))  # type: ignore[attr-defined]
        is_active = channel_id == self.active_channel_id

        channel = self.channel_by_id.get(channel_id)  # type: ignore[attr-defined]
        if channel not in self.private_channels:  # type: ignore[attr-defined]
            return False

        message_id = message.get("id")
        if message_id:
            channel["last_message_id"] = message_id

        state = self._read_state(channel_id)
        state["last_message_id"] = str(message_id or state.get("last_message_id", ""))

        if is_own_message or is_active:
            state["badge_count"] = 0
            state["mention_count"] = 0
        else:
            state["badge_count"] = max(0, int(state.get("badge_count") or 0)) + 1
            state["mention_count"] = 0

        self.read_states[channel_id] = state
        self._save_read_states()
        return True

    def apply_guild_channel_activity(self, message: dict[str, Any]) -> str | None:
        channel_id = message.get("channel_id", "")
        if not channel_id:
            return None
        author_id = str((message.get("author") or {}).get("id", ""))
        is_own_message = author_id != "" and author_id == str((self.me or {}).get("id", ""))  # type: ignore[attr-defined]
        is_active = channel_id == self.active_channel_id
        mentioned = self.message_mentions_me(message)  # type: ignore[attr-defined]
        guild_id = self.get_guild_for_channel(channel_id)  # type: ignore[attr-defined]
        channel = self.channel_by_id.get(channel_id)  # type: ignore[attr-defined]
        if not guild_id or not channel:
            return None
        message_id = message.get("id")
        if message_id:
            channel["last_message_id"] = message_id
        state = self._read_state(channel_id)
        state["last_message_id"] = str(message_id or state.get("last_message_id", ""))
        if is_own_message or is_active:
            state["mention_count"] = 0
        elif mentioned:
            state["mention_count"] = max(0, int(state.get("mention_count") or 0)) + 1
        self.read_states[channel_id] = state
        self._save_read_states()
        return guild_id

    # ------------------------------------------------------------------
    # Mute helpers
    # ------------------------------------------------------------------

    def _is_muted(self, raw: dict[str, Any] | None) -> bool:
        if not isinstance(raw, dict):
            return False
        if not raw.get("muted", False):
            return False
        cfg = raw.get("mute_config")
        if not isinstance(cfg, dict):
            return True
        selected = cfg.get("selected_time_window")
        if selected in (-1, None):
            return True
        end_time = cfg.get("end_time")
        if not isinstance(end_time, str) or end_time == "":
            return True
        try:
            end_dt = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
        except ValueError:
            return True
        return end_dt.astimezone(timezone.utc) > datetime.now(timezone.utc)

    def is_guild_muted(self, guild_id: str) -> bool:
        if not guild_id:
            return False
        return self._is_muted(self.guild_setting(guild_id))  # type: ignore[attr-defined]

    def is_channel_muted(self, channel: dict[str, Any], include_muted_categories: bool = False) -> bool:
        channel_id = str(channel.get("id", "") or "")
        if not channel_id:
            return False
        if self._is_muted(self.channel_override(channel_id)):  # type: ignore[attr-defined]
            return True
        parent_id = str(channel.get("parent_id", "") or "")
        if include_muted_categories or not parent_id:
            return False
        parent = self.get_channel(parent_id)  # type: ignore[attr-defined]
        if not parent:
            return False
        return self.is_channel_muted(parent, include_muted_categories)
