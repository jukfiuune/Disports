from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import daemon_common


MAX_MESSAGES_PER_CHANNEL = 50


def _snowflake(value: Any) -> int:
    try:
        return int(str(value or "0"))
    except ValueError:
        return 0


class OfflineCache:
    """Small shared SQLite cache for instant, read-only startup hydration."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (daemon_common.data_dir() / "offline-cache.sqlite3")
        self._init_lock = threading.Lock()
        self._initialized = False
        # One connection per thread: the gateway thread writes on every
        # message, so reopening (and re-running the pragmas) each time is
        # too expensive on phones.
        self._local = threading.local()

    def _connect(self) -> sqlite3.Connection:
        connection = getattr(self._local, "connection", None)
        if connection is not None:
            return connection
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Autocommit mode: transactions are opened explicitly below.
        connection = sqlite3.connect(str(self.path), timeout=5.0, isolation_level=None)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=5000")
        self._initialize(connection)
        self._local.connection = connection
        return connection

    @contextmanager
    def _transaction(self):
        # BEGIN IMMEDIATE takes the write lock up front, so read-modify-write
        # sequences from the gateway and RPC threads (or the app and daemon
        # processes) cannot overwrite each other.
        connection = self._connect()
        connection.execute("BEGIN IMMEDIATE")
        try:
            yield connection
        except BaseException:
            connection.execute("ROLLBACK")
            raise
        connection.execute("COMMIT")

    def _initialize(self, connection: sqlite3.Connection) -> None:
        if self._initialized:
            return
        with self._init_lock:
            if self._initialized:
                return
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS snapshots (
                    cache_key TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    updated_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS guild_channels (
                    guild_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    updated_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS channel_messages (
                    channel_id TEXT PRIMARY KEY,
                    channel_reference TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    last_opened_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                );
                """
            )
            self._initialized = True

    @staticmethod
    def _encode(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _decode(raw: str, fallback: Any) -> Any:
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return fallback

    # READY snapshot

    def save_ready(self, payload: dict[str, Any]) -> None:
        if not payload or not (payload.get("me") or {}).get("id"):
            return
        self._connect().execute(
            "INSERT OR REPLACE INTO snapshots(cache_key, payload, updated_at) VALUES(?, ?, ?)",
            ("ready", self._encode(payload), int(time.time())),
        )

    def load_ready(self) -> dict[str, Any]:
        row = self._connect().execute(
            "SELECT payload, updated_at FROM snapshots WHERE cache_key = ?", ("ready",)
        ).fetchone()
        if not row:
            return {}
        payload = self._decode(row[0], {})
        if not isinstance(payload, dict):
            return {}
        for contact in payload.get("dmContacts", []) or []:
            if isinstance(contact, dict):
                contact["status"] = "offline"
        payload["cachedAt"] = int(row[1] or 0)
        return payload

    # Guild channel lists

    def save_guild_channels(self, guild_id: str, channels: list[dict[str, Any]]) -> None:
        if not guild_id:
            return
        self._connect().execute(
            "INSERT OR REPLACE INTO guild_channels(guild_id, payload, updated_at) VALUES(?, ?, ?)",
            (guild_id, self._encode(channels or []), int(time.time())),
        )

    def load_guild_channels(self, guild_id: str) -> list[dict[str, Any]]:
        if not guild_id:
            return []
        row = self._connect().execute(
            "SELECT payload FROM guild_channels WHERE guild_id = ?", (guild_id,)
        ).fetchone()
        value = self._decode(row[0], []) if row else []
        return value if isinstance(value, list) else []

    # Channel messages

    def _read_channel(self, connection: sqlite3.Connection, channel_id: str):
        # Returns (messages, reference), or None when the channel is not cached.
        row = connection.execute(
            "SELECT payload, channel_reference FROM channel_messages WHERE channel_id = ?",
            (channel_id,),
        ).fetchone()
        if not row:
            return None
        messages = self._decode(row[0], [])
        reference = self._decode(row[1], {})
        return (
            messages if isinstance(messages, list) else [],
            reference if isinstance(reference, dict) else {},
        )

    def _write_channel(
        self,
        connection: sqlite3.Connection,
        channel_id: str,
        messages: list[dict[str, Any]],
        reference: dict[str, Any],
    ) -> None:
        now = int(time.time())
        connection.execute(
            """
            INSERT OR REPLACE INTO channel_messages(
                channel_id, channel_reference, payload, last_opened_at, updated_at
            ) VALUES(?, ?, ?, ?, ?)
            """,
            (
                channel_id,
                self._encode(reference or {}),
                self._encode(list(messages or [])[:MAX_MESSAGES_PER_CHANNEL]),
                now,
                now,
            ),
        )

    def save_messages(
        self,
        channel_id: str,
        messages: list[dict[str, Any]],
        channel_reference: dict[str, Any] | None = None,
    ) -> None:
        if not channel_id:
            return
        with self._transaction() as connection:
            reference = channel_reference
            if not reference:
                existing = self._read_channel(connection, channel_id)
                reference = existing[1] if existing else {}
            self._write_channel(connection, channel_id, messages, reference)

    def update_channel_reference(self, channel_id: str, reference: dict[str, Any]) -> None:
        if not channel_id or not reference:
            return
        with self._transaction() as connection:
            existing = self._read_channel(connection, channel_id)
            if existing is not None:
                self._write_channel(connection, channel_id, existing[0], reference)

    def has_messages(self, channel_id: str) -> bool:
        if not channel_id:
            return False
        row = self._connect().execute(
            "SELECT 1 FROM channel_messages WHERE channel_id = ?", (channel_id,)
        ).fetchone()
        return row is not None

    def load_messages(self, channel_id: str) -> list[dict[str, Any]]:
        if not channel_id:
            return []
        existing = self._read_channel(self._connect(), channel_id)
        return existing[0] if existing else []

    def load_channel_reference(self, channel_id: str) -> dict[str, Any]:
        if not channel_id:
            return {}
        existing = self._read_channel(self._connect(), channel_id)
        return existing[1] if existing else {}

    def upsert_message(
        self,
        channel_id: str,
        message: dict[str, Any],
        insert_if_missing: bool = True,
    ) -> bool:
        # Updates a cached message in place. New messages are only inserted
        # when insert_if_missing is set (MESSAGE_CREATE / send), and then at
        # their chronological position: an edit or reaction on a message
        # older than the cached window must not surface as the newest one.
        if not channel_id or not message:
            return False
        message_id = str(message.get("messageId", "") or "")
        if not message_id:
            return False
        with self._transaction() as connection:
            existing = self._read_channel(connection, channel_id)
            if existing is None:
                return False
            messages, reference = existing
            for index, cached in enumerate(messages):
                if str(cached.get("messageId", "") or "") == message_id:
                    updated = dict(cached)
                    updated.update(message)
                    messages[index] = updated
                    break
            else:
                if not insert_if_missing:
                    return False
                new_key = _snowflake(message_id)
                # Newest first.
                position = len(messages)
                for index, cached in enumerate(messages):
                    if _snowflake(cached.get("messageId")) < new_key:
                        position = index
                        break
                if position >= MAX_MESSAGES_PER_CHANNEL:
                    return False
                messages.insert(position, dict(message))
            self._write_channel(connection, channel_id, messages, reference)
        return True

    def merge_message_update(
        self,
        channel_id: str,
        message: dict[str, Any],
        raw_update: dict[str, Any],
    ) -> dict[str, Any]:
        """Merge a partial Discord MESSAGE_UPDATE into a cached view model.

        Gateway updates only include fields that changed. Formatting the event
        as a complete message would otherwise erase attachments, embeds,
        replies, author details, and timestamps that were not sent again.
        Explicit empty values are retained when their raw field is present.
        """
        if not channel_id or not message:
            return message

        message_id = str(message.get("messageId", "") or "")
        if not message_id:
            return message
        existing = next(
            (
                item
                for item in self.load_messages(channel_id)
                if str(item.get("messageId", "") or "") == message_id
            ),
            None,
        )
        if not existing:
            return message

        merged = dict(existing)
        merged.update(message)

        preserve_groups = (
            (("content", "mentions"), ("body", "rawBody")),
            (
                ("attachments", "embeds", "message_snapshots"),
                (
                    "medias",
                    "richEmbeds",
                    "hasForwarded",
                    "forwardedLabel",
                    "forwardedAuthor",
                    "forwardedBody",
                ),
            ),
            (
                ("referenced_message",),
                ("hasReply", "replyMessageId", "replyAuthor", "replyBody"),
            ),
            (
                ("author", "member"),
                ("authorId", "author", "initials", "avatarCol", "authorBlocked", "blockedVisibility"),
            ),
            (("timestamp",), ("timestamp", "rawTimestamp")),
            (("reactions",), ("reactionsJson",)),
            (("type",), ("displayKind", "discordMessageType")),
        )
        for raw_keys, formatted_keys in preserve_groups:
            if any(key in raw_update for key in raw_keys):
                continue
            for key in formatted_keys:
                if key in existing:
                    merged[key] = existing[key]

        self.upsert_message(channel_id, merged, insert_if_missing=False)
        return merged

    def patch_message(self, channel_id: str, message_id: str, fields: dict[str, Any]) -> bool:
        if not message_id:
            return False
        patch = dict(fields)
        patch["messageId"] = str(message_id)
        return self.upsert_message(channel_id, patch, insert_if_missing=False)

    def remove_messages(self, channel_id: str, message_ids: list[str]) -> bool:
        if not channel_id:
            return False
        removed = {str(message_id) for message_id in message_ids if message_id}
        with self._transaction() as connection:
            existing = self._read_channel(connection, channel_id)
            if existing is None:
                return False
            messages, reference = existing
            kept = [
                message
                for message in messages
                if str(message.get("messageId", "") or "") not in removed
            ]
            if len(kept) != len(messages):
                self._write_channel(connection, channel_id, kept, reference)
        return True

    def clear(self) -> None:
        with self._transaction() as connection:
            connection.execute("DELETE FROM snapshots")
            connection.execute("DELETE FROM guild_channels")
            connection.execute("DELETE FROM channel_messages")
