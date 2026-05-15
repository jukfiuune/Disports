from __future__ import annotations

import threading
import time
from typing import Any, Callable


_CHUNK_SIZE = 100


def _chunks_for_index(index: int, total_visible: int) -> list[list[int]]:
    chunk = index // _CHUNK_SIZE
    ranges: list[list[int]] = [[0, _CHUNK_SIZE - 1]]
    if chunk > 0:
        start = chunk * _CHUNK_SIZE
        end = start + _CHUNK_SIZE - 1
        if total_visible > 0:
            end = min(end, total_visible - 1)
        if start <= end:
            ranges.append([start, end])
    return ranges


class _GuildSub:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.channel_ranges: dict[str, list[list[int]]] = {}
        self.subscribed = False
        self.lists: dict[str, MemberList] = {}

    def get_or_create_list(self, list_id: str) -> "MemberList":
        with self.lock:
            if list_id not in self.lists:
                self.lists[list_id] = MemberList(list_id)
            return self.lists[list_id]

    def get_list(self, list_id: str) -> "MemberList | None":
        with self.lock:
            return self.lists.get(list_id)


class MemberList:
    def __init__(self, list_id: str) -> None:
        self.list_id = list_id
        self._lock = threading.Lock()
        self.member_count: int = 0
        self.online_count: int = 0
        self.groups: list[dict[str, Any]] = []
        self._items: list[dict[str, Any] | None] = []

    def total_visible(self) -> int:
        with self._lock:
            for g in self.groups:
                if g.get("id") == "offline":
                    return self.member_count
            return self.online_count

    def apply_ops(self, payload: dict[str, Any]) -> None:
        with self._lock:
            self.member_count = int(payload.get("member_count") or 0)
            self.online_count = int(payload.get("online_count") or 0)
            self.groups = payload.get("groups") or []
            for op in payload.get("ops") or []:
                op_type = op.get("op", "")
                if op_type == "SYNC":
                    self._op_sync(op)
                elif op_type == "INVALIDATE":
                    self._op_invalidate(op)
                elif op_type == "INSERT":
                    self._op_insert(op)
                elif op_type == "UPDATE":
                    self._op_update(op)
                elif op_type == "DELETE":
                    self._op_delete(op)
            self._trim()

    def _ensure_len(self, length: int) -> None:
        if len(self._items) < length:
            self._items.extend([None] * (length - len(self._items)))

    def _op_sync(self, op: dict[str, Any]) -> None:
        r = op.get("range") or [0, 0]
        start, end = int(r[0]), int(r[1])
        self._ensure_len(end + 1)
        for i, item in enumerate(op.get("items") or []):
            if start + i <= end:
                self._items[start + i] = item

    def _op_invalidate(self, op: dict[str, Any]) -> None:
        r = op.get("range") or [0, 0]
        start, end = int(r[0]), int(r[1])
        for i in range(start, min(end + 1, len(self._items))):
            self._items[i] = None

    def _op_insert(self, op: dict[str, Any]) -> None:
        index = int(op.get("index") or 0)
        self._ensure_len(index)
        self._items.insert(index, op.get("item"))

    def _op_update(self, op: dict[str, Any]) -> None:
        index = int(op.get("index") or 0)
        self._ensure_len(index + 1)
        self._items[index] = op.get("item")

    def _op_delete(self, op: dict[str, Any]) -> None:
        index = int(op.get("index") or 0)
        if 0 <= index < len(self._items):
            self._items.pop(index)

    def _trim(self) -> None:
        while self._items and self._items[-1] is None:
            self._items.pop()


