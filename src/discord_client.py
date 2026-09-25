import os
from pathlib import Path

try:
    import pyotherside
except ImportError:  # pragma: no cover - local verification path
    pyotherside = None

import daemon_common
import daemon_service
from daemon_proxy import DaemonProxy, DaemonUnavailable
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
    path = _token_path()
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    return {"ok": True}


# --- backend switching ---

_mode = "embedded"  # "embedded" | "daemon"
_proxy: DaemonProxy | None = None


def _connect_proxy() -> DaemonProxy:
    proxy = DaemonProxy(emitter=_emit)
    proxy.connect()
    return proxy


def _degrade_to_embedded() -> None:
    global _mode, _proxy
    if _proxy:
        _proxy.close()
        _proxy = None
    _mode = "embedded"


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
    # Picks the active backend: the daemon when reachable, else embedded.
    global _mode, _proxy
    if _mode == "daemon":
        if _proxy and _proxy.connected:
            return _proxy
        try:
            _proxy = _connect_proxy()
            return _proxy
        except Exception:
            _degrade_to_embedded()
    if daemon_common.socket_path().exists():
        try:
            _proxy = _connect_proxy()
            _mode = "daemon"
            return _proxy
        except Exception:
            pass
    return _client


def _call(method: str, *args):
    # Routes a client call to the daemon, falling back to embedded mode.
    backend = _backend()
    if backend is _client:
        return getattr(_client, method)(*args)
    try:
        return backend.call(method, list(args))
    except DaemonUnavailable:
        _degrade_to_embedded()
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
    return _call("set_active_channel", channel_id)


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


def local_notify(summary: str, body: str) -> dict:
    # Local notification posted by the app while it is running (freedesktop API).
    try:
        from jeepney import DBusAddress, new_method_call
        from jeepney.io.blocking import open_dbus_connection

        connection = open_dbus_connection()
        try:
            address = DBusAddress(
                "/org/freedesktop/Notifications",
                bus_name="org.freedesktop.Notifications",
                interface="org.freedesktop.Notifications",
            )
            request = new_method_call(
                address,
                "Notify",
                "susssasa{sv}i",
                ("Disports", 0, "", summary or "New message", body or "", [], {}, 5000),
            )
            connection.send_and_get_reply(request, timeout=5.0)
        finally:
            connection.close()
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def daemon_status() -> dict:
    return {
        "mode": _mode,
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
    global _mode, _proxy
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
        try:
            _proxy = _connect_proxy()
        except Exception as exc:
            return {"ok": False, "error": f"Could not reach daemon: {exc}"}
        _mode = "daemon"
        if _client.gateway:
            _client.disconnect()
        daemon_common.write_setting(daemon_common.SETTING_BACKGROUND_SERVICE, True)
        return {"ok": True, "mode": "daemon"}

    try:
        daemon_service.stop_and_remove()
    except Exception as exc:
        return {"ok": False, "error": f"Could not stop daemon: {exc}"}
    _degrade_to_embedded()
    _ensure_embedded_ready()
    daemon_common.write_setting(daemon_common.SETTING_BACKGROUND_SERVICE, False)
    return {"ok": True, "mode": "embedded"}
