import os
import threading
import time
from collections import deque
from pathlib import Path

try:
    import pyotherside
except ImportError:  # pragma: no cover - local verification path
    pyotherside = None

import daemon_common
import daemon_service
from daemon_proxy import DaemonProtocolMismatch, DaemonProxy, DaemonTimeout, DaemonUnavailable
from disports_discord import DiscordClient


def _emit(name: str, payload: dict) -> None:
    if pyotherside is not None:
        pyotherside.send(name, payload)


def _desktop_mode() -> bool:
    dm = os.environ.get("CLICKABLE_DESKTOP_MODE", "").strip().lower()
    return dm in ("1", "true", "yes", "on")


# --- embedded client (used when the background daemon is off) ---

_client = DiscordClient(emitter=_emit)


def _token_path() -> Path:
    return daemon_common.token_path()


def save_token(token: str) -> dict:
    raw = (token or "").strip()
    if not raw:
        return {"ok": False, "error": "Empty token."}
    path = _token_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(raw, encoding="utf-8")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return {"ok": True}
    except Exception as e:
        import traceback
        return {"ok": False, "error": f"Save fail: {e}\n{traceback.format_exc()}"}


def load_token() -> dict:
    path = _token_path()
    if not path.is_file():
        return {"token": ""}
    try:
        return {"token": path.read_text(encoding="utf-8").strip()}
    except OSError:
        return {"token": ""}


def clear_token() -> dict:
    # Logout. The daemon also tears down its own session (see
    # DaemonServer.client_token_clear); the embedded client must never be
    # left running either.
    backend = _backend()
    if backend is not _client:
        try:
            backend.call("clear_token")
        except Exception:
            pass
    if _client.gateway or _client.http.token:
        _client.disconnect()
    path = _token_path()
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    _client.cache.clear()
    if _local_notifier is not None:
        _local_notifier.dismiss_all()
    return {"ok": True}


def load_offline_state() -> dict:
    if not _token_path().is_file():
        return {}
    return _client.cache.load_ready()


def load_cached_guild_channels(guild_id: str) -> list:
    return _client.cache.load_guild_channels(str(guild_id or ""))


def load_cached_messages(channel_id: str) -> list:
    return _client.cache.load_messages(str(channel_id or ""))


# --- backend switching ---

_mode = "embedded"  # "embedded" | "daemon"
_proxy: DaemonProxy | None = None
_backend_lock = threading.RLock()
_background_enabled = daemon_common.read_settings()[daemon_common.SETTING_BACKGROUND_SERVICE]
_app_foreground = True
_reattach_thread: threading.Thread | None = None
_local_notifier = None
_notification_actions = deque()
_notification_actions_lock = threading.Lock()

REATTACH_INTERVAL = 2.0


def _connect_proxy() -> DaemonProxy:
    proxy = DaemonProxy(emitter=_emit)
    try:
        proxy.connect()
        return proxy
    except DaemonProtocolMismatch as exc:
        proxy.close()
        if not _background_enabled:
            raise
        print(f"daemon: {exc}; restarting updated service once", flush=True)
        daemon_service.restart()

        deadline = time.monotonic() + 15.0
        last_error: Exception = exc
        while time.monotonic() < deadline:
            replacement = DaemonProxy(emitter=_emit)
            try:
                replacement.connect()
                print("daemon: attached to updated service", flush=True)
                return replacement
            except DaemonUnavailable as retry_error:
                replacement.close()
                last_error = retry_error
                time.sleep(0.25)
        raise DaemonUnavailable(
            f"Updated daemon did not become ready: {last_error}"
        ) from last_error


def _attach_daemon(resync: bool) -> DaemonProxy:
    # Switches to the daemon. Only one gateway may ever feed the UI, so an
    # embedded session started during a fallback is torn down here.
    global _mode, _proxy
    with _backend_lock:
        proxy = _connect_proxy()
        try:
            proxy.call("set_app_foreground", [_app_foreground])
        except Exception:
            pass
        if _client.gateway or _client.http.token:
            print("daemon: attached; stopping embedded gateway", flush=True)
            _client.disconnect()
        _proxy = proxy
        _mode = "daemon"
    if resync:
        # Events were missed while detached: the daemon re-emits its READY
        # snapshot (and connection status) when an existing gateway is
        # attached, which rebuilds the UI models.
        try:
            proxy.call("connect_gateway")
        except Exception as exc:
            print(f"daemon: resync after reattach failed: {exc}", flush=True)
    return proxy


