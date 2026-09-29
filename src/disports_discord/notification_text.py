# Decides whether a new message deserves a notification and renders its text.
# Shared by the background daemon (Postal) and the app (live notifications),
# so both paths apply the same rules and produce the same card.
from __future__ import annotations

import html
import re
from typing import Any

BODY_MAX_LEN = 200


def plain_text(rich: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", str(rich or ""))
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).strip()


def media_label(medias: list) -> str:
    for media in medias or []:
        kind = str((media or {}).get("messageType") or "")
        if kind == "image":
            return "📷 Photo"
        if kind == "video":
            return "🎥 Video"
        if kind == "audio":
            return "🎵 Audio"
        if kind == "link":
            return "🔗 Link"
        if kind:
            return "📎 File"
    return ""


def _summary(state, channel_id: str, author: str, text: str) -> tuple[str, str]:
    channel = state.get_channel(channel_id) or {}
    guild_id = state.get_guild_for_channel(channel_id) or ""
    if guild_id:
        guild_name = state.guild_name(guild_id) or ""
        channel_name = str(channel.get("name") or "channel")
        summary = f"{guild_name} • #{channel_name}" if guild_name else f"#{channel_name}"
        return summary, f"{author}: {text}"
    group_name = str(channel.get("name") or "").strip()
    if not group_name and channel.get("recipients") and int(channel.get("type", -1)) == 3:
        group_name = state.group_name(channel)
    if group_name and group_name != author:
        return group_name, f"{author}: {text}"
    return author, text


def _suppressed_mention(state, guild_id: str, raw: dict[str, Any]) -> bool:
    # Honour "Suppress @everyone and @here" / "Suppress all role @mentions"
    # when those are the only reason the message mentions us.
    me_id = str((state.me or {}).get("id") or "")
    if any(str(m.get("id") or "") == me_id for m in raw.get("mentions") or []):
        return False
    settings = state.guild_setting(guild_id) or {}
    everyone = bool(raw.get("mention_everyone"))
    if everyone and not settings.get("suppress_everyone"):
        return False
    roles = raw.get("mention_roles") or []
    if roles and not settings.get("suppress_roles"):
        return False
    return True


def notification_for(state, raw: dict[str, Any], formatted: dict[str, Any]) -> dict[str, str] | None:
    """Returns {"summary", "body"} when raw MESSAGE_CREATE should notify."""
    me_id = str((state.me or {}).get("id") or "")
    if not me_id:
        return None
    if str(formatted.get("displayKind") or "") == "system":
        return None
    author_id = str((raw.get("author") or {}).get("id") or "")
    if not author_id or author_id == me_id or state.is_blocked(author_id):
        return None
    channel_id = str(raw.get("channel_id") or "")
    if not channel_id:
        return None

    channel = state.get_channel(channel_id) or {}
    guild_id = state.get_guild_for_channel(channel_id) or str(raw.get("guild_id") or "")
    if guild_id:
        if not state.message_mentions_me(raw):
            return None
        if state.is_guild_muted(guild_id):
            return None
        if channel and state.is_channel_muted(channel):
            return None
        if _suppressed_mention(state, guild_id, raw):
            return None
    elif channel and state.is_channel_muted(channel):
        return None

    text = plain_text(formatted.get("body") or "")
    if not text:
        text = media_label(formatted.get("medias") or [])
    if not text:
        return None

    summary, body = _summary(state, channel_id, str(formatted.get("author") or "Unknown"), text)
    if len(body) > BODY_MAX_LEN:
        body = body[: BODY_MAX_LEN - 1].rstrip() + "…"
    return {"summary": summary, "body": body}
