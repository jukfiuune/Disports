from __future__ import annotations

import json
import re
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


class MessageFormatterMixin:
    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

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
            return self.get_guild_for_channel(channel_id) or ""  # type: ignore[attr-defined]
        return ""

    def format_message(self, message: dict[str, Any]) -> dict[str, Any]:
        author = message.get("author") or {}
        member = message.get("member") or {}
        guild_id = self.guild_id_for_message(message)
        cached_user = self.cache_user(author, member, guild_id=guild_id)  # type: ignore[attr-defined]

        display_name = self.message_display_name(cached_user, guild_id=guild_id, member=member) or "Unknown"  # type: ignore[attr-defined]
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
                        "filename": "Image",
                    }))
            elif em_type == "video":
                vid = em.get("video") or {}
                thumbnail = em.get("thumbnail") or {}
                provider = (em.get("provider") or {}).get("name", "").lower()
                url = em.get("url") or vid.get("url") or ""
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

        message_type = self._message_type_value(message.get("type"))  # type: ignore[attr-defined]
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

        raw_reactions = message.get("reactions") or []
        message_id = message.get("id", "")
        if message_id:
            self._reaction_cache[message_id] = list(raw_reactions)  # type: ignore[attr-defined]

        return {
            "messageId": message_id,
            "authorId": author.get("id", ""),
            "author": display_name,
            "initials": self.abbr(display_name, length=2),  # type: ignore[attr-defined]
            "avatarCol": self.avatar_color(author.get("id", "")),  # type: ignore[attr-defined]
            "timestamp": self.format_timestamp(message.get("timestamp")),  # type: ignore[attr-defined]
            "body": content,
            "rawBody": message.get("content", ""),
            "channelId": message.get("channel_id", ""),
            "displayKind": display_kind,
            "discordMessageType": self.MESSAGE_TYPE_NAMES.get(message_type, str(message_type)),  # type: ignore[attr-defined]
            "medias": medias,
            "replyMessageId": reply["replyMessageId"],
            "replyAuthor": reply["replyAuthor"],
            "replyBody": reply["replyBody"],
            "hasReply": reply["hasReply"],
            "forwardedLabel": forwarded["forwardedLabel"],
            "forwardedAuthor": forwarded["forwardedAuthor"],
            "forwardedBody": forwarded["forwardedBody"],
            "hasForwarded": forwarded["hasForwarded"],
            "reactionsJson": json.dumps(self.format_reactions(raw_reactions), separators=(",", ":")),  # type: ignore[attr-defined]
        }

    # ------------------------------------------------------------------
    # Media
    # ------------------------------------------------------------------

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

        result.update({
            "isMedia": True,
            "mediaUrl": url,
            "mediaPreviewUrl": proxy_url,
            "mediaWidth": int(attachment.get("width") or 0),
            "mediaHeight": int(attachment.get("height") or 0),
            "mediaContentType": content_type,
            "mediaIsGifLike": bool(attachment.get("is_gif_like")),
            "mediaFileName": attachment.get("filename", ""),
            "mediaDuration": int(attachment.get("duration_secs") or 0),
        })

        if content_type.startswith("image/"):
            result["messageType"] = "image"
            if content_type == "image/gif":
                result["mediaPreviewUrl"] = url if url else proxy_url
            else:
                result["mediaPreviewUrl"] = MessageFormatterMixin.build_image_preview_url(
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

    # ------------------------------------------------------------------
    # Reply / forwarded
    # ------------------------------------------------------------------

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
        cached_user = self.cache_user(author, member, guild_id=guild_id)  # type: ignore[attr-defined]
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

        result.update({
            "hasReply": True,
            "replyMessageId": referenced_message.get("id", ""),
            "replyAuthor": self.message_display_name(cached_user, guild_id=guild_id, member=member) or "Unknown",  # type: ignore[attr-defined]
            "replyBody": content,
        })
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
        cached_user = self.cache_user(author, message.get("member") or {}, guild_id=guild_id) if author else {}  # type: ignore[attr-defined]
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

        result.update({
            "hasForwarded": True,
            "forwardedLabel": "Forwarded",
            "forwardedAuthor": self.message_display_name(cached_user, guild_id=guild_id) or self.display_name(cached_user) or "",  # type: ignore[attr-defined]
            "forwardedBody": content,
            "media": media,
        })
        return result

    # ------------------------------------------------------------------
    # System messages
    # ------------------------------------------------------------------

    def format_system_message(
        self,
        message: dict[str, Any],
        user: dict[str, Any],
        message_type: int,
    ) -> str:
        guild_id = self.guild_id_for_message(message)
        user_name = self.message_display_name(user, guild_id=guild_id, member=message.get("member") or {}) or "Someone"  # type: ignore[attr-defined]
        guild_name = ((message.get("guild") or {}).get("name")) or ""
        content = self.render_message_content(
            message.get("content", ""),
            message.get("mentions", []) or [],
            guild_id=guild_id,
            rich=False,
        ).strip()

        if content == "[nudge]":
            if user.get("id") and user.get("id") == (self.me or {}).get("id"):  # type: ignore[attr-defined]
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

    # ------------------------------------------------------------------
    # Typing
    # ------------------------------------------------------------------

    def format_typing(self, payload: dict[str, Any]) -> dict[str, Any]:
        user_id = str(payload.get("user_id", "") or "")
        guild_id = str(payload.get("guild_id", "") or "")
        if not guild_id:
            guild_id = self.get_guild_for_channel(str(payload.get("channel_id", "") or "")) or ""  # type: ignore[attr-defined]
        user = self.users.get(user_id, {})  # type: ignore[attr-defined]
        member = payload.get("member", {}) or {}
        if member and isinstance(member.get("user"), dict):
            user = self.cache_user(member.get("user") or {}, member, guild_id=guild_id)  # type: ignore[attr-defined]
        elif user and member:
            user = self.cache_user(user, member, guild_id=guild_id)  # type: ignore[attr-defined]
        author = self.message_display_name(user, guild_id=guild_id, member=member) or member.get("nick") or "Someone"  # type: ignore[attr-defined]
        return {
            "userId": user_id,
            "author": author,
            "channelId": payload.get("channel_id", ""),
        }

    # ------------------------------------------------------------------
    # Mention resolution
    # ------------------------------------------------------------------

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
            member = mention.get("member")
            cached = self.cache_user(mention, member, guild_id=guild_id)  # type: ignore[attr-defined]
            mention_names[user_id] = self.message_display_name(cached, guild_id=guild_id, member=member) or user_id  # type: ignore[attr-defined]

        def repl(match: re.Match[str]) -> str:
            user_id = match.group(1)
            return f"@{mention_names.get(user_id, user_id)}"

        return MENTION_RE.sub(repl, content)

    # ------------------------------------------------------------------
    # Rich content renderer
    # ------------------------------------------------------------------

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
            cached = self.cache_user(mention, member, guild_id=guild_id)  # type: ignore[attr-defined]
            mention_names[user_id] = self.message_display_name(cached, guild_id=guild_id, member=member) or user_id  # type: ignore[attr-defined]

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
            src = html.escape(self.guild_emoji_url(emoji_id, animated), quote=True)  # type: ignore[attr-defined]
            return f'<img src="{src}" alt="{alt}" width="{emoji_size}" height="{emoji_size}"/>'

        user_id = match.group("user_id")
        if user_id:
            user_name = f"@{mention_names.get(user_id, user_id)}"
            return html.escape(user_name) if rich else user_name

        role_id = match.group("role_id")
        if role_id:
            role_name = f"@{self.role_name(guild_id, role_id)}"  # type: ignore[attr-defined]
            return html.escape(role_name) if rich else role_name

        channel_id = match.group("channel_id")
        if channel_id:
            label = self.channel_label(channel_id)  # type: ignore[attr-defined]
            if not rich:
                return label
            href = html.escape(f"disports://channel/{channel_id}", quote=True)
            return f'<a href="{href}">{html.escape(label)}</a>'

        return html.escape(match.group(0)) if rich else match.group(0)

    # ------------------------------------------------------------------
    # Mentions-me check
    # ------------------------------------------------------------------

    def message_mentions_me(self, message: dict[str, Any]) -> bool:
        me_id = str((self.me or {}).get("id", "") or "")  # type: ignore[attr-defined]
        if not me_id:
            return False

        if bool(message.get("mention_everyone")):
            return True

        for mention in message.get("mentions", []) or []:
            if str(mention.get("id", "") or "") == me_id:
                return True

        guild_id = str(message.get("guild_id", "") or "")
        if guild_id:
            member = self.guild_members.get(guild_id) or {}  # type: ignore[attr-defined]
            my_roles = {str(role_id) for role_id in (member.get("roles") or []) if role_id is not None}
            for role_id in message.get("mention_roles", []) or []:
                if str(role_id) in my_roles:
                    return True

        return False
