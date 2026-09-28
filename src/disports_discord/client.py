from __future__ import annotations

import re
import time
from typing import Any, Callable
from urllib.parse import quote

from .emoji_catalog import unicode_emoji_catalog
from .gateway import DiscordGateway
from .http import DiscordHTTP, DiscordHTTPError, DiscordNetworkError
from .notification_text import notification_for
from offline_cache import OfflineCache
from .remote_auth import DiscordRemoteAuth
from .state import DiscordState


class DiscordClient:
    def __init__(self, emitter: Callable[[str, dict[str, Any]], None] | None = None) -> None:
        self.http = DiscordHTTP()
        self.state = DiscordState()
        self.emitter = emitter
        self.gateway: DiscordGateway | None = None
        self.remote_auth: DiscordRemoteAuth | None = None
        self._gateway_ready = False
        self.cache = OfflineCache()
        # Snapshot writes are throttled: unread badges change on every
        # message, and re-serializing the whole session each time on the
        # gateway thread is too slow for busy servers.
        self._cache_dirty: set[str] = set()
        self._cache_saved_at: dict[str, float] = {}

    def login(self, token: str) -> dict[str, Any]:
        self.stop_qr_login()
        # Reopening the UI while the background daemon is connected must attach
        # to the existing session. Re-authenticating here used to wipe READY
        # state, then connect_gateway() replaced the live gateway entirely.
        if self.http.token == token and self.state.me:
            print(
                "session: reusing authenticated state and existing gateway",
                flush=True,
            )
            return {
                "ok": True,
                "username": self.state.display_name(self.state.me),
                "id": self.state.me.get("id", ""),
            }
        if self.gateway:
            self.gateway.stop()
            self.gateway = None
        self._gateway_ready = False
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
        except DiscordNetworkError as exc:
            return {
                "ok": False,
                "error": f"Discord is temporarily unreachable: {exc}",
                "retryable": True,
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
            # DiscordGateway owns a persistent reconnect loop. start() is
            # idempotent while that loop is alive, so preserve its session.
            print("session: attaching to existing gateway", flush=True)
            self.gateway.start()
            if self._gateway_ready:
                print("session: delivering cached READY snapshot", flush=True)
                snapshot = self.state.format_ready_payload()
                snapshot["cached"] = True
                self._emit("ready", snapshot)
                self._emit("connection_status", {"ready": self.gateway.connected})
            return True
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
        self._gateway_ready = False
        self._cache_dirty.clear()
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
            except (DiscordHTTPError, DiscordNetworkError):
                return None

        def fetch_member():
            if not me_id:
                return None
            try:
                return self.http.request("GET", f"guilds/{guild_id}/members/{me_id}")
            except (DiscordHTTPError, DiscordNetworkError):
                return None

        def fetch_channels():
            try:
                return self.http.request("GET", f"guilds/{guild_id}/channels") or []
            except DiscordNetworkError:
                return None
            except DiscordHTTPError:
                return []

        def fetch_threads():
            try:
                return self.http.request("GET", f"guilds/{guild_id}/threads/active") or {}
            except (DiscordHTTPError, DiscordNetworkError):
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

        if channels is None:
            return self.cache.load_guild_channels(guild_id)

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
        formatted = self.state.format_guild_channel_list(guild_id)
        self.cache.save_guild_channels(guild_id, formatted)
        return formatted

    def fetch_guild_emojis(self, guild_id: str) -> list[dict[str, Any]]:
        if not guild_id:
            return []
        if guild_id not in self.state.guild_emojis:
            try:
                emojis = self.http.request("GET", f"guilds/{guild_id}/emojis") or []
            except (DiscordHTTPError, DiscordNetworkError):
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
        try:
            messages = self.http.request(
                "GET",
                f"channels/{channel_id}/messages",
                params=params,
            )
        except DiscordNetworkError:
            return self.cache.load_messages(channel_id) if not before else []
        self._request_missing_members(channel_id, messages or [])
        formatted = self.state.format_messages(messages or [])
        if not before:
            self.cache.save_messages(
                channel_id,
                formatted,
                self.state.format_channel_reference(channel_id),
            )
        return formatted

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
        formatted = self.state.format_message(message)
        self.cache.upsert_message(channel_id, formatted)
        return {"ok": True, "message": formatted}

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
        formatted = self.state.format_message(message)
        self.cache.upsert_message(channel_id, formatted, insert_if_missing=False)
        return {"ok": True, "message": formatted}

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
        self.cache.remove_messages(channel_id, [message_id])
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
        print(
            f"notification: resolve channel={channel_id} cache={'hit' if channel else 'miss'}",
            flush=True,
        )
        if not channel:
            try:
                channel = self.http.request("GET", f"channels/{channel_id}")
            except DiscordNetworkError:
                cached = self.cache.load_channel_reference(channel_id)
                if cached.get("openable"):
                    print(
                        f"notification: resolved channel={channel_id} from offline cache",
                        flush=True,
                    )
                    return {"ok": True, "channel": cached, "cached": True}
                return {"ok": False, "error": "Channel is unavailable while offline."}
            except DiscordHTTPError as exc:
                return {"ok": False, "error": self._api_error(exc)}
            guild_id = str((channel or {}).get("guild_id", "") or "")
            if guild_id:
                existing = list(self.state.guild_channels.get(guild_id, []))
                if not any(str(entry.get("id", "") or "") == channel_id for entry in existing):
                    existing.append(channel)
                    self.state.set_guild_channels(guild_id, existing)
            elif channel:
                self.state.upsert_private_channel(channel)

            print(
                f"notification: fetched channel={channel_id} "
                f"type={(channel or {}).get('type', 'unknown')} "
                f"guild={(channel or {}).get('guild_id', '') or 'dm'}",
                flush=True,
            )

        guild_id = str((channel or {}).get("guild_id", "") or "") or self.state.get_guild_for_channel(channel_id) or ""
        if guild_id and not self.state.guild_name(guild_id):
            try:
                guild_data = self.http.request("GET", f"guilds/{guild_id}")
            except (DiscordHTTPError, DiscordNetworkError):
                guild_data = None
            if guild_data:
                self.state.set_guild_context(guild_id, guild_data, self.state.guild_members.get(guild_id))

        reference = self.state.format_channel_reference(channel_id)
        if not reference.get("openable"):
            print(
                f"notification: channel not openable channel={channel_id} "
                f"type={reference.get('channelType', 'unknown')}",
                flush=True,
            )
            return {"ok": False, "error": "This channel type is not openable yet.", "channel": reference}
        self.cache.update_channel_reference(channel_id, reference)
        print(
            f"notification: resolved channel={channel_id} "
            f"type={reference.get('channelType', 'unknown')} "
            f"guild={reference.get('guildId') or 'dm'}",
            flush=True,
        )
        return {"ok": True, "channel": reference}

    def channel_info(self, channel_id: str) -> dict[str, Any]:
        resolved = self.resolve_channel(channel_id)
        if not resolved.get("ok"):
            return resolved

        info = self.state.format_channel_info(channel_id)
        if info:
            return {"ok": True, "info": info, "cached": bool(resolved.get("cached"))}

        reference = resolved.get("channel") or self.cache.load_channel_reference(channel_id)
        ready = self.cache.load_ready()
        for contact in ready.get("dmContacts", []) or []:
            if str(contact.get("channelId", "") or "") == str(channel_id):
                return {
                    "ok": True,
                    "cached": True,
                    "info": {
                        "kind": "user",
                        "channelId": channel_id,
                        "name": contact.get("name", ""),
                        "iconUrl": contact.get("iconUrl", ""),
                        "status": contact.get("status", "offline"),
                        "userId": contact.get("contactId", ""),
                        "blocked": bool(contact.get("blocked")),
                        "members": [],
                    },
                }
        for group in ready.get("dmGroups", []) or []:
            if str(group.get("channelId", "") or "") == str(channel_id):
                return {
                    "ok": True,
                    "cached": True,
                    "info": {
                        "kind": "group",
                        "channelId": channel_id,
                        "name": group.get("name", ""),
                        "iconUrl": group.get("iconUrl", ""),
                        "memberCount": 0,
                        "members": [],
                    },
                }
        return {
            "ok": True,
            "cached": True,
            "info": {
                "kind": "channel",
                "channelId": channel_id,
                "name": reference.get("name", ""),
                "channelType": reference.get("channelType", "unknown"),
                "guildId": reference.get("guildId", ""),
                "guildName": reference.get("guildName", ""),
                "iconUrl": "",
                "category": "",
                "topic": "",
                "nsfw": False,
                "members": [],
            },
        }

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
            self._gateway_ready = True
            ready_payload = self.state.format_ready_payload()
            self.cache.save_ready(ready_payload)
            self._cache_dirty.discard("ready")
            self._cache_saved_at["ready"] = time.monotonic()
            self._emit("ready", ready_payload)
            return

        if event_type == "RESUMED":
            self._emit("connection_status", {"ready": True})
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
                
            formatted_message = self.state.format_message(data)
            self.cache.upsert_message(str(channel_id or ""), formatted_message)
            # Notification text travels with the event (not the cache) so the
            # daemon and the app apply identical rules and wording.
            event = dict(formatted_message)
            try:
                notification = notification_for(self.state, data, formatted_message)
            except Exception as exc:
                print(f"notification: rule evaluation failed: {exc}", flush=True)
                notification = None
            event["notifySummary"] = notification["summary"] if notification else ""
            event["notifyBody"] = notification["body"] if notification else ""
            self._emit("message_create", event)
            return

        if event_type == "MESSAGE_UPDATE":
            formatted_message = self.state.format_message(data)
            formatted_message = self.cache.merge_message_update(
                str(data.get("channel_id", "") or ""),
                formatted_message,
                data,
            )
            self._emit("message_update", formatted_message)
            return

        if event_type == "MESSAGE_DELETE":
            self.cache.remove_messages(
                str(data.get("channel_id", "") or ""),
                [str(data.get("id", "") or "")],
            )
            self._emit(
                "message_delete",
                {
                    "messageId": data.get("id", ""),
                    "channelId": data.get("channel_id", ""),
                },
            )
            return

        if event_type == "MESSAGE_DELETE_BULK":
            self.cache.remove_messages(
                str(data.get("channel_id", "") or ""),
                [str(message_id) for message_id in (data.get("ids", []) or [])],
            )
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
            self._save_ready_throttled(force=True)
            self._emit("relationships_update", self.state.format_private_channel_payload())
            return

        if event_type == "RELATIONSHIP_REMOVE":
            self.state.apply_relationship_remove(data)
            self._save_ready_throttled(force=True)
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
                reactions_json = json.dumps(updated, separators=(",", ":"))
                self.cache.patch_message(
                    channel_id,
                    message_id,
                    {"reactionsJson": reactions_json},
                )
                self._emit("message_reaction", {
                    "messageId": message_id,
                    "channelId": channel_id,
                    "reactionsJson": reactions_json,
                })
            return

    def _handle_gateway_log(self, message: str) -> None:
        lowered = message.lower()
        status: dict[str, Any] | None = None
        if "gateway reconnecting" in lowered:
            delay_match = re.search(r"in (\d+)s", lowered)
            status = {
                "ready": False,
                "phase": "resume_wait" if "resume=yes" in lowered else "retry_wait",
                "retrySeconds": int(delay_match.group(1)) if delay_match else 0,
            }
        elif "gateway resuming session" in lowered:
            status = {"ready": False, "phase": "resuming"}
        elif "gateway identifying new session" in lowered:
            status = {"ready": False, "phase": "identifying"}
        elif "gateway connecting" in lowered:
            status = {"ready": False, "phase": "connecting"}
        elif "gateway error" in lowered:
            status = {"ready": False, "phase": "interrupted"}
        elif "heartbeat stopped" in lowered:
            status = {"ready": False, "phase": "heartbeat"}
        if status:
            self._emit("connection_status", status)
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
        self._save_ready_throttled()

    CACHE_SAVE_INTERVAL = 15.0

    def _throttle_due(self, key: str, force: bool) -> bool:
        now = time.monotonic()
        if not force and now - self._cache_saved_at.get(key, 0.0) < self.CACHE_SAVE_INTERVAL:
            self._cache_dirty.add(key)
            return False
        self._cache_saved_at[key] = now
        self._cache_dirty.discard(key)
        return True

    def _save_ready_throttled(self, force: bool = False) -> None:
        if not self._gateway_ready or not self._throttle_due("ready", force):
            return
        try:
            self.cache.save_ready(self.state.format_ready_payload())
        except Exception as exc:
            print(f"cache: ready snapshot save failed: {exc}", flush=True)

    def _save_guild_channels_throttled(self, guild_id: str, formatted: list, force: bool = False) -> None:
        if not self._gateway_ready or not self._throttle_due(f"guild:{guild_id}", force):
            return
        try:
            self.cache.save_guild_channels(guild_id, formatted)
        except Exception as exc:
            print(f"cache: guild channel save failed: {exc}", flush=True)

    def flush_cache(self) -> None:
        # Writes snapshots skipped by the throttle (daemon shutdown).
        if not self._gateway_ready:
            return
        for key in list(self._cache_dirty):
            if key == "ready":
                self._save_ready_throttled(force=True)
            elif key.startswith("guild:"):
                guild_id = key[len("guild:"):]
                self._save_guild_channels_throttled(
                    guild_id, self.state.format_guild_channel_list(guild_id), force=True
                )

    def _emit_guild_channels(self, guild_id: str) -> None:
        formatted = self.state.format_guild_channel_list(guild_id)
        self._save_guild_channels_throttled(guild_id, formatted)
        self._save_ready_throttled()
        self._emit(
            "guild_channels",
            {
                "guildId": guild_id,
                "list": formatted,
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
