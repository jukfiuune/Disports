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
        self.guild_members: dict[str, dict[str, Any]] = {}
        self.users: dict[str, dict[str, Any]] = {}
        self.presences: dict[str, str] = {}
        self.active_channel_id: str | None = None
        self.read_states: dict[str, str] = {}
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
                        self.read_states = data
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
        if message_id:
            self.read_states[channel_id] = message_id
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
                self.read_states[channel_id] = last_id
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
            read_id = self.read_states.get(channel_id)
            read_val = int(read_id) if read_id else int(self.session_start_id)
            return 1 if last_val > read_val else 0
        except (ValueError, TypeError):
            return 0

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
            m_id = str(rs.get("last_message_id", ""))
            if c_id and m_id:
                self.read_states[c_id] = m_id
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

    def apply_presence(self, payload: dict[str, Any]) -> None:
        user = payload.get("user") or {}
        user_id = user.get("id")
        if user_id:
            self.presences[user_id] = payload.get("status", "offline")

    def cache_user(
        self,
        user: dict[str, Any] | None,
        member: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not user:
            return {}

        user_id = user.get("id", "")
        cached = self.users.setdefault(user_id, {})
        self._merge_dict(cached, user)
        if member:
            cached_member = cached.setdefault("_member", {})
            # nick=None is meaningful: it means "no server nickname".
            # _merge_dict skips None, so we must write it explicitly first
            # so that a cleared nickname doesn't stay stuck in cache.
            if "nick" in member:
                cached_member["nick"] = member["nick"]  # may be None
            self._merge_dict(cached_member, member)
        return cached

    def set_guild_channels(self, guild_id: str, channels: list[dict[str, Any]]) -> None:
        self.guild_channels[guild_id] = channels

    def set_guild_context(
        self,
        guild_id: str,
        guild_data: dict[str, Any] | None,
        member_data: dict[str, Any] | None,
    ) -> None:
        roles: dict[str, int] = {}
        for role in (guild_data or {}).get("roles", []) or []:
            role_id = role.get("id")
            if not role_id:
                continue
            try:
                roles[role_id] = int(role.get("permissions") or 0)
            except (TypeError, ValueError):
                roles[role_id] = 0
        if roles:
            self.guild_roles[guild_id] = roles
        if member_data:
            self.guild_members[guild_id] = member_data

    def apply_private_channel_activity(self, message: dict[str, Any]) -> bool:
        channel_id = message.get("channel_id", "")
        if not channel_id:
            return False

        for channel in self.private_channels:
            if channel.get("id") != channel_id:
                continue

            message_id = message.get("id")
            if message_id:
                channel["last_message_id"] = message_id

            if "mentions" in message:
                channel["mention_count"] = len(message["mentions"])

            return True
        return False

    def get_guild_unread_count(self, guild_id: str) -> int:
        count = 0
        for channel in self.guild_channels.get(guild_id, []):
            count += self.is_channel_unread(channel)
        return count

    def get_dm_unread_count(self) -> int:
        count = 0
        for channel in self.private_channels:
            count += self.is_channel_unread(channel)
        return count

    def apply_guild_channel_activity(self, message: dict[str, Any]) -> str | None:
        channel_id = message.get("channel_id", "")
        if not channel_id:
            return None
        for guild_id, channels in self.guild_channels.items():
            for channel in channels:
                if channel.get("id") == channel_id:
                    message_id = message.get("id")
                    if message_id:
                        channel["last_message_id"] = message_id
                    return guild_id
        return None

    def get_guild_for_channel(self, channel_id: str) -> str | None:
        if not channel_id:
            return None
        for guild_id, channels in self.guild_channels.items():
            for channel in channels:
                if channel.get("id") == channel_id:
                    return guild_id
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
                    fu = sum(
                        self.get_guild_unread_count(str(g.get("id", "")))
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
                            "folderUnread": fu,
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
                    "status": self.presences.get(user_id, "offline"),
                    "unread": self.is_channel_unread(channel),
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
                    "unread": self.is_channel_unread(channel),
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
        categories = {
            channel["id"]: {
                "id": channel.get("id", ""),
                "name": channel.get("name", ""),
                "position": int(channel.get("position", 0)),
            }
            for channel in channels
            if channel.get("type") == 4
        }

        def channel_sort_key(channel: dict[str, Any]) -> tuple[int, int, str]:
            parent_id = channel.get("parent_id")
            category = categories.get(parent_id)
            category_position = category["position"] if category else -1
            return (
                category_position,
                int(channel.get("position", 0)),
                channel.get("name", ""),
            )

        formatted = []
        for channel in sorted(channels, key=channel_sort_key):
            channel_type = int(channel.get("type", -1))
            if channel_type not in (0, 2, 5, 13, 15):
                continue
            if not self.has_channel_access(guild_id, channel):
                continue
            parent_id = channel.get("parent_id")
            formatted.append(
                {
                    "channelId": channel.get("id", ""),
                    "categoryId": (categories.get(parent_id) or {}).get("id", "uncategorized"),
                    "category": (categories.get(parent_id) or {}).get("name", "Channels"),
                    "name": channel.get("name", ""),
                    "channelType": self.channel_type_name(channel_type),
                    "channelGlyph": self.channel_type_glyph(channel_type),
                    "channelIconName": self.channel_type_icon(channel_type),
                    "openable": channel_type in (0, 5),
                    "unread": self.is_channel_unread(channel),
                }
            )
        return formatted

    def format_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [self.format_message(message) for message in messages]

    def format_message(self, message: dict[str, Any]) -> dict[str, Any]:
        author = message.get("author") or {}
        member = message.get("member") or {}
        cached_user = self.cache_user(author, member)

        display_name = self.message_display_name(cached_user) or "Unknown"
        content = message.get("content", "")
        import html
        import re
        content = html.escape(content)
        content = self.replace_mentions(content, message.get("mentions", []) or [])
        content = re.sub(r'(https?://[^\s]+)', r'<a href="\1">\1</a>', content)
        
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
                if vid.get("url"):
                    medias.append(self.format_media({
                        "content_type": "video/mp4", 
                        "url": vid.get("url"), 
                        "proxy_url": thumbnail.get("proxy_url") or vid.get("proxy_url"), 
                        "width": vid.get("width"), 
                        "height": vid.get("height"), 
                        "filename": "Video"
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
                        "filename": "GIF"
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
            content = system_text

        return {
            "messageId": message.get("id", ""),
            "authorId": author.get("id", ""),
            "author": display_name,
            "initials": self.abbr(display_name, length=2),
            "avatarCol": self.avatar_color(author.get("id", "")),
            "timestamp": self.format_timestamp(message.get("timestamp")),
            "body": content,
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
        user_id = payload.get("user_id", "")
        user = self.users.get(user_id, {})
        member = payload.get("member", {}) or {}
        if user and member:
            cached_member = user.setdefault("_member", {})
            self._merge_dict(cached_member, member)
        author = self.message_display_name(user) or member.get("nick") or "Someone"
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
    def message_display_name(user: dict[str, Any] | None) -> str:
        if not user:
            return ""
        member = user.get("_member") or {}
        return (
            member.get("nick")
            or user.get("global_name")
            or user.get("username")
            or ""
        )

    @staticmethod
    def guild_icon_url(guild_id: str, icon_hash: str | None) -> str:
        if not guild_id or not icon_hash:
            return ""
        return f"https://cdn.discordapp.com/icons/{guild_id}/{icon_hash}.png?size=128"

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
    ) -> str:
        if not content:
            return ""

        mention_names = {}
        for mention in mentions:
            user_id = mention.get("id")
            if not user_id:
                continue
            # In guild messages the mentions array includes a partial `member`
            # object (with `nick`) embedded directly on each user entry.
            member = mention.get("member")
            cached = self.cache_user(mention, member)
            mention_names[user_id] = self.message_display_name(cached) or user_id

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
        cached_user = self.cache_user(author, member)
        content = self.replace_mentions(
            referenced_message.get("content", ""),
            referenced_message.get("mentions", []) or [],
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
                "replyAuthor": self.message_display_name(cached_user) or "Unknown",
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
        cached_user = self.cache_user(author, message.get("member") or {}) if author else {}
        attachments = message.get("attachments", []) or []
        media = self.format_media(attachments[0]) if attachments else self.format_media({})

        content = self.replace_mentions(
            message.get("content", ""),
            message.get("mentions", []) or [],
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
                "forwardedAuthor": self.message_display_name(cached_user) or self.display_name(cached_user) or "",
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
        user_name = self.message_display_name(user) or "Someone"
        guild_name = ((message.get("guild") or {}).get("name")) or ""
        content = self.replace_mentions(
            message.get("content", ""),
            message.get("mentions", []) or [],
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
            13: "stage",
            15: "forum",
        }.get(channel_type, "unknown")

    @staticmethod
    def channel_type_glyph(channel_type: int) -> str:
        return {
            0: "#",
            2: "))",
            5: "!",
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
    def _merge_dict(target: dict[str, Any], source: dict[str, Any]) -> None:
        for key, value in source.items():
            if value is None:
                continue
            if isinstance(value, str) and value == "":
                continue
            target[key] = value
