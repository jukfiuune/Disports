from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


MENTION_RE = re.compile(r"<@!?(\d+)>")
ROLE_MENTION_RE = re.compile(r"<@&(\d+)>")
CHANNEL_MENTION_RE = re.compile(r"<#(\d+)>")
CUSTOM_EMOJI_RE = re.compile(r"<(a?):([A-Za-z0-9_~\-]+):(\d+)>")
DISCORD_TOKEN_RE = re.compile(
    r"(?P<url>https?://[^\s]+)"
    r"|<(?P<emoji_anim>a?):(?P<emoji_name>[A-Za-z0-9_~\-]+):(?P<emoji_id>\d+)>"
    r"|<@!?(?P<user_id>\d+)>"
    r"|<@&(?P<role_id>\d+)>"
    r"|<#(?P<channel_id>\d+)>"
)


class DiscordState:
    ADMINISTRATOR_PERMISSION = 1 << 3
    VIEW_CHANNEL_PERMISSION = 1 << 10
    CONNECT_PERMISSION = 1 << 20
    MESSAGE_TYPE_NAMES = {
        0: "Default",
        1: "RecipientAdd",
        2: "RecipientRemove",
        3: "Call",
        4: "ChannelNameChange",
        5: "ChannelIconChange",
        6: "ChannelPinnedMessage",
        7: "GuildMemberJoin",
        8: "UserPremiumGuildSubscription",
        9: "TierOneUserPremiumGuildSubscription",
        10: "TierTwoUserPremiumGuildSubscription",
        11: "TierThreeUserPremiumGuildSubscription",
        12: "ChannelFollowAdd",
        14: "GuildDiscoveryDisqualified",
        15: "GuildDiscoveryRequalified",
        16: "GuildDiscoveryGracePeriodInitialWarning",
        17: "GuildDiscoveryGracePeriodFinalWarning",
        18: "ThreadCreated",
        19: "Reply",
        20: "ApplicationCommand",
        21: "ThreadStarterMessage",
        22: "GuildInviteReminder",
        23: "ContextMenuCommand",
        24: "AutoModAlert",
        25: "RoleSubscriptionPurchase",
        26: "InteractionPremiumUpsell",
        27: "StageStart",
        28: "StageEnd",
        29: "StageSpeaker",
        30: "StageRaiseHand",
        31: "StageTopic",
        32: "GuildApplicationPremiumSubscription",
        35: "PremiumReferral",
        36: "GuildIncidentAlertModeEnabled",
        37: "GuildIncidentAlertModeDisabled",
        38: "GuildIncidentReportRaid",
        39: "GuildIncidentReportFalseAlarm",
        44: "PurchaseNotification",
        46: "PollResult",
    }

    def __init__(self) -> None:
        self.me: dict[str, Any] | None = None
        self.guilds: list[dict[str, Any]] = []
        self.private_channels: list[dict[str, Any]] = []
        self.guild_channels: dict[str, list[dict[str, Any]]] = {}
        self.guild_roles: dict[str, dict[str, int]] = {}
        self.guild_role_names: dict[str, dict[str, str]] = {}
        self.guild_members: dict[str, dict[str, Any]] = {}
        self.guild_details: dict[str, dict[str, Any]] = {}
        self.guild_emojis: dict[str, list[dict[str, Any]]] = {}
        self.users: dict[str, dict[str, Any]] = {}
        self.presences: dict[str, str] = {}
        self.active_channel_id: str | None = None
        self.read_states: dict[str, dict[str, Any]] = {}
        self.session_start_id: str = str(int((time.time() * 1000) - 1420070400000) << 22)
        self.read_states_file = os.path.join(
            os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share")),
            "disports",
            "read_states.json",
        )
        self._load_read_states()
        self._user_settings_cache: dict[str, Any] = {}
        self.guild_positions_raw: list[str] = []
        self.guild_folders_raw: list[dict[str, Any]] = []
        self.user_guild_settings: dict[str, dict[str, Any]] = {}
        self.channel_overrides: dict[str, dict[str, Any]] = {}
        self.channel_to_guild: dict[str, str] = {}

    def guild_name(self, guild_id: str) -> str:
        if not guild_id:
            return ""
        for guild in self.guilds:
            if str(guild.get("id", "") or "") == guild_id:
                return str(guild.get("name", "") or "")
        return str((self.guild_details.get(guild_id) or {}).get("name", "") or "")

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

    @staticmethod
    def _folder_color_hex(color_val: Any) -> str:
        try:
            c = int(color_val)
        except (TypeError, ValueError):
            return ""
        if c <= 0:
            return ""
        rgb = c & 0xFFFFFF
        return f"#{rgb:06x}"

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

    def set_active_channel(self, channel_id: str) -> None:
        self.active_channel_id = channel_id
        if channel_id:
            self.mark_channel_read(channel_id)

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
            for ch in self.private_channels:
                if ch.get("id") == channel_id:
                    last_id = ch.get("last_message_id")
                    break
            if not last_id:
                for channels in self.guild_channels.values():
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

    def guild_setting(self, guild_id: str) -> dict[str, Any]:
        return dict(self.user_guild_settings.get(guild_id, {}))

    def channel_override(self, channel_id: str) -> dict[str, Any]:
        return dict(self.channel_overrides.get(channel_id, {}))

    def is_guild_muted(self, guild_id: str) -> bool:
        if not guild_id:
            return False
        return self._is_muted(self.guild_setting(guild_id))

    def is_channel_muted(self, channel: dict[str, Any], include_muted_categories: bool = False) -> bool:
        channel_id = str(channel.get("id", "") or "")
        if not channel_id:
            return False
        if self._is_muted(self.channel_override(channel_id)):
            return True
        parent_id = str(channel.get("parent_id", "") or "")
        if include_muted_categories or not parent_id:
            return False
        parent = self.get_channel(parent_id)
        if not parent:
            return False
        return self.is_channel_muted(parent, include_muted_categories)

    def reset(self) -> None:
        self.__init__()

    def set_me(self, me: dict[str, Any]) -> None:
        self.me = me
        self.cache_user(me)

    def apply_ready(self, payload: dict[str, Any]) -> None:
        user = payload.get("user")
        if user:
            self.set_me(user)

        self.guilds = payload.get("guilds", []) or []
        self.private_channels = payload.get("private_channels", []) or []

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
            incoming = self._normalize_read_state_entry(rs)
            existing = self._read_state(c_id)
            self.read_states[c_id] = self._merge_ready_read_state(existing, incoming)
        if entries:
            self._save_read_states()

        for presence in payload.get("presences", []) or []:
            self.apply_presence(presence)

        for channel in self.private_channels:
            for recipient in channel.get("recipients", []) or []:
                self.cache_user(recipient)

        us = payload.get("user_settings")
        self._user_settings_cache = dict(us) if isinstance(us, dict) else {}
        self._sync_guild_layout_from_user_settings()
        self._sync_notification_settings(payload.get("user_guild_settings"))

        # Discord includes a 'channels' list inside each guild object in the
        # READY payload.  Store them so unread counts work before the user
        # ever taps into a server.
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
                    self.guild_channels[guild_id] = channels
                for ch in channels:
                    ch_id = str(ch.get("id", "") or "")
                    if ch_id:
                        self.channel_to_guild[ch_id] = guild_id

    def apply_presence(self, payload: dict[str, Any]) -> None:
        user = payload.get("user") or {}
        user_id = user.get("id")
        if user_id:
            self.presences[user_id] = payload.get("status", "offline")

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
        self._merge_dict(cached, user)
        if member:
            cached_members = cached.setdefault("_members", {})
            normalized_guild_id = str(guild_id or member.get("guild_id", "") or "")
            cached_member = cached_members.setdefault(normalized_guild_id, {})
            # nick=None is meaningful: it means "no server nickname".
            # _merge_dict skips None, so we must write it explicitly first
            # so that a cleared nickname doesn't stay stuck in cache.
            if "nick" in member:
                cached_member["nick"] = member["nick"]  # may be None
            self._merge_dict(cached_member, member)
            if normalized_guild_id:
                cached_member["guild_id"] = normalized_guild_id
        return cached

    def set_guild_channels(self, guild_id: str, channels: list[dict[str, Any]]) -> None:
        self.guild_channels[guild_id] = channels
        for ch in channels:
            ch_id = str(ch.get("id", "") or "")
            if ch_id:
                self.channel_to_guild[ch_id] = guild_id

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
        return resolved_guild_id

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
            self._merge_dict(cached_guild, guild_data)
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

    def apply_private_channel_activity(self, message: dict[str, Any]) -> bool:
        channel_id = message.get("channel_id", "")
        if not channel_id:
            return False

        author_id = str((message.get("author") or {}).get("id", ""))
        is_own_message = author_id != "" and author_id == str((self.me or {}).get("id", ""))
        is_active = channel_id == self.active_channel_id

        for channel in self.private_channels:
            if channel.get("id") != channel_id:
                continue

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
        return False

    def get_guild_unread_count(self, guild_id: str) -> int:
        mentions = self.get_guild_mention_count(guild_id)
        if mentions > 0:
            return mentions

        if self.is_guild_muted(guild_id):
            return 0

        count = 0
        for channel in self.iter_visible_guild_channels(guild_id):
            if self.is_channel_muted(channel):
                continue
            count += self.is_channel_unread(channel)
        return count

    def get_dm_unread_count(self) -> int:
        count = 0
        for channel in self.private_channels:
            count += self.channel_badge_count(channel)
        return count

    def apply_guild_channel_activity(self, message: dict[str, Any]) -> str | None:
        channel_id = message.get("channel_id", "")
        if not channel_id:
            return None
        author_id = str((message.get("author") or {}).get("id", ""))
        is_own_message = author_id != "" and author_id == str((self.me or {}).get("id", ""))
        is_active = channel_id == self.active_channel_id
        mentioned = self.message_mentions_me(message)
        for guild_id, channels in self.guild_channels.items():
            for channel in channels:
                if channel.get("id") == channel_id:
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
        return None

    def get_guild_for_channel(self, channel_id: str) -> str | None:
        if not channel_id:
            return None
        # Fast path: use the pre-built reverse index
        if channel_id in self.channel_to_guild:
            return self.channel_to_guild[channel_id]
        # Slow path: scan loaded guild channel lists
        for guild_id, channels in self.guild_channels.items():
            for channel in channels:
                if channel.get("id") == channel_id:
                    self.channel_to_guild[channel_id] = guild_id
                    return guild_id
        return None

    def get_channel(self, channel_id: str) -> dict[str, Any] | None:
        if not channel_id:
            return None
        for channel in self.private_channels:
            if channel.get("id") == channel_id:
                return channel
        for channels in self.guild_channels.values():
            for channel in channels:
                if channel.get("id") == channel_id:
                    return channel
        return None

    def format_ready_payload(self) -> dict[str, Any]:
        return {
            "me": self.format_current_user(),
            "guilds": self.format_sidebar_guild_rows(),
            "dmContacts": self.format_dm_contacts(),
            "dmGroups": self.format_dm_groups(),
        }

    def format_current_user(self) -> dict[str, Any]:
        if not self.me:
            return {}
        return {
            "id": self.me.get("id", ""),
            "username": self.display_name(self.me),
        }

    def _sort_guilds_by_join(self, guilds: list[dict[str, Any]]) -> None:
        def sort_key(g: dict[str, Any]) -> tuple[int, str]:
            ja = g.get("joined_at")
            if isinstance(ja, str) and ja:
                return (0, ja)
            return (1, str(g.get("id", "")))

        guilds.sort(key=sort_key)

    def _guild_sidebar_entry(
        self,
        guild: dict[str, Any],
        *,
        folder_key: str = "",
        folder_color_hex: str = "",
    ) -> dict[str, Any]:
        guild_id = str(guild.get("id", ""))
        return {
            "itemType": "server",
            "folderName": "",
            "folderColor": 0,
            "folderColorHex": folder_color_hex,
            "folderKey": folder_key,
            "folderUnread": 0,
            "previewIconUrls": "",
            "previewAbbrs": "",
            "serverId": guild_id,
            "name": guild.get("name", ""),
            "abbr": self.abbr(guild.get("name", "")),
            "iconUrl": self.guild_icon_url(guild_id, guild.get("icon")),
            "unread": self.get_guild_unread_count(guild_id),
            "unreadKind": self.guild_unread_kind(guild_id),
        }

    def format_sidebar_guild_rows(self) -> list[dict[str, Any]]:
        """Sidebar rail: optional folder headers (from user_settings.guild_folders) + servers.

        Matches the common client pattern (see Aerochat Home.xaml AddGuilds): walk folder
        definitions in order, then append guilds not listed in any folder sorted by join time.
        If guild_folders is empty, use guild_positions; else alphabetical / join fallback.
        """
        by_id: dict[str, dict[str, Any]] = {}
        for guild in self.guilds:
            gid = guild.get("id")
            if gid is None:
                continue
            by_id[str(gid)] = guild

        rows: list[dict[str, Any]] = []
        seen: set[str] = set()

        if self.guild_folders_raw:
            for fi, folder in enumerate(self.guild_folders_raw):
                name_raw = folder.get("name")
                name_str = name_raw.strip() if isinstance(name_raw, str) else ""
                color_val = folder.get("color")
                try:
                    fc = int(color_val) if color_val is not None else 0
                except (TypeError, ValueError):
                    fc = 0
                hexcol = self._folder_color_hex(color_val)

                guild_objs: list[dict[str, Any]] = []
                for gid in folder.get("guild_ids") or []:
                    sid = str(gid)
                    guild_obj = by_id.get(sid)
                    if not guild_obj:
                        continue
                    guild_objs.append(guild_obj)
                    seen.add(sid)

                folder_key = f"f{fi}"
                if name_str and guild_objs:
                    preview_urls = [
                        self.guild_icon_url(str(g.get("id")), g.get("icon"))
                        for g in guild_objs[:4]
                    ]
                    preview_abbrs = [
                        self.abbr(g.get("name", "")) for g in guild_objs[:4]
                    ]
                    folder_mentions = sum(
                        self.get_guild_mention_count(str(g.get("id", "")))
                        for g in guild_objs
                    )
                    folder_has_unread = any(
                        self.guild_has_unread(str(g.get("id", "")))
                        for g in guild_objs
                    )
                    rows.append(
                        {
                            "itemType": "folderHeader",
                            "folderKey": folder_key,
                            "folderName": name_str,
                            "folderColor": fc,
                            "folderColorHex": hexcol,
                            "previewIconUrls": "\n".join(preview_urls),
                            "previewAbbrs": "\n".join(preview_abbrs),
                            "folderUnread": folder_mentions if folder_mentions > 0 else 0,
                            "folderUnreadKind": "count" if folder_mentions > 0 else ("dot" if folder_has_unread else "none"),
                            "serverId": "",
                            "name": "",
                            "abbr": "",
                            "iconUrl": "",
                            "unread": 0,
                        }
                    )
                    for g in guild_objs:
                        rows.append(
                            self._guild_sidebar_entry(
                                g,
                                folder_key=folder_key,
                                folder_color_hex=hexcol,
                            )
                        )
                else:
                    for g in guild_objs:
                        rows.append(self._guild_sidebar_entry(g))

            leftover = [by_id[s] for s in by_id if s not in seen]
            self._sort_guilds_by_join(leftover)
            for g in leftover:
                rows.append(self._guild_sidebar_entry(g))
            return rows

        if self.guild_positions_raw:
            for sid in self.guild_positions_raw:
                guild_obj = by_id.get(str(sid))
                if guild_obj:
                    rows.append(self._guild_sidebar_entry(guild_obj))
                    seen.add(str(sid))
            for sid in sorted(s for s in by_id if s not in seen):
                rows.append(self._guild_sidebar_entry(by_id[sid]))
            return rows

        guild_list = list(by_id.values())
        self._sort_guilds_by_join(guild_list)
        return [self._guild_sidebar_entry(g) for g in guild_list]

    def format_dm_contacts(self) -> list[dict[str, Any]]:
        contacts = []
        for channel in self._sorted_private_channels():
            if channel.get("type") != 1:
                continue
            recipients = channel.get("recipients", []) or []
            if not recipients:
                continue
            recipient = recipients[0]
            self.cache_user(recipient)
            user_id = recipient.get("id", "")
            contacts.append(
                {
                    "contactId": user_id,
                    "channelId": channel.get("id", ""),
                    "name": self.display_name(recipient),
                    "abbr": self.abbr(self.display_name(recipient)),
                    "iconUrl": self.user_avatar_url(user_id, recipient.get("avatar")),
                    "status": self.presences.get(user_id, "offline"),
                    "unread": self.channel_badge_count(channel),
                    "unreadKind": self.channel_unread_kind(channel),
                    "sortKey": self._last_message_sort_value(channel.get("last_message_id")),
                }
            )
        return contacts

    def format_dm_groups(self) -> list[dict[str, Any]]:
        groups = []
        for channel in self._sorted_private_channels():
            if channel.get("type") != 3:
                continue
            name = channel.get("name") or self.group_name(channel)
            groups.append(
                {
                    "groupId": channel.get("id", ""),
                    "channelId": channel.get("id", ""),
                    "name": name,
                    "abbr": self.abbr(name),
                    "iconUrl": self.group_dm_icon_url(channel.get("id", ""), channel.get("icon")),
                    "unread": self.channel_badge_count(channel),
                    "unreadKind": self.channel_unread_kind(channel),
                    "sortKey": self._last_message_sort_value(channel.get("last_message_id")),
                }
            )
        return groups

    def format_private_channel_payload(self) -> dict[str, Any]:
        return {
            "dmContacts": self.format_dm_contacts(),
            "dmGroups": self.format_dm_groups(),
        }

    def format_guild_channel_list(self, guild_id: str) -> list[dict[str, Any]]:
        channels = self.guild_channels.get(guild_id, [])
        channel_index = {
            str(channel.get("id", "") or ""): channel
            for channel in channels
            if str(channel.get("id", "") or "")
        }
        categories = {
            channel["id"]: {
                "id": channel.get("id", ""),
                "name": channel.get("name", ""),
                "position": int(channel.get("position", 0)),
            }
            for channel in channels
            if channel.get("type") == 4
        }

        def category_for_channel(channel: dict[str, Any]) -> dict[str, Any] | None:
            parent_id = str(channel.get("parent_id", "") or "")
            parent = channel_index.get(parent_id)
            if parent and int(parent.get("type", -1)) == 4:
                return categories.get(parent_id)
            if parent:
                grandparent_id = str(parent.get("parent_id", "") or "")
                return categories.get(grandparent_id)
            return None

        def thread_parent(channel: dict[str, Any]) -> dict[str, Any] | None:
            channel_type = int(channel.get("type", -1))
            if channel_type not in (10, 11, 12):
                return None
            parent_id = str(channel.get("parent_id", "") or "")
            return channel_index.get(parent_id)

        def channel_sort_key(channel: dict[str, Any]) -> tuple[int, int, int, int, str]:
            category = category_for_channel(channel)
            category_position = category["position"] if category else -1
            parent = thread_parent(channel)
            parent_position = int(parent.get("position", 0)) if parent else int(channel.get("position", 0))
            thread_rank = 1 if parent else 0
            return (
                category_position,
                parent_position,
                thread_rank,
                int(channel.get("position", 0)),
                channel.get("name", ""),
            )

        formatted = []
        for channel in sorted(channels, key=channel_sort_key):
            channel_type = int(channel.get("type", -1))
            if not self.is_visible_guild_channel(guild_id, channel):
                continue
            category = category_for_channel(channel) or {}
            parent = thread_parent(channel)
            parent_id = str(channel.get("parent_id", "") or "")
            formatted.append(
                {
                    "channelId": channel.get("id", ""),
                    "categoryId": category.get("id", "uncategorized"),
                    "category": category.get("name", "Channels"),
                    "name": channel.get("name", ""),
                    "channelType": self.channel_type_name(channel_type),
                    "channelGlyph": self.channel_type_glyph(channel_type),
                    "channelIconName": self.channel_type_icon(channel_type),
                    "openable": self.channel_is_openable(channel),
                    "unread": self.channel_badge_count(channel),
                    "unreadKind": self.channel_unread_kind(channel),
                    "indentLevel": 1 if parent else 0,
                    "parentChannelId": parent_id,
                    "parentName": str((parent or {}).get("name", "") or ""),
                }
            )
        return formatted

    def format_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [self.format_message(message) for message in messages]

    def guild_id_for_message(self, message: dict[str, Any] | None) -> str:
        if not isinstance(message, dict):
            return ""
        guild_id = str(message.get("guild_id", "") or "")
        if guild_id:
            return guild_id
        channel_id = str(message.get("channel_id", "") or "")
        if channel_id:
            return self.get_guild_for_channel(channel_id) or ""
        return ""

    def format_message(self, message: dict[str, Any]) -> dict[str, Any]:
        author = message.get("author") or {}
        member = message.get("member") or {}
        guild_id = self.guild_id_for_message(message)
        cached_user = self.cache_user(author, member, guild_id=guild_id)

        display_name = self.message_display_name(cached_user, guild_id=guild_id, member=member) or "Unknown"
        content = self.render_message_content(
            message.get("content", ""),
            message.get("mentions", []) or [],
            guild_id=guild_id,
            rich=True,
        )

        raw_attachments = message.get("attachments", []) or []
        embeds = message.get("embeds", []) or []
        
        medias = []
        for att in raw_attachments:
            medias.append(self.format_media(att))
            
        for em in embeds:
            em_type = em.get("type", "")
            if em_type == "image":
                img = em.get("image") or em.get("thumbnail") or {}
                if img.get("url"):
                    medias.append(self.format_media({
                        "content_type": "image/unknown", 
                        "url": img.get("url"), 
                        "proxy_url": img.get("proxy_url"), 
                        "width": img.get("width"), 
                        "height": img.get("height"), 
                        "filename": "Image"
                    }))
            elif em_type == "video":
                vid = em.get("video") or {}
                thumbnail = em.get("thumbnail") or {}
                provider = (em.get("provider") or {}).get("name", "").lower()
                url = em.get("url") or vid.get("url") or ""
                # YouTube / Vimeo etc. are link previews, not direct video files
                is_web_video = provider in ("youtube", "vimeo", "twitch") or \
                               "youtube.com" in url or "youtu.be" in url
                
                if is_web_video:
                    if thumbnail.get("url"):
                        medias.append({
                            "messageType": "link",
                            "mediaUrl": url,
                            "mediaPreviewUrl": thumbnail.get("proxy_url") or thumbnail.get("url"),
                            "mediaFileName": em.get("title") or url,
                            "mediaContentType": "text/html",
                            "mediaWidth": thumbnail.get("width") or 0,
                            "mediaHeight": thumbnail.get("height") or 0,
                        })
                elif vid.get("url"):
                    medias.append(self.format_media({
                        "content_type": "video/mp4", 
                        "url": vid.get("url"), 
                        "proxy_url": thumbnail.get("proxy_url") or vid.get("proxy_url"), 
                        "width": vid.get("width"), 
                        "height": vid.get("height"), 
                        "filename": "Video",
                        "is_gif_like": provider == "tenor",
                    }))
            elif em_type == "gifv":
                vid = em.get("video") or {}
                if vid.get("url"):
                    medias.append(self.format_media({
                        "content_type": "video/mp4", 
                        "url": vid.get("url"), 
                        "proxy_url": vid.get("proxy_url"), 
                        "width": vid.get("width"), 
                        "height": vid.get("height"), 
                        "filename": "GIF",
                        "is_gif_like": True,
                    }))
        if medias:
            temp_content = re.sub(r'https?://[^\s]+', '', message.get("content", ""))
            if not temp_content.strip():
                content = ""

        message_type = self._message_type_value(message.get("type"))
        reply = self.format_reply(message.get("referenced_message"))
        forwarded = self.format_forwarded(message.get("message_snapshots") or [])
        system_text = self.format_system_message(message, cached_user, message_type)

        if not content and not medias:
            content = "\n".join(
                a.get("url", "")
                for a in raw_attachments
                if a.get("url")
            )

        display_kind = "system" if system_text else "default"
        if system_text:
            import html
            content = html.escape(system_text)

        return {
            "messageId": message.get("id", ""),
            "authorId": author.get("id", ""),
            "author": display_name,
            "initials": self.abbr(display_name, length=2),
            "avatarCol": self.avatar_color(author.get("id", "")),
            "timestamp": self.format_timestamp(message.get("timestamp")),
            "body": content,
            "rawBody": message.get("content", ""),
            "channelId": message.get("channel_id", ""),
            "displayKind": display_kind,
            "discordMessageType": self.MESSAGE_TYPE_NAMES.get(message_type, str(message_type)),
            "medias": medias,
            "replyMessageId": reply["replyMessageId"],
            "replyAuthor": reply["replyAuthor"],
            "replyBody": reply["replyBody"],
            "hasReply": reply["hasReply"],
            "forwardedLabel": forwarded["forwardedLabel"],
            "forwardedAuthor": forwarded["forwardedAuthor"],
            "forwardedBody": forwarded["forwardedBody"],
            "hasForwarded": forwarded["hasForwarded"],
        }

    def format_typing(self, payload: dict[str, Any]) -> dict[str, Any]:
        user_id = str(payload.get("user_id", "") or "")
        guild_id = str(payload.get("guild_id", "") or "")
        if not guild_id:
            guild_id = self.get_guild_for_channel(str(payload.get("channel_id", "") or "")) or ""
        user = self.users.get(user_id, {})
        member = payload.get("member", {}) or {}
        if member and isinstance(member.get("user"), dict):
            user = self.cache_user(member.get("user") or {}, member, guild_id=guild_id)
        elif user and member:
            user = self.cache_user(user, member, guild_id=guild_id)
        author = self.message_display_name(user, guild_id=guild_id, member=member) or member.get("nick") or "Someone"
        return {
            "userId": user_id,
            "author": author,
            "channelId": payload.get("channel_id", ""),
        }

    @staticmethod
    def abbr(name: str, length: int = 2) -> str:
        parts = [part for part in re.split(r"[^A-Za-z0-9]+", name or "") if part]
        if not parts:
            return "?"
        if len(parts) == 1:
            return parts[0][:length].upper()
        return "".join(part[0] for part in parts[:length]).upper()

    @staticmethod
    def display_name(user: dict[str, Any] | None) -> str:
        if not user:
            return ""
        return user.get("global_name") or user.get("username") or ""

    @staticmethod
    def guild_emoji_url(emoji_id: str, animated: bool = False) -> str:
        if not emoji_id:
            return ""
        ext = "gif" if animated else "png"
        return f"https://cdn.discordapp.com/emojis/{emoji_id}.{ext}?size=64&quality=lossless"

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
                guild_member["nick"] = member["nick"]  # may be None
            self._merge_dict(guild_member, member)
        return (
            guild_member.get("nick")
            or user.get("global_name")
            or user.get("username")
            or ""
        )

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

    @staticmethod
    def guild_icon_url(guild_id: str, icon_hash: str | None) -> str:
        if not guild_id or not icon_hash:
            return ""
        return f"https://cdn.discordapp.com/icons/{guild_id}/{icon_hash}.png?size=128"

    @staticmethod
    def user_avatar_url(user_id: str, avatar_hash: str | None) -> str:
        if not user_id or not avatar_hash:
            return ""
        return f"https://cdn.discordapp.com/avatars/{user_id}/{avatar_hash}.png?size=128"

    @staticmethod
    def group_dm_icon_url(channel_id: str, icon_hash: str | None) -> str:
        if not channel_id or not icon_hash:
            return ""
        return f"https://cdn.discordapp.com/channel-icons/{channel_id}/{icon_hash}.png?size=128"

    @staticmethod
    def avatar_color(seed: str) -> str:
        digest = hashlib.md5(seed.encode("utf-8")).hexdigest()
        return f"#{digest[:6]}"

    @staticmethod
    def group_name(channel: dict[str, Any]) -> str:
        recipients = channel.get("recipients", []) or []
        names = [
            recipient.get("global_name") or recipient.get("username") or "Unknown"
            for recipient in recipients
        ]
        return ", ".join(names[:3]) or "Group"

    @staticmethod
    def format_timestamp(raw_timestamp: str | None) -> str:
        if not raw_timestamp:
            return ""
        try:
            timestamp = datetime.fromisoformat(raw_timestamp.replace("Z", "+00:00"))
        except ValueError:
            return raw_timestamp

        now = datetime.now(timezone.utc).astimezone()
        local = timestamp.astimezone()
        if local.date() == now.date():
            return local.strftime("%H:%M")
        return local.strftime("%Y-%m-%d %H:%M")

    def replace_mentions(
        self,
        content: str,
        mentions: list[dict[str, Any]],
        guild_id: str = "",
    ) -> str:
        if not content:
            return ""

        mention_names = {}
        for mention in mentions:
            user_id = str(mention.get("id", "") or "")
            if not user_id:
                continue
            # In guild messages the mentions array includes a partial `member`
            # object (with `nick`) embedded directly on each user entry.
            member = mention.get("member")
            cached = self.cache_user(mention, member, guild_id=guild_id)
            mention_names[user_id] = self.message_display_name(cached, guild_id=guild_id, member=member) or user_id

        def repl(match: re.Match[str]) -> str:
            user_id = match.group(1)
            return f"@{mention_names.get(user_id, user_id)}"

        return MENTION_RE.sub(repl, content)

    def format_reply(self, referenced_message: dict[str, Any] | None) -> dict[str, Any]:
        result = {
            "hasReply": False,
            "replyMessageId": "",
            "replyAuthor": "",
            "replyBody": "",
        }
        if not referenced_message:
            return result

        author = referenced_message.get("author") or {}
        member = referenced_message.get("member") or {}
        guild_id = self.guild_id_for_message(referenced_message)
        cached_user = self.cache_user(author, member, guild_id=guild_id)
        content = self.render_message_content(
            referenced_message.get("content", ""),
            referenced_message.get("mentions", []) or [],
            guild_id=guild_id,
            rich=False,
        ).strip()
        attachments = referenced_message.get("attachments", []) or []
        media = self.format_media(attachments[0]) if attachments else self.format_media({})

        if not content:
            if media["messageType"] == "image":
                content = "Image"
            elif media["messageType"] == "video":
                content = "Video"
            elif media["messageType"] == "audio":
                content = "Audio"
            elif media["messageType"] == "file":
                content = media["mediaFileName"] or "Attachment"
            else:
                content = "Message"

        result.update(
            {
                "hasReply": True,
                "replyMessageId": referenced_message.get("id", ""),
                "replyAuthor": self.message_display_name(cached_user, guild_id=guild_id, member=member) or "Unknown",
                "replyBody": content,
            }
        )
        return result

    def format_forwarded(self, snapshots: list[dict[str, Any]]) -> dict[str, Any]:
        result = {
            "hasForwarded": False,
            "forwardedLabel": "",
            "forwardedAuthor": "",
            "forwardedBody": "",
            "media": self.format_media({}),
        }
        if not snapshots:
            return result

        message = (snapshots[0] or {}).get("message") or {}
        author = message.get("author") or {}
        guild_id = self.guild_id_for_message(message)
        cached_user = self.cache_user(author, message.get("member") or {}, guild_id=guild_id) if author else {}
        attachments = message.get("attachments", []) or []
        media = self.format_media(attachments[0]) if attachments else self.format_media({})

        content = self.render_message_content(
            message.get("content", ""),
            message.get("mentions", []) or [],
            guild_id=guild_id,
            rich=False,
        ).strip()
        if not content:
            if media["messageType"] == "image":
                content = "Image"
            elif media["messageType"] == "video":
                content = "Video"
            elif media["messageType"] == "audio":
                content = "Audio"
            elif media["messageType"] == "file":
                content = media["mediaFileName"] or "Attachment"
            else:
                content = "Forwarded message"

        result.update(
            {
                "hasForwarded": True,
                "forwardedLabel": "Forwarded",
                "forwardedAuthor": self.message_display_name(cached_user, guild_id=guild_id) or self.display_name(cached_user) or "",
                "forwardedBody": content,
                "media": media,
            }
        )
        return result

    def format_system_message(
        self,
        message: dict[str, Any],
        user: dict[str, Any],
        message_type: int,
    ) -> str:
        guild_id = self.guild_id_for_message(message)
        user_name = self.message_display_name(user, guild_id=guild_id, member=message.get("member") or {}) or "Someone"
        guild_name = ((message.get("guild") or {}).get("name")) or ""
        content = self.render_message_content(
            message.get("content", ""),
            message.get("mentions", []) or [],
            guild_id=guild_id,
            rich=False,
        ).strip()

        if content == "[nudge]":
            if user.get("id") and user.get("id") == (self.me or {}).get("id"):
                return "You just sent a nudge."
            return f"{user_name} just sent a nudge."

        system_messages = {
            1: f"{user_name} was added to the group.",
            2: f"{user_name} was removed from the group.",
            3: f"{user_name} started a call.",
            4: f"{user_name} changed the group name to {content}." if content else f"{user_name} changed the group name.",
            5: f"{user_name} changed the group icon.",
            6: f"{user_name} pinned a message to this channel.",
            7: f"{user_name} joined the conversation.",
            8: f"{user_name} boosted the server!",
            9: f"{user_name} boosted the server to level 1!",
            10: f"{user_name} boosted the server to level 2!",
            11: f"{user_name} boosted the server to level 3!",
            12: f"{user_name} followed this channel.",
            14: f"{guild_name or 'This server'} was disqualified from server discovery.",
            15: f"{guild_name or 'This server'} was requalified for server discovery.",
            16: f"{guild_name or 'This server'} has failed to meet server discovery requirements for a week.",
            17: f"{guild_name or 'This server'} has failed to meet server discovery requirements for three weeks.",
            18: f"{user_name} started a thread: {content}." if content else f"{user_name} started a thread.",
            21: "This is the start of the thread.",
            22: "Invite more people to help build this server.",
            24: "AutoMod blocked or flagged a message.",
            25: f"{user_name} purchased a role subscription.",
            26: "A premium interaction is available.",
            27: f"{user_name} started a stage.",
            28: f"{user_name} ended a stage.",
            29: f"{user_name} is now speaking in the stage.",
            30: f"{user_name} raised their hand in the stage.",
            31: f"{user_name} changed the stage topic to {content}." if content else f"{user_name} changed the stage topic.",
            32: f"{user_name} purchased an app premium subscription.",
            35: f"{user_name} sent a premium referral.",
            36: f"{user_name} enabled server incident alert mode.",
            37: f"{user_name} disabled server incident alert mode.",
            38: f"{user_name} reported a raid.",
            39: f"{user_name} marked the incident report as a false alarm.",
            44: "A purchase notification was posted.",
            46: "A poll result was posted.",
        }
        return system_messages.get(message_type, "")

    @staticmethod
    def format_media(attachment: dict[str, Any]) -> dict[str, Any]:
        result = {
            "isMedia": False,
            "messageType": "text",
            "mediaIsGifLike": False,
            "mediaUrl": "",
            "mediaPreviewUrl": "",
            "mediaWidth": 0,
            "mediaHeight": 0,
            "mediaContentType": "",
            "mediaFileName": "",
            "mediaDuration": 0,
        }
        if not attachment:
            return result
        content_type = attachment.get("content_type") or ""
        url = attachment.get("url") or ""
        proxy_url = attachment.get("proxy_url") or url
        filename = (attachment.get("filename") or "").lower()

        if not content_type:
            if filename.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")):
                content_type = "image/unknown"
            elif filename.endswith((".mp4", ".webm", ".mov", ".mkv")):
                content_type = "video/unknown"
            elif filename.endswith((".mp3", ".ogg", ".wav", ".flac", ".m4a")):
                content_type = "audio/unknown"

        result.update(
            {
                "isMedia": True,
                "mediaUrl": url,
                "mediaPreviewUrl": proxy_url,
                "mediaWidth": int(attachment.get("width") or 0),
                "mediaHeight": int(attachment.get("height") or 0),
                "mediaContentType": content_type,
                "mediaIsGifLike": bool(attachment.get("is_gif_like")),
                "mediaFileName": attachment.get("filename", ""),
                "mediaDuration": int(attachment.get("duration_secs") or 0),
            }
        )

        if content_type.startswith("image/"):
            result["messageType"] = "image"
            if content_type == "image/gif":
                result["mediaPreviewUrl"] = url if url else proxy_url
            else:
                result["mediaPreviewUrl"] = DiscordState.build_image_preview_url(
                    proxy_url or url,
                    result["mediaWidth"],
                    result["mediaHeight"],
                )
        elif content_type.startswith("video/"):
            result["messageType"] = "video"
            result["mediaPreviewUrl"] = proxy_url
        elif content_type.startswith("audio/"):
            result["messageType"] = "audio"
        else:
            result["messageType"] = "file"

        return result

    @staticmethod
    def build_image_preview_url(url: str, width: int, height: int) -> str:
        if not url:
            return ""

        preview_width = width
        preview_height = height
        max_size = 400

        if width > 0 and height > 0:
            if width > height:
                preview_height = max(1, int(height / width * max_size))
                preview_width = max_size
            else:
                preview_width = max(1, int(width / height * max_size))
                preview_height = max_size

        parts = urlsplit(url.replace("cdn.discordapp.com", "media.discordapp.net"))
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        query["format"] = "png"
        if preview_width > 0 and preview_height > 0:
            query["width"] = str(preview_width)
            query["height"] = str(preview_height)

        return urlunsplit((
            parts.scheme,
            parts.netloc,
            parts.path,
            urlencode(query),
            parts.fragment,
        ))

    def _sorted_private_channels(self) -> list[dict[str, Any]]:
        return sorted(
            self.private_channels,
            key=lambda channel: (
                self._last_message_sort_value(channel.get("last_message_id")),
                channel.get("id", ""),
            ),
            reverse=True,
        )

    @staticmethod
    def _last_message_sort_value(last_message_id: str | None) -> int:
        if not last_message_id:
            return 0
        try:
            return int(last_message_id)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _message_type_value(raw_value: Any) -> int:
        try:
            return int(raw_value or 0)
        except (TypeError, ValueError):
            return 0

    @classmethod
    def can_access_channel(cls, channel: dict[str, Any]) -> bool:
        permissions = channel.get("permissions")
        if permissions is None:
            return True

        try:
            permission_bits = int(permissions)
        except (TypeError, ValueError):
            return True

        if not (permission_bits & cls.VIEW_CHANNEL_PERMISSION):
            return False

        channel_type = int(channel.get("type", -1))
        if channel_type in (2, 13) and not (permission_bits & cls.CONNECT_PERMISSION):
            return False

        return True

    def is_visible_guild_channel(self, guild_id: str, channel: dict[str, Any]) -> bool:
        channel_type = int(channel.get("type", -1))
        if channel_type not in (0, 2, 5, 10, 11, 12, 13, 15):
            return False
        return self.has_channel_access(guild_id, channel)

    def iter_visible_guild_channels(self, guild_id: str) -> list[dict[str, Any]]:
        return [
            channel
            for channel in self.guild_channels.get(guild_id, [])
            if self.is_visible_guild_channel(guild_id, channel)
        ]

    def has_channel_access(self, guild_id: str, channel: dict[str, Any]) -> bool:
        computed = self.compute_channel_permissions(guild_id, channel)
        if computed is None:
            return self.can_access_channel(channel)

        if not (computed & self.VIEW_CHANNEL_PERMISSION):
            return False

        channel_type = int(channel.get("type", -1))
        if channel_type in (2, 13) and not (computed & self.CONNECT_PERMISSION):
            return False

        return True

    def compute_channel_permissions(self, guild_id: str, channel: dict[str, Any]) -> int | None:
        if not self.me:
            return None

        role_permissions = self.guild_roles.get(guild_id)
        member = self.guild_members.get(guild_id)
        if not role_permissions or not member:
            return None

        me_id = (self.me or {}).get("id", "")
        everyone_permissions = role_permissions.get(guild_id, 0)
        permissions = everyone_permissions

        for role_id in member.get("roles", []) or []:
            permissions |= role_permissions.get(role_id, 0)

        if permissions & self.ADMINISTRATOR_PERMISSION:
            return (1 << 53) - 1

        overwrites = channel.get("permission_overwrites", []) or []

        everyone_overwrite = self._find_overwrite(overwrites, guild_id)
        permissions = self._apply_overwrite(permissions, everyone_overwrite)

        allow_roles = 0
        deny_roles = 0
        member_roles = set(member.get("roles", []) or [])
        for overwrite in overwrites:
            if overwrite.get("id") not in member_roles:
                continue
            if int(overwrite.get("type", 0)) != 0:
                continue
            allow_roles |= self._permission_value(overwrite.get("allow"))
            deny_roles |= self._permission_value(overwrite.get("deny"))
        permissions &= ~deny_roles
        permissions |= allow_roles

        member_overwrite = self._find_overwrite(overwrites, me_id)
        permissions = self._apply_overwrite(permissions, member_overwrite)
        return permissions

    @staticmethod
    def _find_overwrite(overwrites: list[dict[str, Any]], target_id: str) -> dict[str, Any] | None:
        for overwrite in overwrites:
            if overwrite.get("id") == target_id:
                return overwrite
        return None

    @classmethod
    def _apply_overwrite(cls, permissions: int, overwrite: dict[str, Any] | None) -> int:
        if not overwrite:
            return permissions
        deny = cls._permission_value(overwrite.get("deny"))
        allow = cls._permission_value(overwrite.get("allow"))
        permissions &= ~deny
        permissions |= allow
        return permissions

    @staticmethod
    def _permission_value(raw_value: Any) -> int:
        try:
            return int(raw_value or 0)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def channel_type_name(channel_type: int) -> str:
        return {
            0: "text",
            2: "voice",
            5: "announcement",
            10: "announcement_thread",
            11: "public_thread",
            12: "private_thread",
            13: "stage",
            15: "forum",
        }.get(channel_type, "unknown")

    @staticmethod
    def channel_type_glyph(channel_type: int) -> str:
        return {
            0: "#",
            2: "))",
            5: "!",
            10: ">",
            11: ">",
            12: ">",
            13: "*",
            15: "@",
        }.get(channel_type, "#")

    @staticmethod
    def channel_type_icon(channel_type: int) -> str:
        return {
            2: "speaker",
            5: "notification",
            13: "media-playback-start",
            15: "contact-group",
        }.get(channel_type, "")

    @staticmethod
    def channel_is_openable(channel: dict[str, Any]) -> bool:
        return int(channel.get("type", -1)) in (0, 5, 10, 11, 12)

    def channel_display_name(self, channel: dict[str, Any] | None, with_prefix: bool = True) -> str:
        if not channel:
            return "#unknown"
        channel_type = int(channel.get("type", -1))
        name = str(channel.get("name", "") or "")
        if channel_type in (0, 5, 10, 11, 12):
            return f"#{name}" if with_prefix and name else name
        return name

    def channel_label(self, channel_id: str, with_prefix: bool = True) -> str:
        channel = self.get_channel(channel_id)
        if channel:
            return self.channel_display_name(channel, with_prefix=with_prefix)
        return f"#{channel_id}" if with_prefix else channel_id

    def role_name(self, guild_id: str, role_id: str) -> str:
        if not guild_id or not role_id:
            return role_id
        return self.guild_role_names.get(guild_id, {}).get(role_id, role_id)

    def render_message_content(
        self,
        content: str,
        mentions: list[dict[str, Any]],
        *,
        guild_id: str = "",
        rich: bool = False,
    ) -> str:
        if not content:
            return ""

        import html

        mention_names: dict[str, str] = {}
        for mention in mentions:
            user_id = str(mention.get("id", "") or "")
            if not user_id:
                continue
            member = mention.get("member")
            cached = self.cache_user(mention, member, guild_id=guild_id)
            mention_names[user_id] = self.message_display_name(cached, guild_id=guild_id, member=member) or user_id

        emoji_size = 36 if rich and CUSTOM_EMOJI_RE.sub("", content).strip() == "" else 22
        parts: list[str] = []
        last_index = 0
        for match in DISCORD_TOKEN_RE.finditer(content):
            segment = content[last_index:match.start()]
            parts.append(html.escape(segment) if rich else segment)
            parts.append(self._render_discord_token(match, mention_names, guild_id, rich, emoji_size))
            last_index = match.end()

        tail = content[last_index:]
        parts.append(html.escape(tail) if rich else tail)
        rendered = "".join(parts)
        if rich:
            return rendered.replace("\n", "<br>")
        return rendered

    def _render_discord_token(
        self,
        match: re.Match[str],
        mention_names: dict[str, str],
        guild_id: str,
        rich: bool,
        emoji_size: int,
    ) -> str:
        import html

        url = match.group("url")
        if url:
            escaped_url = html.escape(url, quote=True)
            return f'<a href="{escaped_url}">{escaped_url}</a>' if rich else url

        emoji_id = match.group("emoji_id")
        if emoji_id:
            emoji_name = match.group("emoji_name") or emoji_id
            animated = (match.group("emoji_anim") or "") == "a"
            if not rich:
                return f":{emoji_name}:"
            alt = html.escape(f":{emoji_name}:", quote=True)
            src = html.escape(self.guild_emoji_url(emoji_id, animated), quote=True)
            return f'<img src="{src}" alt="{alt}" width="{emoji_size}" height="{emoji_size}"/>'

        user_id = match.group("user_id")
        if user_id:
            user_name = f"@{mention_names.get(user_id, user_id)}"
            return html.escape(user_name) if rich else user_name

        role_id = match.group("role_id")
        if role_id:
            role_name = f"@{self.role_name(guild_id, role_id)}"
            return html.escape(role_name) if rich else role_name

        channel_id = match.group("channel_id")
        if channel_id:
            label = self.channel_label(channel_id)
            if not rich:
                return label
            href = html.escape(f"disports://channel/{channel_id}", quote=True)
            return f'<a href="{href}">{html.escape(label)}</a>'

        return html.escape(match.group(0)) if rich else match.group(0)

    def format_guild_emoji_list(self, guild_id: str) -> list[dict[str, Any]]:
        emojis = self.guild_emojis.get(guild_id, [])
        formatted = []
        for emoji in sorted(emojis, key=lambda entry: str(entry.get("name", "") or "").lower()):
            emoji_id = str(emoji.get("id", "") or "")
            name = str(emoji.get("name", "") or "")
            animated = bool(emoji.get("animated"))
            if not emoji_id or not name:
                continue
            formatted.append(
                {
                    "emojiId": emoji_id,
                    "name": name,
                    "animated": animated,
                    "imageUrl": self.guild_emoji_url(emoji_id, animated),
                    "code": f"<{'a' if animated else ''}:{name}:{emoji_id}>",
                }
            )
        return formatted

    def format_channel_reference(self, channel_id: str) -> dict[str, Any]:
        channel = self.get_channel(channel_id)
        guild_id = self.get_guild_for_channel(channel_id) or str((channel or {}).get("guild_id", "") or "")
        name = self.channel_display_name(channel, with_prefix=False) if channel else ""
        channel_type = int((channel or {}).get("type", -1))
        return {
            "channelId": channel_id,
            "guildId": guild_id,
            "guildName": self.guild_name(guild_id),
            "name": name,
            "label": self.channel_display_name(channel, with_prefix=True) if channel else f"#{channel_id}",
            "openable": self.channel_is_openable(channel or {}),
            "channelType": self.channel_type_name(channel_type),
        }

    @staticmethod
    def _merge_dict(target: dict[str, Any], source: dict[str, Any]) -> None:
        for key, value in source.items():
            if value is None:
                continue
            if isinstance(value, str) and value == "":
                continue
            target[key] = value

    @staticmethod
    def _int_value(raw_value: Any) -> int:
        try:
            return max(0, int(raw_value or 0))
        except (TypeError, ValueError):
            return 0

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
            "badge_count": self._int_value(entry.get("badge_count")),
            "mention_count": self._int_value(entry.get("mention_count")),
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

        if self._snowflake_ge(incoming_last, existing_last):
            return {
                "last_message_id": incoming_last,
                "badge_count": self._int_value(incoming.get("badge_count")),
                "mention_count": self._int_value(incoming.get("mention_count")),
            }

        return {
            "last_message_id": existing_last,
            "badge_count": self._int_value(existing.get("badge_count")),
            "mention_count": self._int_value(existing.get("mention_count")),
        }

    def channel_badge_count(self, channel: dict[str, Any]) -> int:
        channel_id = str(channel.get("id", "") or "")
        if not channel_id:
            return 0

        state = self._read_state(channel_id)
        if int(channel.get("type", -1)) in (1, 3):
            badge_count = self._int_value(state.get("badge_count"))
            if badge_count > 0:
                return badge_count
            return 1 if self.is_channel_unread(channel) else 0

        mention_count = self._int_value(state.get("mention_count"))
        if mention_count > 0:
            return mention_count
        return 0

    def channel_unread_kind(self, channel: dict[str, Any]) -> str:
        if not channel:
            return "none"
        count = self.channel_badge_count(channel)
        if count > 0:
            return "count"
        if int(channel.get("type", -1)) not in (1, 3) and self.is_channel_muted(channel):
            return "none"
        if self.is_channel_unread(channel):
            return "dot"
        return "none"

    def guild_has_unread(self, guild_id: str) -> bool:
        if self.is_guild_muted(guild_id) and self.get_guild_mention_count(guild_id) == 0:
            return False
        for channel in self.iter_visible_guild_channels(guild_id):
            if self.channel_unread_kind(channel) != "none":
                return True
        return False

    def get_guild_mention_count(self, guild_id: str) -> int:
        count = 0
        for channel in self.iter_visible_guild_channels(guild_id):
            channel_id = str(channel.get("id", "") or "")
            if not channel_id:
                continue
            count += self._int_value(self._read_state(channel_id).get("mention_count"))
        return count

    def guild_unread_kind(self, guild_id: str) -> str:
        if self.get_guild_mention_count(guild_id) > 0:
            return "count"
        if self.guild_has_unread(guild_id):
            return "dot"
        return "none"

    def message_mentions_me(self, message: dict[str, Any]) -> bool:
        me_id = str((self.me or {}).get("id", "") or "")
        if not me_id:
            return False

        mention_everyone = bool(message.get("mention_everyone"))
        if mention_everyone:
            return True

        for mention in message.get("mentions", []) or []:
            if str(mention.get("id", "") or "") == me_id:
                return True

        guild_id = str(message.get("guild_id", "") or "")
        if guild_id:
            member = self.guild_members.get(guild_id) or {}
            my_roles = {str(role_id) for role_id in (member.get("roles") or []) if role_id is not None}
            for role_id in message.get("mention_roles", []) or []:
                if str(role_id) in my_roles:
                    return True

        return False

    @staticmethod
    def _snowflake_ge(lhs: str, rhs: str) -> bool:
        if not lhs:
            return False
        if not rhs:
            return True
        try:
            return int(lhs) >= int(rhs)
        except (TypeError, ValueError):
            return lhs >= rhs
