from __future__ import annotations

from typing import Any, Callable
from urllib.parse import quote

from .emoji_catalog import unicode_emoji_catalog
from .gateway import DiscordGateway
from .http import DiscordHTTP, DiscordHTTPError
from .remote_auth import DiscordRemoteAuth
from .state import DiscordState


class DiscordClient:
    def __init__(self, emitter: Callable[[str, dict[str, Any]], None] | None = None) -> None:
        self.http = DiscordHTTP()
        self.state = DiscordState()
        self.emitter = emitter
        self.gateway: DiscordGateway | None = None
        self.remote_auth: DiscordRemoteAuth | None = None

    def login(self, token: str) -> dict[str, Any]:
        self.stop_qr_login()
        self.http.set_token(token)
        self.state.reset()
        try:
            me = self.http.request("GET", "users/@me")
        except DiscordHTTPError as exc:
            return {
                "ok": False,
                "error": self._api_error(exc),
                "clear_saved_token": exc.status == 401,
            }

        self.state.set_me(me)
        return {
            "ok": True,
            "username": self.state.display_name(me),
            "id": me.get("id", ""),
        }

    def connect_gateway(self) -> bool:
        if not self.http.token:
            raise RuntimeError("No Discord token set")
        if self.gateway:
            self.gateway.stop()
        self.gateway = DiscordGateway(
            self.http.token,
            self._handle_gateway_event,
            self._handle_gateway_log,
        )
        self.state._send_gateway = self.gateway.guild_subscribe_raw
        self.gateway.start()
        return True

    def disconnect(self) -> bool:
        if self.gateway:
            self.gateway.stop()
            self.gateway = None
        self.state._send_gateway = None
        self.stop_qr_login()
        self.http.set_token(None)
        return True

    def start_qr_login(self) -> dict[str, Any]:
        self.stop_qr_login()
        self.remote_auth = DiscordRemoteAuth(http=self.http, emitter=self._emit)
        try:
            self.remote_auth.start()
        except Exception as exc:
            self.remote_auth = None
            return {"ok": False, "error": f"Unable to start QR login: {exc}"}
        return {"ok": True}

    def stop_qr_login(self) -> bool:
        if self.remote_auth:
            self.remote_auth.stop()
            self.remote_auth = None
        return True

    def fetch_guild_channels(self, guild_id: str) -> list[dict[str, Any]]:
        from concurrent.futures import ThreadPoolExecutor

        me_id = (self.state.me or {}).get("id", "")

        def fetch_guild():
            try:
                return self.http.request("GET", f"guilds/{guild_id}")
            except DiscordHTTPError:
                return None

        def fetch_member():
            if not me_id:
                return None
            try:
                return self.http.request("GET", f"guilds/{guild_id}/members/{me_id}")
            except DiscordHTTPError:
                return None

        def fetch_channels():
            try:
                return self.http.request("GET", f"guilds/{guild_id}/channels") or []
            except DiscordHTTPError:
                return []

        def fetch_threads():
            try:
                return self.http.request("GET", f"guilds/{guild_id}/threads/active") or {}
            except DiscordHTTPError:
                return {}

        with ThreadPoolExecutor(max_workers=4) as executor:
            fut_guild = executor.submit(fetch_guild)
            fut_member = executor.submit(fetch_member)
            fut_channels = executor.submit(fetch_channels)
            fut_threads = executor.submit(fetch_threads)

            guild_data = fut_guild.result()
            member_data = fut_member.result()
            channels = fut_channels.result()
            active_threads = fut_threads.result()

        self.state.set_guild_context(guild_id, guild_data, member_data)
        merged_channels = self._merge_guild_channels(
            channels,
            (active_threads.get("threads") or []) if isinstance(active_threads, dict) else [],
        )
        self.state.set_guild_channels(guild_id, merged_channels)

        if self.gateway:
            self.state.subscribe_guild_channel(guild_id, "")

        self._emit(
            "guild_sidebar",
            {"guilds": self.state.format_sidebar_guild_rows()},
        )
        return self.state.format_guild_channel_list(guild_id)

    def fetch_guild_emojis(self, guild_id: str) -> list[dict[str, Any]]:
        if not guild_id:
            return []
        if guild_id not in self.state.guild_emojis:
            try:
                emojis = self.http.request("GET", f"guilds/{guild_id}/emojis") or []
            except DiscordHTTPError:
                return []
            self.state.set_guild_emojis(guild_id, emojis)
        return self.state.format_guild_emoji_list(guild_id)

    def fetch_unicode_emojis(self) -> list[dict[str, Any]]:
        return [dict(emoji) for emoji in unicode_emoji_catalog()]

    def fetch_private_channels(self) -> dict[str, Any]:
        return self.state.format_private_channel_payload()

    def fetch_messages(self, channel_id: str, limit: int = 50, before: str = "") -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": limit}
        if before:
            params["before"] = before
        messages = self.http.request(
            "GET",
            f"channels/{channel_id}/messages",
            params=params,
        )
        self._request_missing_members(channel_id, messages or [])
        return self.state.format_messages(messages or [])

    def send_message(
        self,
        channel_id: str,
        content: str,
        reply_message_id: str = "",
    ) -> dict[str, Any]:
        if not content.strip():
            return {"ok": False, "error": "Message content cannot be empty."}
        payload: dict[str, Any] = {"content": content}
        if reply_message_id:
            payload["message_reference"] = {
                "message_id": reply_message_id,
                "fail_if_not_exists": False,
            }
            payload["allowed_mentions"] = {
                "parse": ["users", "roles", "everyone"],
                "replied_user": False,
            }
        try:
            message = self.http.request(
                "POST",
                f"channels/{channel_id}/messages",
                json_body=payload,
            )
        except DiscordHTTPError as exc:
            return {"ok": False, "error": self._api_error(exc)}
        if self.state.apply_private_channel_activity(message):
            self._emit("private_channels", self.state.format_private_channel_payload())
        return {"ok": True, "message": self.state.format_message(message)}

    def edit_message(
        self,
        channel_id: str,
        message_id: str,
        content: str,
    ) -> dict[str, Any]:
        if not content.strip():
            return {"ok": False, "error": "Message content cannot be empty."}
        try:
            message = self.http.request(
                "PATCH",
                f"channels/{channel_id}/messages/{message_id}",
                json_body={"content": content},
            )
        except DiscordHTTPError as exc:
            return {"ok": False, "error": self._api_error(exc)}
        return {"ok": True, "message": self.state.format_message(message)}

    def delete_message(
        self,
        channel_id: str,
        message_id: str,
    ) -> dict[str, Any]:
        try:
            self.http.request(
                "DELETE",
                f"channels/{channel_id}/messages/{message_id}",
            )
        except DiscordHTTPError as exc:
            return {"ok": False, "error": self._api_error(exc)}
        return {"ok": True}

    def add_reaction(
        self,
        channel_id: str,
        message_id: str,
        emoji: str,
    ) -> dict[str, Any]:
        if not channel_id or not message_id or not emoji:
            return {"ok": False, "error": "Missing required parameters."}
        try:
            self.http.request(
                "PUT",
                f"channels/{channel_id}/messages/{message_id}/reactions/{quote(emoji, safe='')}/@me",
            )
        except DiscordHTTPError as exc:
            return {"ok": False, "error": self._api_error(exc)}
        return {"ok": True}

    def remove_reaction(
        self,
        channel_id: str,
        message_id: str,
        emoji: str,
    ) -> dict[str, Any]:
        if not channel_id or not message_id or not emoji:
            return {"ok": False, "error": "Missing required parameters."}
        try:
            self.http.request(
                "DELETE",
                f"channels/{channel_id}/messages/{message_id}/reactions/{quote(emoji, safe='')}/0/@me",
            )
        except DiscordHTTPError as exc:
            return {"ok": False, "error": self._api_error(exc)}
        return {"ok": True}

    def ack_message(
        self,
        channel_id: str,
        message_id: str,
    ) -> dict[str, Any]:
        """Send a message acknowledgment to the Discord API."""
        try:
            self.http.request(
                "POST",
                f"channels/{channel_id}/messages/{message_id}/ack",
                json_body={"token": None},
            )
        except DiscordHTTPError as exc:
            return {"ok": False, "error": self._api_error(exc)}
        return {"ok": True}

    def mark_seen(
        self,
        channel_id: str,
        message_id: str,
    ) -> dict[str, Any]:
        """Update local read state for a channel without sending an API acknowledgment."""
        if not channel_id:
            return {"ok": False, "error": "Missing channel id."}
        self.state.mark_channel_read(channel_id, message_id or None)
        self._emit_channel_unread(channel_id)
        return {"ok": True}

    def set_active_channel(self, channel_id: str) -> bool:
        if channel_id:
            self.state.set_active_channel(channel_id)
            self._emit_channel_unread(channel_id)
            guild_id = self.state.get_guild_for_channel(channel_id)
            if guild_id and self.gateway:
                self.state.subscribe_guild_channel(guild_id, channel_id)
        else:
            self.state.set_active_channel("")
        return True

    def resolve_channel(self, channel_id: str) -> dict[str, Any]:
        if not channel_id:
            return {"ok": False, "error": "Missing channel id."}

        channel = self.state.get_channel(channel_id)
        if not channel:
            try:
                channel = self.http.request("GET", f"channels/{channel_id}")
            except DiscordHTTPError as exc:
                return {"ok": False, "error": self._api_error(exc)}
            guild_id = str((channel or {}).get("guild_id", "") or "")
            if guild_id:
                existing = list(self.state.guild_channels.get(guild_id, []))
                if not any(str(entry.get("id", "") or "") == channel_id for entry in existing):
                    existing.append(channel)
                    self.state.set_guild_channels(guild_id, existing)

        guild_id = str((channel or {}).get("guild_id", "") or "") or self.state.get_guild_for_channel(channel_id) or ""
        if guild_id and not self.state.guild_name(guild_id):
            try:
                guild_data = self.http.request("GET", f"guilds/{guild_id}")
            except DiscordHTTPError:
                guild_data = None
            if guild_data:
                self.state.set_guild_context(guild_id, guild_data, self.state.guild_members.get(guild_id))

        reference = self.state.format_channel_reference(channel_id)
        if not reference.get("openable"):
            return {"ok": False, "error": "This channel type is not openable yet.", "channel": reference}
        return {"ok": True, "channel": reference}

    def reconnect(self) -> None:
        if self.gateway:
            self.gateway.reconnect()

    def _handle_gateway_event(self, event_type: str, data: dict[str, Any]) -> None:
        if data is None:
            data = {}
        elif not isinstance(data, dict):
            self._handle_gateway_log(f"Ignoring unexpected payload for {event_type}: {type(data).__name__}")
            return

        if event_type == "READY":
            self.state.apply_ready(data)
            self.state.apply_relationships(data.get("relationships") or [])
            self._emit("ready", self.state.format_ready_payload())
            return

        if event_type in ("USER_SETTINGS_UPDATE", "user_settings_update"):
            if self.state.merge_user_settings_gateway_update(data):
                self._emit(
                    "guild_sidebar",
                    {"guilds": self.state.format_sidebar_guild_rows()},
                )
            return

        if event_type == "USER_GUILD_SETTINGS_UPDATE":
            if self.state.merge_user_guild_settings_update(data):
                guild_id = str(data.get("guild_id", "") or "")
                if guild_id:
                    self._emit_guild_channels(guild_id)
                self._emit(
                    "guild_sidebar",
                    {"guilds": self.state.format_sidebar_guild_rows()},
                )
            return

        if event_type == "PRESENCE_UPDATE":
            self.state.apply_presence(data)
            self._emit(
                "presence",
                {
                    "userId": (data.get("user") or {}).get("id", ""),
                    "status": data.get("status", "offline"),
                },
            )
            return

        if event_type == "GUILD_MEMBERS_CHUNK":
            guild_id = self.state.apply_guild_members_chunk(data)
            if guild_id:
                self._emit(
                    "guild_member_chunk",
                    {
                        "guildId": guild_id,
                    },
                )
            return

        if event_type == "GUILD_MEMBER_LIST_UPDATE":
            self.state.apply_member_list_update(data)
            guild_id = str(data.get("guild_id") or "")
            self._emit(
                "member_list_update",
                {
                    "guildId": guild_id,
                    "listId": str(data.get("id") or "everyone"),
                    "memberCount": int(data.get("member_count") or 0),
                    "onlineCount": int(data.get("online_count") or 0),
                },
            )
            return

        if event_type in ("CHANNEL_CREATE", "CHANNEL_UPDATE", "THREAD_CREATE", "THREAD_UPDATE"):
            guild_id = self.state.upsert_guild_channel(data)
            if guild_id:
                self._emit_guild_channels(guild_id)
            return

        if event_type in ("CHANNEL_DELETE", "THREAD_DELETE"):
            guild_id = self.state.remove_guild_channel(
                str(data.get("id", "") or ""),
                str(data.get("guild_id", "") or ""),
            )
            if guild_id:
                self._emit_guild_channels(guild_id)
            return

        if event_type == "MESSAGE_CREATE":
            channel_id = data.get("channel_id")
            is_private = self.state.apply_private_channel_activity(data)
            guild_id = None
            if not is_private:
                guild_id = self.state.apply_guild_channel_activity(data)

            channel = self.state.get_channel(channel_id)
            self._emit_channel_unread(channel_id)

            if is_private:
                self._emit("private_channels", self.state.format_private_channel_payload())
            elif guild_id:
                self._emit_guild_channels(guild_id)
                
            self._emit("message_create", self.state.format_message(data))
            return

        if event_type == "MESSAGE_UPDATE":
            self._emit("message_update", self.state.format_message(data))
            return

        if event_type == "MESSAGE_DELETE":
            self._emit(
                "message_delete",
                {
                    "messageId": data.get("id", ""),
                    "channelId": data.get("channel_id", ""),
                },
            )
            return

        if event_type == "MESSAGE_DELETE_BULK":
            self._emit(
                "message_bulk_delete",
                {
                    "messageIds": data.get("ids", []) or [],
                    "channelId": data.get("channel_id", ""),
                },
            )
            return

        if event_type == "MESSAGE_ACK":
            channel_id = data.get("channel_id")
            message_id = data.get("message_id")
            if channel_id and message_id:
                self.state.mark_channel_read(channel_id, message_id)
                self._emit_channel_unread(channel_id)
            return

        if event_type == "CHANNEL_UNREAD_UPDATE":
            for entry in data.get("channel_unread_updates") or []:
                channel_id = str(entry.get("id") or "")
                message_id = str(entry.get("last_message_id") or "")
                if not channel_id or not message_id:
                    continue
                self.state.mark_channel_read(channel_id, message_id)
                self._emit_channel_unread(channel_id)
            return

        if event_type == "TYPING_START":
            self._emit("typing", self.state.format_typing(data))
            return

        if event_type == "RELATIONSHIP_ADD":
            self.state.apply_relationship_add(data)
            self._emit("relationships_update", self.state.format_private_channel_payload())
            return

        if event_type == "RELATIONSHIP_REMOVE":
            self.state.apply_relationship_remove(data)
            self._emit("relationships_update", self.state.format_private_channel_payload())
            return

        if event_type in (
            "MESSAGE_REACTION_ADD",
            "MESSAGE_REACTION_REMOVE",
            "MESSAGE_REACTION_REMOVE_ALL",
            "MESSAGE_REACTION_REMOVE_EMOJI",
        ):
            message_id = str(data.get("message_id") or "")
            channel_id = str(data.get("channel_id") or "")
            my_id = str((self.state.me or {}).get("id") or "")
            updated = self.state.update_message_reactions(
                message_id, event_type, data, my_user_id=my_id
            )
            if updated is not None:
                import json
                self._emit("message_reaction", {
                    "messageId": message_id,
                    "channelId": channel_id,
                    "reactionsJson": json.dumps(updated, separators=(",", ":")),
                })
            return

    def _handle_gateway_log(self, message: str) -> None:
        self._emit("gateway_log", {"message": message})

    def _emit(self, name: str, payload: dict[str, Any]) -> None:
        if self.emitter:
            self.emitter(name, payload)

    def set_preference(self, key: str, value: str) -> None:
        self.state.client_preferences[key] = value

    def _emit_channel_unread(self, channel_id: str) -> None:
        guild_id = self.state.get_guild_for_channel(channel_id)
        channel = self.state.get_channel(channel_id)
        self._emit("channel_unread", {
            "channelId": channel_id,
            "unread": self.state.channel_badge_count(channel) if channel else 0,
            "unreadKind": self.state.channel_unread_kind(channel) if channel else "none",
            "guildId": guild_id,
            "guildUnread": self.state.get_guild_unread_count(guild_id) if guild_id else 0,
            "guildUnreadKind": self.state.guild_unread_kind(guild_id) if guild_id else "none",
            "dmUnread": self.state.get_dm_unread_count() if not guild_id else 0
        })

    def _emit_guild_channels(self, guild_id: str) -> None:
        self._emit(
            "guild_channels",
            {
                "guildId": guild_id,
                "list": self.state.format_guild_channel_list(guild_id),
            },
        )

    def _request_missing_members(
        self,
        channel_id: str,
        messages: list[dict[str, Any]],
    ) -> None:
        if not self.gateway or not messages:
            return
        guild_id = self.state.get_guild_for_channel(channel_id)
        if not guild_id:
            return

        missing_ids: list[str] = []
        seen_ids: set[str] = set()

        def add_user_id(user_id: str) -> None:
            sid = str(user_id or "")
            if not sid or sid in seen_ids:
                return
            seen_ids.add(sid)
            if self.state.has_guild_member(guild_id, sid):
                return
            missing_ids.append(sid)

        for message in messages:
            if not isinstance(message, dict):
                continue
            add_user_id(str((message.get("author") or {}).get("id", "") or ""))
            referenced = message.get("referenced_message") or {}
            if isinstance(referenced, dict):
                add_user_id(str((referenced.get("author") or {}).get("id", "") or ""))
            for snapshot in message.get("message_snapshots") or []:
                snap_msg = (snapshot or {}).get("message") or {}
                if isinstance(snap_msg, dict):
                    add_user_id(str((snap_msg.get("author") or {}).get("id", "") or ""))
            for mention in message.get("mentions", []) or []:
                if isinstance(mention, dict):
                    add_user_id(str(mention.get("id", "") or ""))

        if missing_ids:
            self.gateway.request_guild_members(guild_id, missing_ids)

    @staticmethod
    def _merge_guild_channels(
        channels: list[dict[str, Any]],
        threads: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for channel in (channels or []) + (threads or []):
            if not isinstance(channel, dict):
                continue
            channel_id = str(channel.get("id", "") or "")
            if not channel_id or channel_id in seen_ids:
                continue
            seen_ids.add(channel_id)
            merged.append(channel)
        return merged

    @staticmethod
    def _api_error(exc: DiscordHTTPError) -> str:
        if exc.status == 401:
            return "Discord rejected the token."
        return exc.display_message()
