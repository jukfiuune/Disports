# Postal (Ubuntu Touch push service) notifications for the Disports daemon.
#
# Envelopes are posted to Lomiri's Postal service over DBus: when the app
# process is dead the system runs the app's push helper (pushexec) to render
# the envelope as a notification; when the app is alive the delivery is
# handed to the app process and ignored there.
from __future__ import annotations

import json
import re
import threading
from datetime import datetime

import daemon_common

POSTAL_BUS_NAME = "com.lomiri.Postal"
POSTAL_INTERFACE = "com.lomiri.Postal"

BODY_MAX_LEN = 200


def postal_app_id() -> str:
    return f"{daemon_common.app_id_prefix()}_disports"


def _dbus_object_path(app_id: str) -> str:
    package = app_id.split("_")[0]
    escaped = re.sub(
        r"[^A-Za-z0-9]",
        lambda match: f"_{ord(match.group(0)):02x}",
        package,
    )
    return f"/com/lomiri/Postal/{escaped}"


def _truncate(text: str, limit: int = BODY_MAX_LEN) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def build_envelope(summary: str, body: str, tag: str, timestamp: str = "") -> dict:
    envelope = {
        "event_type": "Message",
        "summary": _truncate(summary, 80),
        "body": _truncate(body),
        "tag": tag,
    }
    parsed = _parse_timestamp(timestamp)
    if parsed is not None:
        envelope["timestamp"] = parsed
    return envelope


def _parse_timestamp(raw: str):
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None
        return int(parsed.timestamp())
    except ValueError:
        return None


class Notifier:
    # Lazy DBus client for Postal; failures never crash the daemon.
    # Lock-protected: posts come from the gateway thread, cleanup can come
    # from RPC handling or shutdown.

    def __init__(self) -> None:
        self._connection = None
        self._address = None
        self._warned = False
        self._lock = threading.RLock()

    def _warn(self, message: str) -> None:
        if self._warned:
            return
        self._warned = True
        print(f"postal: {message}", flush=True)

    def _connect(self):
        with self._lock:
            if self._connection is not None:
                return True
            try:
                from jeepney import DBusAddress
                from jeepney.io.blocking import open_dbus_connection

                self._connection = open_dbus_connection()
                self._address = DBusAddress(
                    _dbus_object_path(postal_app_id()),
                    bus_name=POSTAL_BUS_NAME,
                    interface=POSTAL_INTERFACE,
                )
                self._warned = False
                return True
            except Exception as exc:
                self._connection = None
                self._warn(f"connect failed: {exc}")
                return False

    def _call(self, method: str, signature: str, args: tuple) -> bool:
        if not self._connect():
            return False
        with self._lock:
            try:
                from jeepney import new_method_call

                request = new_method_call(self._address, method, signature, args)
                self._connection.send_and_get_reply(request, timeout=10.0)
                self._warned = False
                return True
            except Exception as exc:
                self._warn(f"{method} failed: {exc}")
                try:
                    if self._connection is not None:
                        self._connection.close()
                except Exception:
                    pass
                self._connection = None
                return False

    def post(self, app_id: str, payload: dict) -> bool:
        return self._call("Post", "ss", (app_id, json.dumps(payload)))

    def set_counter(self, app_id: str, count: int, visible: bool) -> bool:
        return self._call("SetCounter", "sib", (app_id, int(count), bool(visible)))

    def clear_persistent(self, app_id: str, tags: list[str]) -> bool:
        if not tags:
            return True
        return self._call("ClearPersistentList", "sas", (app_id, tags))

    def close(self) -> None:
        with self._lock:
            try:
                if self._connection is not None:
                    self._connection.close()
            except Exception:
                pass
            self._connection = None
