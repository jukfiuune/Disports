from __future__ import annotations

import json
from typing import Any

from ._utils import merge_dict


class GuildStateMixin:
    def __init__(self) -> None:
        self._reset_state()
        super().__init__()

    def _reset_state(self) -> None:
        self.me: dict[str, Any] | None = None
        self.guilds: list[dict[str, Any]] = []
        self.guild_by_id: dict[str, dict[str, Any]] = {}
        self.private_channels: list[dict[str, Any]] = []
        self.guild_channels: dict[str, list[dict[str, Any]]] = {}
        self.channel_by_id: dict[str, dict[str, Any]] = {}
        self.guild_roles: dict[str, dict[str, int]] = {}
        self.guild_role_names: dict[str, dict[str, str]] = {}
        self.guild_members: dict[str, dict[str, Any]] = {}
        self.guild_details: dict[str, dict[str, Any]] = {}
        self.guild_emojis: dict[str, list[dict[str, Any]]] = {}
        self.users: dict[str, dict[str, Any]] = {}
        self.presences: dict[str, str] = {}
        self._user_settings_cache: dict[str, Any] = {}
        self.guild_positions_raw: list[str] = []
        self.guild_folders_raw: list[dict[str, Any]] = []
        self.user_guild_settings: dict[str, dict[str, Any]] = {}
        self.channel_overrides: dict[str, dict[str, Any]] = {}
        self.channel_to_guild: dict[str, str] = {}
        if hasattr(super(), "_reset_state"):
            super()._reset_state()
    # Reset
    def reset(self) -> None:
        self._reset_state()
    # Current user
    def set_me(self, me: dict[str, Any]) -> None:
        self.me = me
        self.cache_user(me)
    # User cache
    def cache_user(
        self,
        user: dict[str, Any] | None,
        member: dict[str, Any] | None = None,
        guild_id: str = "",
    ) -> dict[str, Any]:
        if not user:
            return {}
        user_id = str(user.get("id", "") or "")
        if not user_id:
            return {}
        cached = self.users.setdefault(user_id, {})
        merge_dict(cached, user)
        if member:
            cached_members = cached.setdefault("_members", {})
            normalized_guild_id = str(guild_id or member.get("guild_id", "") or "")
            cached_member = cached_members.setdefault(normalized_guild_id, {})
            if "nick" in member:
                cached_member["nick"] = member["nick"]
            merge_dict(cached_member, member)
            if normalized_guild_id:
                cached_member["guild_id"] = normalized_guild_id
        return cached
    # Guild layout helpers
    def guild_name(self, guild_id: str) -> str:
        if not guild_id:
            return ""
        guild = self.guild_by_id.get(guild_id)
        if guild:
            return str(guild.get("name", "") or "")
        return str((self.guild_details.get(guild_id) or {}).get("name", "") or "")

    def guild_setting(self, guild_id: str) -> dict[str, Any]:
        return dict(self.user_guild_settings.get(guild_id, {}))

    def channel_override(self, channel_id: str) -> dict[str, Any]:
        return dict(self.channel_overrides.get(channel_id, {}))

    def _normalize_guild_folders_value(self, raw: Any) -> list[dict[str, Any]]:
        if raw is None:
            return []
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return []
        if not isinstance(raw, list):
            return []
        return [x for x in raw if isinstance(x, dict)]

    def _sync_guild_layout_from_user_settings(self) -> None:
        positions = self._user_settings_cache.get("guild_positions")
        if isinstance(positions, str):
            try:
                positions = json.loads(positions)
            except (json.JSONDecodeError, TypeError):
                positions = []
        self.guild_positions_raw = [str(x) for x in (positions or []) if x is not None]
        self.guild_folders_raw = self._normalize_guild_folders_value(
            self._user_settings_cache.get("guild_folders")
        )

    def _sync_notification_settings(self, raw: Any) -> None:
        guilds: dict[str, dict[str, Any]] = {}
        overrides: dict[str, dict[str, Any]] = {}

        entries: list[dict[str, Any]] = []
        if isinstance(raw, list):
            entries = [x for x in raw if isinstance(x, dict)]
        elif isinstance(raw, dict):
            if isinstance(raw.get("entries"), list):
                entries = [x for x in raw.get("entries") if isinstance(x, dict)]
            elif raw.get("guild_id") is not None:
                entries = [raw]
            else:
                vals = [x for x in raw.values() if isinstance(x, dict)]
                if vals:
                    entries = vals

        for entry in entries:
            guild_id = str(entry.get("guild_id", "") or "")
            if not guild_id:
                continue
            guilds[guild_id] = dict(entry)
            for override in entry.get("channel_overrides", []) or []:
                if not isinstance(override, dict):
                    continue
                channel_id = str(override.get("channel_id", "") or "")
                if channel_id:
                    overrides[channel_id] = dict(override)

        self.user_guild_settings = guilds
        self.channel_overrides = overrides

    def merge_user_settings_gateway_update(self, data: dict[str, Any]) -> bool:
        if not isinstance(data, dict):
            return False
        changed = False
        if "guild_positions" in data:
            self._user_settings_cache["guild_positions"] = data["guild_positions"]
            changed = True
        if "guild_folders" in data:
            self._user_settings_cache["guild_folders"] = data["guild_folders"]
            changed = True
        if changed:
            self._sync_guild_layout_from_user_settings()
        return changed

    def merge_user_guild_settings_update(self, data: dict[str, Any]) -> bool:
        if not isinstance(data, dict):
            return False
        guild_id = str(data.get("guild_id", "") or "")
        if not guild_id:
            return False
        self.user_guild_settings[guild_id] = dict(data)
        for override in data.get("channel_overrides", []) or []:
            if not isinstance(override, dict):
                continue
            channel_id = str(override.get("channel_id", "") or "")
            if channel_id:
                self.channel_overrides[channel_id] = dict(override)
        return True
    # READY payload
    def apply_ready(self, payload: dict[str, Any]) -> None:
        self._reset_state()
        user = payload.get("user")
        if user:
            self.set_me(user)

        self.guilds = payload.get("guilds", []) or []
        self.guild_by_id = {
            str(guild.get("id", "") or ""): guild
            for guild in self.guilds
            if isinstance(guild, dict) and str(guild.get("id", "") or "")
        }
        self.private_channels = payload.get("private_channels", []) or []
        self._index_private_channels()

        rs_data = payload.get("read_state")
        entries = []
        if isinstance(rs_data, dict) and "entries" in rs_data:
            entries = rs_data["entries"]
        elif isinstance(rs_data, list):
            entries = rs_data

        for rs in entries:
            c_id = str(rs.get("id", ""))
            if not c_id:
                continue
            incoming = self._normalize_read_state_entry(rs)  # type: ignore[attr-defined]
            existing = self._read_state(c_id)  # type: ignore[attr-defined]
            self.read_states[c_id] = self._merge_ready_read_state(existing, incoming)  # type: ignore[attr-defined]
        if entries:
            self._save_read_states()  # type: ignore[attr-defined]

        for presence in payload.get("presences", []) or []:
            self.apply_presence(presence)

        for channel in self.private_channels:
            for recipient in channel.get("recipients", []) or []:
                self.cache_user(recipient)

        us = payload.get("user_settings")
        self._user_settings_cache = dict(us) if isinstance(us, dict) else {}
        self._sync_guild_layout_from_user_settings()
        self._sync_notification_settings(payload.get("user_guild_settings"))

        for guild in self.guilds:
            guild_id = str(guild.get("id", "") or "")
            channels = guild.get("channels") or []
            member_data = guild.get("member")
            if not member_data and isinstance(guild.get("members"), list):
                me_id = str((self.me or {}).get("id", "") or "")
                for member in guild.get("members") or []:
                    user_id = str(((member or {}).get("user") or {}).get("id", "") or "")
                    if me_id and user_id == me_id:
                        member_data = member
                        break
            if guild_id:
                self.set_guild_context(guild_id, guild, member_data if isinstance(member_data, dict) else None)
            if guild_id and channels:
                if guild_id not in self.guild_channels:
                    self.set_guild_channels(guild_id, channels)

    def apply_presence(self, payload: dict[str, Any]) -> None:
        user = payload.get("user") or {}
        user_id = user.get("id")
        if user_id:
            self.presences[user_id] = payload.get("status", "offline")
    # Guild channels
    def set_guild_channels(self, guild_id: str, channels: list[dict[str, Any]]) -> None:
        for old_channel in self.guild_channels.get(guild_id, []):
            old_id = str(old_channel.get("id", "") or "")
            if old_id and self.channel_to_guild.get(old_id) == guild_id:
                self.channel_to_guild.pop(old_id, None)
                if self.channel_by_id.get(old_id) is old_channel:
                    self.channel_by_id.pop(old_id, None)
        self.guild_channels[guild_id] = channels
        for ch in channels:
            ch_id = str(ch.get("id", "") or "")
            if ch_id:
                self.channel_to_guild[ch_id] = guild_id
                self.channel_by_id[ch_id] = ch

    def _index_private_channels(self) -> None:
        for channel in self.private_channels:
            channel_id = str(channel.get("id", "") or "")
            if channel_id:
                self.channel_by_id[channel_id] = channel

    def upsert_guild_channel(self, channel: dict[str, Any]) -> str | None:
        if not isinstance(channel, dict):
            return None
        channel_id = str(channel.get("id", "") or "")
        if not channel_id:
            return None
        guild_id = str(channel.get("guild_id", "") or "") or self.get_guild_for_channel(channel_id) or ""
        if not guild_id:
            return None
        channels = list(self.guild_channels.get(guild_id, []))
        replaced = False
        for index, existing in enumerate(channels):
            if str(existing.get("id", "") or "") == channel_id:
                channels[index] = channel
                replaced = True
                break
        if not replaced:
            channels.append(channel)
        self.set_guild_channels(guild_id, channels)
        return guild_id

    def remove_guild_channel(self, channel_id: str, guild_id: str = "") -> str | None:
        resolved_guild_id = guild_id or self.get_guild_for_channel(channel_id) or ""
        if not resolved_guild_id:
            return None
        channels = [
            channel
            for channel in self.guild_channels.get(resolved_guild_id, [])
            if str(channel.get("id", "") or "") != channel_id
        ]
        self.guild_channels[resolved_guild_id] = channels
        self.channel_to_guild.pop(channel_id, None)
        self.channel_by_id.pop(channel_id, None)
        return resolved_guild_id

    def get_guild_for_channel(self, channel_id: str) -> str | None:
        if not channel_id:
            return None
        if channel_id in self.channel_to_guild:
            return self.channel_to_guild[channel_id]
        for guild_id, channels in self.guild_channels.items():
            for channel in channels:
                if channel.get("id") == channel_id:
                    self.channel_to_guild[channel_id] = guild_id
                    return guild_id
        return None

    def get_channel(self, channel_id: str) -> dict[str, Any] | None:
        if not channel_id:
            return None
        return self.channel_by_id.get(channel_id)
    # Guild context (roles, members, emojis)
    def set_guild_emojis(self, guild_id: str, emojis: list[dict[str, Any]]) -> None:
        self.guild_emojis[guild_id] = [dict(emoji) for emoji in (emojis or []) if isinstance(emoji, dict)]

    def set_guild_context(
        self,
        guild_id: str,
        guild_data: dict[str, Any] | None,
        member_data: dict[str, Any] | None,
    ) -> None:
        if guild_data:
            cached_guild = self.guild_details.setdefault(guild_id, {})
            merge_dict(cached_guild, guild_data)
            if guild_id in self.guild_by_id:
                merge_dict(self.guild_by_id[guild_id], guild_data)
        roles: dict[str, int] = {}
        role_names: dict[str, str] = {}
        for role in (guild_data or {}).get("roles", []) or []:
            role_id = role.get("id")
            if not role_id:
                continue
            role_id = str(role_id)
            try:
                roles[role_id] = int(role.get("permissions") or 0)
            except (TypeError, ValueError):
                roles[role_id] = 0
            role_names[role_id] = str(role.get("name", "") or "")
        if roles:
            self.guild_roles[guild_id] = roles
        if role_names:
            self.guild_role_names[guild_id] = role_names
        if member_data:
            self.guild_members[guild_id] = member_data
            if isinstance(member_data.get("user"), dict):
                self.cache_user(member_data.get("user") or {}, member_data, guild_id=guild_id)
        if guild_data and isinstance(guild_data.get("emojis"), list):
            self.set_guild_emojis(guild_id, guild_data.get("emojis") or [])

    def apply_guild_members_chunk(self, payload: dict[str, Any]) -> str:
        guild_id = str(payload.get("guild_id", "") or "")
        if not guild_id:
            return ""
        for member in payload.get("members", []) or []:
            if not isinstance(member, dict):
                continue
            user = member.get("user") or {}
            if not isinstance(user, dict):
                continue
            self.cache_user(user, member, guild_id=guild_id)
        for presence in payload.get("presences", []) or []:
            if isinstance(presence, dict):
                self.apply_presence(presence)
        return guild_id
    # Member helpers
    def guild_member_for_user(self, user: dict[str, Any] | None, guild_id: str = "") -> dict[str, Any]:
        if not user:
            return {}
        members = user.get("_members") or {}
        if guild_id and isinstance(members, dict):
            member = members.get(guild_id)
            if isinstance(member, dict):
                return member
        fallback = members.get("") if isinstance(members, dict) else None
        return fallback if isinstance(fallback, dict) else {}

    def has_guild_member(self, guild_id: str, user_id: str) -> bool:
        if not guild_id or not user_id:
            return False
        user = self.users.get(str(user_id))
        if not user:
            return False
        return bool(self.guild_member_for_user(user, guild_id))

    def message_display_name(
        self,
        user: dict[str, Any] | None,
        guild_id: str = "",
        member: dict[str, Any] | None = None,
    ) -> str:
        if not user:
            return ""
        guild_member = dict(self.guild_member_for_user(user, guild_id))
        if member:
            if "nick" in member:
                guild_member["nick"] = member["nick"]
            merge_dict(guild_member, member)
        return (
            guild_member.get("nick")
            or user.get("global_name")
            or user.get("username")
            or ""
        )