def _degrade_to_embedded() -> None:
    global _mode, _proxy
    with _backend_lock:
        if _proxy:
            _proxy.close()
            _proxy = None
        _mode = "embedded"
    _schedule_reattach()


def _schedule_reattach() -> None:
    # While the background service is enabled, embedded mode is only a
    # stopgap (daemon restarting, crashed, being updated). Keep probing and
    # hand the session back as soon as it is reachable.
    global _reattach_thread
    if not _background_enabled:
        return
    with _backend_lock:
        if _reattach_thread and _reattach_thread.is_alive():
            return
        _reattach_thread = threading.Thread(target=_reattach_loop, daemon=True)
        _reattach_thread.start()


def _reattach_loop() -> None:
    while _background_enabled and _mode == "embedded":
        time.sleep(REATTACH_INTERVAL)
        if not daemon_common.socket_path().exists():
            continue
        try:
            _attach_daemon(resync=True)
            print("daemon: reattached after fallback", flush=True)
            return
        except Exception:
            continue


def _ensure_embedded_ready() -> bool:
    # Log the embedded client in from the shared token file if needed.
    token = (load_token().get("token") or "").strip()
    if not token:
        return False
    if _client.http.token != token:
        result = _client.login(token)
        if not result.get("ok"):
            return False
    if _client.state.me and _client.gateway is None:
        try:
            _client.connect_gateway()
        except Exception:
            pass
    return True


def _backend():
    # Picks the active backend: the daemon when enabled and reachable, else
    # the embedded client.
    with _backend_lock:
        if _mode == "daemon" and _proxy and _proxy.connected:
            return _proxy
        if not _background_enabled:
            return _client
        was_daemon = _mode == "daemon"
        try:
            # A dropped connection (e.g. the daemon discarded us while the
            # app was suspended) needs a resync; a first attach does not.
            return _attach_daemon(resync=was_daemon)
        except Exception:
            if was_daemon:
                _degrade_to_embedded()
            else:
                _schedule_reattach()
            return _client


def _call(method: str, *args):
    # Routes a client call to the daemon, falling back to embedded mode only
    # when the daemon is actually gone.
    backend = _backend()
    if backend is _client:
        if _background_enabled:
            _ensure_embedded_ready()
        return getattr(_client, method)(*args)
    try:
        return backend.call(method, list(args))
    except DaemonTimeout as exc:
        # The daemon is alive but slow; it still owns the gateway.
        raise RuntimeError(str(exc)) from exc
    except DaemonUnavailable:
        pass
    # Connection lost mid-call: try to reattach once before falling back.
    backend = _backend()
    if backend is not _client:
        return backend.call(method, list(args))
    _ensure_embedded_ready()
    return getattr(_client, method)(*args)


# --- public API (names must stay stable: QML calls these directly) ---


def set_preference(key: str, value: str) -> None:
    _call("set_preference", key, value)


def dev_flags() -> dict:
    if _desktop_mode():
        return {"clickableDesktopMode": True}
    return {}


def login(token: str) -> dict:
    return _call("login", token)


def start_qr_login() -> dict:
    return _call("start_qr_login")


def stop_qr_login() -> bool:
    return _call("stop_qr_login")


def connect_gateway() -> bool:
    return _call("connect_gateway")


def disconnect() -> bool:
    return _call("disconnect")


def resume_session() -> dict:
    # Foreground refresh: (re)attach to whichever backend owns the gateway
    # and have it re-emit its session snapshot. Never raises, so the UI can
    # always clear its "refreshing" state.
    try:
        _call("connect_gateway")
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def reconnect() -> bool:
    _call("reconnect")
    return True


def fetch_private_channels() -> dict:
    return _call("fetch_private_channels")


def fetch_guild_channels(guild_id: str) -> list:
    return _call("fetch_guild_channels", guild_id)


def fetch_guild_emojis(guild_id: str) -> list:
    return _call("fetch_guild_emojis", guild_id)


def fetch_unicode_emojis() -> list:
    return _call("fetch_unicode_emojis")


def fetch_messages(channel_id: str, limit: int = 50, before: str = "") -> list:
    return _call("fetch_messages", channel_id, limit, before)


