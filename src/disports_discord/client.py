from __future__ import annotations

from typing import Any, Callable

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
        self.active_channel_id = ""

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
        self.gateway.start()
        return True

    def disconnect(self) -> bool:
        if self.gateway:
            self.gateway.stop()
            self.gateway = None
        self.active_channel_id = ""
        self.stop_qr_login()
        self.http.set_token(None)
        return True

    def start_qr_login(self) -> dict[str, Any]:
        self.stop_qr_login()
        self.remote_auth = DiscordRemoteAuth(emitter=self._emit)
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
        guild_data = None
        member_data = None
        if self.state.me and self.state.me.get("id"):
            try:
                guild_data = self.http.request("GET", f"guilds/{guild_id}")
            except DiscordHTTPError:
                guild_data = None
            try:
                member_data = self.http.request(
                    "GET",
                    f"guilds/{guild_id}/members/{self.state.me.get('id', '')}",
                )
            except DiscordHTTPError:
                member_data = None

        self.state.set_guild_context(guild_id, guild_data, member_data)
        channels = self.http.request("GET", f"guilds/{guild_id}/channels")
        self.state.set_guild_channels(guild_id, channels or [])
        self._emit(
            "guild_sidebar",
            {"guilds": self.state.format_sidebar_guild_rows()},
        )
        return self.state.format_guild_channel_list(guild_id)

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

    def ack_message(
        self,
        channel_id: str,
        message_id: str,
    ) -> dict[str, Any]:
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
        if not channel_id:
            return {"ok": False, "error": "Missing channel id."}
        self.state.mark_channel_read(channel_id, message_id or None)
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
        return {"ok": True}

    def set_active_channel(self, channel_id: str) -> bool:
        self.active_channel_id = channel_id
        if channel_id:
            guild_id = self.state.get_guild_for_channel(channel_id)
            channel = self.state.get_channel(channel_id)
            self.state.set_active_channel(channel_id)
            self._emit("channel_unread", {
                "channelId": channel_id, 
                "unread": self.state.channel_badge_count(channel) if channel else 0,
                "unreadKind": self.state.channel_unread_kind(channel) if channel else "none",
                "guildId": guild_id,
                "guildUnread": self.state.get_guild_unread_count(guild_id) if guild_id else 0,
                "guildUnreadKind": self.state.guild_unread_kind(guild_id) if guild_id else "none",
                "dmUnread": self.state.get_dm_unread_count() if not guild_id else 0
            })
        return True

    def reconnect(self) -> None:
        if self.gateway:
            self.gateway.reconnect()

    def _handle_gateway_event(self, event_type: str, data: dict[str, Any]) -> None:
        if event_type == "READY":
            self.state.apply_ready(data)
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
                    self._emit(
                        "guild_channels",
                        {
                            "guildId": guild_id,
                            "list": self.state.format_guild_channel_list(guild_id),
                        },
                    )
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

        if event_type == "MESSAGE_CREATE":
            channel_id = data.get("channel_id")
            is_private = self.state.apply_private_channel_activity(data)
            guild_id = None
            if not is_private:
                guild_id = self.state.apply_guild_channel_activity(data)

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

            if is_private:
                self._emit("private_channels", self.state.format_private_channel_payload())
            elif guild_id:
                self._emit(
                    "guild_channels",
                    {
                        "guildId": guild_id,
                        "list": self.state.format_guild_channel_list(guild_id),
                    },
                )
                
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
                guild_id = self.state.get_guild_for_channel(channel_id)
                self.state.mark_channel_read(channel_id, message_id)
                channel = self.state.get_channel(channel_id)
                self._emit("channel_unread", {
                    "channelId": channel_id,
                    "unread": self.state.channel_badge_count(channel) if channel else 0,
                    "unreadKind": self.state.channel_unread_kind(channel) if channel else "none",
                    "guildId": guild_id,
                    "guildUnread": self.state.get_guild_unread_count(guild_id) if guild_id else 0,
                    "guildUnreadKind": self.state.guild_unread_kind(guild_id) if guild_id else "none",
                    "dmUnread": self.state.get_dm_unread_count() if not guild_id else 0,
                })
            return

        if event_type == "CHANNEL_UNREAD_UPDATE":
            for entry in data.get("channel_unread_updates") or []:
                channel_id = str(entry.get("id") or "")
                message_id = str(entry.get("last_message_id") or "")
                if not channel_id or not message_id:
                    continue
                guild_id = self.state.get_guild_for_channel(channel_id)
                self.state.mark_channel_read(channel_id, message_id)
                channel = self.state.get_channel(channel_id)
                self._emit("channel_unread", {
                    "channelId": channel_id,
                    "unread": self.state.channel_badge_count(channel) if channel else 0,
                    "unreadKind": self.state.channel_unread_kind(channel) if channel else "none",
                    "guildId": guild_id,
                    "guildUnread": self.state.get_guild_unread_count(guild_id) if guild_id else 0,
                    "guildUnreadKind": self.state.guild_unread_kind(guild_id) if guild_id else "none",
                    "dmUnread": self.state.get_dm_unread_count() if not guild_id else 0,
                })
            return

        if event_type == "TYPING_START":
            self._emit("typing", self.state.format_typing(data))

    def _handle_gateway_log(self, message: str) -> None:
        self._emit("gateway_log", {"message": message})

    def _emit(self, name: str, payload: dict[str, Any]) -> None:
        if self.emitter:
            self.emitter(name, payload)

    @staticmethod
    def _api_error(exc: DiscordHTTPError) -> str:
        if exc.status == 401:
            return "Discord rejected the token."
        return f"Discord API error ({exc.status}): {exc.body}"
