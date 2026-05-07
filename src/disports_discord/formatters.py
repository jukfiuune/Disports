from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any

from ._utils import last_message_sort_value


class FormattersMixin:
    # Top-level view-model builders
    def format_ready_payload(self) -> dict[str, Any]:
        return {
            "me": self.format_current_user(),
            "guilds": self.format_sidebar_guild_rows(),
            "dmContacts": self.format_dm_contacts(),
            "dmGroups": self.format_dm_groups(),
        }

    def format_current_user(self) -> dict[str, Any]:
        if not self.me:  # type: ignore[attr-defined]
            return {}
        return {
            "id": self.me.get("id", ""),  # type: ignore[attr-defined]
            "username": self.display_name(self.me),  # type: ignore[attr-defined]
        }

    def format_private_channel_payload(self) -> dict[str, Any]:
        return {
            "dmContacts": self.format_dm_contacts(),
            "dmGroups": self.format_dm_groups(),
        }
    # Sidebar guild rows
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
            "abbr": self.abbr(guild.get("name", "")),  # type: ignore[attr-defined]
            "iconUrl": self.guild_icon_url(guild_id, guild.get("icon")),
            "unread": self.get_guild_unread_count(guild_id),  # type: ignore[attr-defined]
            "unreadKind": self.guild_unread_kind(guild_id),  # type: ignore[attr-defined]
        }

    def format_sidebar_guild_rows(self) -> list[dict[str, Any]]:
        by_id = self.guild_by_id  # type: ignore[attr-defined]
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()

        if self.guild_folders_raw:  # type: ignore[attr-defined]
            for fi, folder in enumerate(self.guild_folders_raw):  # type: ignore[attr-defined]
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
                        self.abbr(g.get("name", "")) for g in guild_objs[:4]  # type: ignore[attr-defined]
                    ]
                    folder_mentions = sum(
                        self.get_guild_mention_count(str(g.get("id", "")))  # type: ignore[attr-defined]
                        for g in guild_objs
                    )
                    folder_has_unread = any(
                        self.guild_has_unread(str(g.get("id", "")))  # type: ignore[attr-defined]
                        for g in guild_objs
                    )
                    rows.append({
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
                    })
                    for g in guild_objs:
                        rows.append(self._guild_sidebar_entry(g, folder_key=folder_key, folder_color_hex=hexcol))
                else:
                    for g in guild_objs:
                        rows.append(self._guild_sidebar_entry(g))

            leftover = [by_id[s] for s in by_id if s not in seen]
            self._sort_guilds_by_join(leftover)
            for g in leftover:
                rows.append(self._guild_sidebar_entry(g))
            return rows

        if self.guild_positions_raw:  # type: ignore[attr-defined]
            for sid in self.guild_positions_raw:  # type: ignore[attr-defined]
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
    # DM contacts and groups
    def _sorted_private_channels(self) -> list[dict[str, Any]]:
        return sorted(
            self.private_channels,  # type: ignore[attr-defined]
            key=lambda channel: (
                last_message_sort_value(channel.get("last_message_id")),
                channel.get("id", ""),
            ),
            reverse=True,
        )

    def format_dm_contacts(self) -> list[dict[str, Any]]:
        contacts = []
        for channel in self._sorted_private_channels():
            if channel.get("type") != 1:
                continue
            recipients = channel.get("recipients", []) or []
            if not recipients:
                continue
            recipient = recipients[0]
            self.cache_user(recipient)  # type: ignore[attr-defined]
            user_id = recipient.get("id", "")
            contacts.append({
                "contactId": user_id,
                "channelId": channel.get("id", ""),
                "name": self.display_name(recipient),
                "abbr": self.abbr(self.display_name(recipient)),  # type: ignore[attr-defined]
                "iconUrl": self.user_avatar_url(user_id, recipient.get("avatar")),
                "status": self.presences.get(user_id, "offline"),  # type: ignore[attr-defined]
                "unread": self.channel_badge_count(channel),  # type: ignore[attr-defined]
                "unreadKind": self.channel_unread_kind(channel),  # type: ignore[attr-defined]
                "sortKey": last_message_sort_value(channel.get("last_message_id")),
            })
        return contacts

    def format_dm_groups(self) -> list[dict[str, Any]]:
        groups = []
        for channel in self._sorted_private_channels():
            if channel.get("type") != 3:
                continue
            name = channel.get("name") or self.group_name(channel)
            groups.append({
                "groupId": channel.get("id", ""),
                "channelId": channel.get("id", ""),
                "name": name,
                "abbr": self.abbr(name),  # type: ignore[attr-defined]
                "iconUrl": self.group_dm_icon_url(channel.get("id", ""), channel.get("icon")),
                "unread": self.channel_badge_count(channel),  # type: ignore[attr-defined]
                "unreadKind": self.channel_unread_kind(channel),  # type: ignore[attr-defined]
                "sortKey": last_message_sort_value(channel.get("last_message_id")),
            })
        return groups
    # Guild channel list
    def format_guild_channel_list(self, guild_id: str) -> list[dict[str, Any]]:
        channels = self.guild_channels.get(guild_id, [])  # type: ignore[attr-defined]
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
            if not self.is_visible_guild_channel(guild_id, channel):  # type: ignore[attr-defined]
                continue
            category = category_for_channel(channel) or {}
            parent = thread_parent(channel)
            parent_id = str(channel.get("parent_id", "") or "")
            formatted.append({
                "channelId": channel.get("id", ""),
                "categoryId": category.get("id", "uncategorized"),
                "category": category.get("name", "Channels"),
                "name": channel.get("name", ""),
                "channelType": self.channel_type_name(channel_type),
                "channelGlyph": self.channel_type_glyph(channel_type),
                "channelIconName": self.channel_type_icon(channel_type),
                "openable": self.channel_is_openable(channel),
                "unread": self.channel_badge_count(channel),  # type: ignore[attr-defined]
                "unreadKind": self.channel_unread_kind(channel),  # type: ignore[attr-defined]
                "indentLevel": 1 if parent else 0,
                "parentChannelId": parent_id,
                "parentName": str((parent or {}).get("name", "") or ""),
            })
        return formatted
    # Guild emoji list
    def format_guild_emoji_list(self, guild_id: str) -> list[dict[str, Any]]:
        emojis = self.guild_emojis.get(guild_id, [])  # type: ignore[attr-defined]
        formatted = []
        for emoji in sorted(emojis, key=lambda entry: str(entry.get("name", "") or "").lower()):
            emoji_id = str(emoji.get("id", "") or "")
            name = str(emoji.get("name", "") or "")
            animated = bool(emoji.get("animated"))
            if not emoji_id or not name:
                continue
            formatted.append({
                "emojiId": emoji_id,
                "name": name,
                "animated": animated,
                "imageUrl": self.guild_emoji_url(emoji_id, animated),
                "code": f"<{'a' if animated else ''}:{name}:{emoji_id}>",
            })
        return formatted

    def format_channel_reference(self, channel_id: str) -> dict[str, Any]:
        channel = self.get_channel(channel_id)  # type: ignore[attr-defined]
        guild_id = self.get_guild_for_channel(channel_id) or str((channel or {}).get("guild_id", "") or "")  # type: ignore[attr-defined]
        name = self.channel_display_name(channel, with_prefix=False) if channel else ""
        channel_type = int((channel or {}).get("type", -1))
        return {
            "channelId": channel_id,
            "guildId": guild_id,
            "guildName": self.guild_name(guild_id),  # type: ignore[attr-defined]
            "name": name,
            "label": self.channel_display_name(channel, with_prefix=True) if channel else f"#{channel_id}",
            "openable": self.channel_is_openable(channel or {}),
            "channelType": self.channel_type_name(channel_type),
        }
    # Pure display / static helpers
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
    def guild_emoji_url(emoji_id: str, animated: bool = False) -> str:
        if not emoji_id:
            return ""
        ext = "gif" if animated else "png"
        return f"https://cdn.discordapp.com/emojis/{emoji_id}.{ext}?size=64&quality=lossless"

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
        return int(channel.get("type", -1)) in (0, 2, 5, 10, 11, 12)

    def channel_display_name(self, channel: dict[str, Any] | None, with_prefix: bool = True) -> str:
        if not channel:
            return "#unknown"
        channel_type = int(channel.get("type", -1))
        name = str(channel.get("name", "") or "")
        if channel_type in (0, 5, 10, 11, 12):
            return f"#{name}" if with_prefix and name else name
        return name

    def channel_label(self, channel_id: str, with_prefix: bool = True) -> str:
        channel = self.get_channel(channel_id)  # type: ignore[attr-defined]
        if channel:
            return self.channel_display_name(channel, with_prefix=with_prefix)
        return f"#{channel_id}" if with_prefix else channel_id

    def role_name(self, guild_id: str, role_id: str) -> str:
        if not guild_id or not role_id:
            return role_id
        return self.guild_role_names.get(guild_id, {}).get(role_id, role_id)  # type: ignore[attr-defined]