def channel_info(channel_id: str) -> dict:
    return _call("channel_info", channel_id)


def send_message(channel_id: str, content: str, reply_message_id: str = "") -> dict:
    return _call("send_message", channel_id, content, reply_message_id)


def edit_message(channel_id: str, message_id: str, content: str) -> dict:
    return _call("edit_message", channel_id, message_id, content)


def delete_message(channel_id: str, message_id: str) -> dict:
    return _call("delete_message", channel_id, message_id)


def ack_message(channel_id: str, message_id: str) -> dict:
    return _call("ack_message", channel_id, message_id)


def mark_seen(channel_id: str, message_id: str) -> dict:
    return _call("mark_seen", channel_id, message_id)


def set_active_channel(channel_id: str) -> bool:
    if channel_id and _local_notifier is not None:
        _local_notifier.dismiss_channel(channel_id)
    return _call("set_active_channel", channel_id)


def set_app_foreground(active: bool) -> bool:
    # Tells the daemon whether the UI can post its own notifications. The
    # app is suspended soon after leaving the foreground, so the daemon must
    # take over from that moment.
    global _app_foreground
    _app_foreground = bool(active)
    with _backend_lock:
        proxy = _proxy if _mode == "daemon" else None
    if proxy is None or not proxy.connected:
        if _app_foreground:
            _backend()  # reattach if the daemon dropped us while suspended
        return True
    try:
        proxy.call("set_app_foreground", [_app_foreground])
    except Exception:
        pass
    return True


def resolve_channel(channel_id: str) -> dict:
    return _call("resolve_channel", channel_id)


def add_reaction(channel_id: str, message_id: str, emoji: str) -> dict:
    return _call("add_reaction", channel_id, message_id, emoji)


def remove_reaction(channel_id: str, message_id: str, emoji: str) -> dict:
    return _call("remove_reaction", channel_id, message_id, emoji)


# --- daemon management ---


def get_settings() -> dict:
    settings = daemon_common.read_settings()
    return {
        "backgroundService": settings[daemon_common.SETTING_BACKGROUND_SERVICE],
        "notifications": settings[daemon_common.SETTING_NOTIFICATIONS],
        "desktopMode": _desktop_mode(),
    }


def set_notifications(enabled: bool) -> dict:
    # Opt-in/out of notifications; the daemon picks it up live and cleans up.
    daemon_common.write_setting(daemon_common.SETTING_NOTIFICATIONS, bool(enabled))
    backend = _backend()
    if backend is not _client:
        try:
            backend.call("set_notifications", bool(enabled))
        except Exception:
            pass  # daemon unavailable; it cleans up on its own stop path
    return {"ok": True}


class _LocalNotifier:
    """Posts interactive notifications and forwards taps back to QML."""

    def __init__(self) -> None:
        from jeepney import DBusAddress, MatchRule
        from jeepney.bus_messages import message_bus
        from jeepney.io.threading import open_dbus_router

        self._address = DBusAddress(
            "/org/freedesktop/Notifications",
            bus_name="org.freedesktop.Notifications",
            interface="org.freedesktop.Notifications",
        )
        self._channels: dict[int, str] = {}
        self._lock = threading.Lock()
        self._router_context = open_dbus_router()
        self._router = self._router_context.__enter__()
        self._action_rule = MatchRule(
            type="signal",
            interface="org.freedesktop.Notifications",
            member="ActionInvoked",
            path="/org/freedesktop/Notifications",
        )
        self._router.send_and_get_reply(
            message_bus.AddMatch(self._action_rule), timeout=5.0
        )
        self._filter_context = self._router.filter(
            self._action_rule, bufsize=32
        )
        self._action_queue = self._filter_context.__enter__()
        threading.Thread(target=self._watch_actions, daemon=True).start()

    def _watch_actions(self) -> None:
        while True:
            try:
                message = self._action_queue.get()
                notification_id = int(message.body[0])
                with self._lock:
                    channel_id = self._channels.pop(notification_id, "")
                if channel_id:
                    with _notification_actions_lock:
                        _notification_actions.append(channel_id)
                    print(
                        f"notification: queued live action channel={channel_id}",
                        flush=True,
                    )
            except Exception:
                return

    def post(self, summary: str, body: str, channel_id: str) -> None:
        from jeepney import new_method_call

        request = new_method_call(
            self._address,
            "Notify",
            "susssasa{sv}i",
            (
                "Disports",
                0,
                "",
                summary or "New message",
                body or "",
                ["open", "Open"],
                {"x-lomiri-switch-to-application": ("s", "true")},
                5000,
            ),
        )
        reply = self._router.send_and_get_reply(request, timeout=5.0)
        notification_id = int(reply.body[0])
        with self._lock:
            if len(self._channels) >= 100:
                self._channels.clear()
            self._channels[notification_id] = str(channel_id)

    def _close_ids(self, ids: list[int]) -> None:
        from jeepney import new_method_call

        for notification_id in ids:
            try:
                self._router.send_and_get_reply(
                    new_method_call(self._address, "CloseNotification", "u", (notification_id,)),
                    timeout=2.0,
                )
            except Exception:
                pass

    def dismiss_channel(self, channel_id: str) -> None:
        # Reading a conversation dismisses its notifications.
        with self._lock:
            ids = [nid for nid, cid in self._channels.items() if cid == str(channel_id)]
            for nid in ids:
                self._channels.pop(nid, None)
        self._close_ids(ids)

    def dismiss_all(self) -> None:
        with self._lock:
            ids = list(self._channels)
            self._channels.clear()
        self._close_ids(ids)

    def close(self) -> None:
        try:
            self._filter_context.__exit__(None, None, None)
        finally:
            self._router_context.__exit__(None, None, None)