class MemberStateMixin:
    def __init__(self) -> None:
        self._member_state_lock = threading.Lock()
        self._guild_subs: dict[str, _GuildSub] = {}
        self._sub_throttle: dict[str, float] = {}
        self._send_gateway: Callable[[dict], None] | None = None
        super().__init__()

    def _reset_state(self) -> None:
        # _send_gateway is preserved across resets so reconnects keep working.
        self._member_state_lock = threading.Lock()
        self._guild_subs = {}
        self._sub_throttle = {}
        if hasattr(super(), "_reset_state"):
            super()._reset_state()

    def subscribe_guild_channel(
        self,
        guild_id: str,
        channel_id: str,
        scroll_index: int = 0,
    ) -> None:
        if not guild_id or not self._send_gateway:
            return

        if not channel_id:
            threading.Thread(
                target=self._do_subscribe,
                args=(guild_id, {}),
                daemon=True,
            ).start()
            return

        sub = self._get_or_create_guild_sub(guild_id)
        list_id = self._compute_list_id(guild_id, channel_id)
        ml = sub.get_or_create_list(list_id)
        ranges = _chunks_for_index(scroll_index, ml.total_visible())

        with sub.lock:
            if sub.channel_ranges.get(channel_id) == ranges and sub.subscribed:
                return
            for cid in sub.channel_ranges:
                if cid != channel_id:
                    sub.channel_ranges[cid] = [[0, _CHUNK_SIZE - 1]]
            sub.channel_ranges[channel_id] = ranges
            sub.subscribed = True
            channels_snapshot = dict(sub.channel_ranges)

        threading.Thread(
            target=self._do_subscribe,
            args=(guild_id, channels_snapshot),
            daemon=True,
        ).start()

    def apply_member_list_update(self, data: dict[str, Any]) -> None:
        guild_id = str(data.get("guild_id") or "")
        list_id = str(data.get("id") or "everyone")

        sub = self._get_or_create_guild_sub(guild_id)
        sub.get_or_create_list(list_id).apply_ops(data)

        for op in data.get("ops") or []:
            if op.get("op") not in ("SYNC", "INSERT", "UPDATE"):
                continue
            items: list[dict[str, Any]] = op.get("items") or (
                [op["item"]] if op.get("item") else []
            )
            for item in items:
                if not isinstance(item, dict):
                    continue
                member_obj = item.get("member")
                if not isinstance(member_obj, dict):
                    continue
                user = member_obj.get("user")
                if isinstance(user, dict) and user.get("id"):
                    self.cache_user(user, member_obj, guild_id=guild_id)
                presence = member_obj.get("presence") or {}
                if isinstance(presence, dict):
                    uid = str(
                        (presence.get("user") or {}).get("id")
                        or (user or {}).get("id")
                        or ""
                    )
                    if uid:
                        self.presences[uid] = presence.get("status", "offline")

    def _compute_list_id(self, guild_id: str, channel_id: str) -> str:
        channel = self.channel_by_id.get(channel_id)
        if not channel:
            return "everyone"

        VIEW_CHANNEL = 1 << 10
        allows: list[str] = []
        denies: list[str] = []
        for ow in channel.get("permission_overwrites") or []:
            try:
                allow_bits = int(ow.get("allow") or 0)
                deny_bits = int(ow.get("deny") or 0)
            except (TypeError, ValueError):
                continue
            ow_id = str(ow.get("id") or "")
            if not ow_id:
                continue
            if allow_bits & VIEW_CHANNEL:
                allows.append(ow_id)
            elif deny_bits & VIEW_CHANNEL:
                denies.append(ow_id)

        if not allows and not denies:
            return "everyone"

        parts = [f"allow:{a}" for a in allows] + [f"deny:{d}" for d in denies]
        key = ",".join(parts).encode()

        # replaces mmh3 (c python package, not available on "all")
        def fmix32(h: int) -> int:
            h ^= h >> 16
            h = (h * 0x85ebca6b) & 0xFFFFFFFF
            h ^= h >> 13
            h = (h * 0xc2b2ae35) & 0xFFFFFFFF
            h ^= h >> 16
            return h

        length = len(key)
        nblocks = length // 4
        h1 = 0
        c1 = 0xcc9e2d51
        c2 = 0x1b873593

        for i in range(nblocks):
            k1 = int.from_bytes(key[i * 4:(i + 1) * 4], byteorder='little', signed=False)
            k1 = (k1 * c1) & 0xFFFFFFFF
            k1 = ((k1 << 15) | (k1 >> 17)) & 0xFFFFFFFF
            k1 = (k1 * c2) & 0xFFFFFFFF
            h1 ^= k1
            h1 = ((h1 << 13) | (h1 >> 19)) & 0xFFFFFFFF
            h1 = (h1 * 5 + 0xe6546b64) & 0xFFFFFFFF

        tail = key[nblocks * 4:]
        k1 = 0
        if len(tail) >= 3:
            k1 ^= tail[2] << 16
        if len(tail) >= 2:
            k1 ^= tail[1] << 8
        if len(tail) >= 1:
            k1 ^= tail[0]
            k1 = (k1 * c1) & 0xFFFFFFFF
            k1 = ((k1 << 15) | (k1 >> 17)) & 0xFFFFFFFF
            k1 = (k1 * c2) & 0xFFFFFFFF
            h1 ^= k1

        h1 ^= length
        return str(fmix32(h1))
        
    def _get_or_create_guild_sub(self, guild_id: str) -> _GuildSub:
        with self._member_state_lock:
            if guild_id not in self._guild_subs:
                self._guild_subs[guild_id] = _GuildSub()
            return self._guild_subs[guild_id]

    def _do_subscribe(self, guild_id: str, channels: dict[str, list[list[int]]]) -> None:
        if not self._send_gateway:
            return
        now = time.monotonic()
        with self._member_state_lock:
            if now - self._sub_throttle.get(guild_id, 0.0) < 0.25:
                return
            self._sub_throttle[guild_id] = now
        try:
            data: dict[str, Any] = {
                "guild_id": guild_id,
                "typing": True,
                "activities": True,
                "threads": False,
            }
            if channels:
                data["channels"] = {cid: r for cid, r in channels.items()}
            self._send_gateway({"op": 14, "d": data})
        except Exception:
            pass