def local_notify(summary: str, body: str, channel_id: str = "") -> dict:
    # Live notification posted by the app while it is in the foreground.
    # Once backgrounded, the daemon (if enabled) owns notifications; posting
    # here too would duplicate them.
    global _local_notifier
    if _mode == "daemon" and not _app_foreground:
        return {"ok": True, "skipped": True}
    try:
        if _local_notifier is None:
            _local_notifier = _LocalNotifier()
        _local_notifier.post(summary, body, channel_id)
        print(
            f"notification: posted live notification channel={channel_id or 'unknown'}",
            flush=True,
        )
        return {"ok": True}
    except Exception as exc:
        if _local_notifier is not None:
            try:
                _local_notifier.close()
            except Exception:
                pass
        _local_notifier = None
        return {"ok": False, "error": str(exc)}


def take_notification_action() -> dict:
    """Return one live-notification tap for delivery on QML's UI thread."""
    with _notification_actions_lock:
        if not _notification_actions:
            return {}
        channel_id = _notification_actions.popleft()
        print(
            f"notification: delivering live action channel={channel_id}",
            flush=True,
        )
        return {"channelId": channel_id}


def daemon_status() -> dict:
    backend = _backend()
    return {
        "mode": "embedded" if backend is _client else "daemon",
        "daemonReachable": _proxy is not None and _proxy.connected,
        "installed": daemon_service.is_installed(),
        "active": daemon_service.is_active(),
        "desktopMode": _desktop_mode(),
    }


def set_background_service(enabled: bool) -> dict:
    # Handover order when enabling: the daemon connects first (it owns the
    # token file), then the app drops its embedded gateway so there is only
    # ever one gateway session. When disabling the order is reversed and the
    # app reconnects embedded.
    global _background_enabled
    if _desktop_mode():
        return {"ok": False, "error": "Background service is unavailable in desktop mode."}

    enabled = bool(enabled)

    if enabled:
        try:
            daemon_service.install_and_start()
        except Exception as exc:
            return {"ok": False, "error": f"Could not start daemon: {exc}"}
        if not daemon_service.wait_for_socket():
            return {"ok": False, "error": "Daemon did not start."}
        _background_enabled = True
        try:
            _attach_daemon(resync=True)
        except Exception as exc:
            _background_enabled = False
            return {"ok": False, "error": f"Could not reach daemon: {exc}"}
        daemon_common.write_setting(daemon_common.SETTING_BACKGROUND_SERVICE, True)
        return {"ok": True, "mode": "daemon"}

    # Stop probing for the daemon before removing it.
    _background_enabled = False
    try:
        daemon_service.stop_and_remove()
    except Exception as exc:
        _background_enabled = True
        return {"ok": False, "error": f"Could not stop daemon: {exc}"}
    _degrade_to_embedded()
    _ensure_embedded_ready()
    daemon_common.write_setting(daemon_common.SETTING_BACKGROUND_SERVICE, False)
    return {"ok": True, "mode": "embedded"}
