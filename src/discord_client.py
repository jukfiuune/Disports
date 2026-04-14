import os
from pathlib import Path

try:
    import pyotherside
except ImportError:  # pragma: no cover - local verification path
    pyotherside = None

from disports_discord import DiscordClient


def _emit(name: str, payload: dict) -> None:
    if pyotherside is not None:
        pyotherside.send(name, payload)


def _token_path() -> Path:
    base = os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share"))
    # On Ubuntu Touch, APP_ID contains the writable namespace (e.g. "disports.uguuuu_disports_1.0.0")
    # Apps are only allowed to write to ~/.local/share/<APP_ID_PREFIX>
    app_id = os.environ.get("APP_ID", "").split("_")[0]
    app_dir = app_id if app_id else "disports"
    return Path(base) / app_dir / "token"


_client = DiscordClient(emitter=_emit)


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


def dev_flags() -> dict:
    """QML reads this after Python loads; see NavigationLogic connectivity gate.

    Returns {} when nothing overrides QML heuristics. Use ``force: true`` when Python should
    set ``ignoreConnectivityGate`` explicitly.

    - DISPORTS_IGNORE_CONNECTIVITY: force on (1/true/yes/on) or force off (0/false/no/off).
    - CLICKABLE_DESKTOP_MODE: Clickable sets this for ``clickable desktop`` (yaml ``env_vars``
      often do not reach qmlscene, but this variable usually does).
    """
    v = os.environ.get("DISPORTS_IGNORE_CONNECTIVITY", "").strip().lower()
    if v in ("0", "false", "no", "off"):
        return {"ignoreConnectivityGate": False, "force": True}
    if v in ("1", "true", "yes", "on"):
        return {"ignoreConnectivityGate": True, "force": True}

    dm = os.environ.get("CLICKABLE_DESKTOP_MODE", "").strip().lower()
    if dm in ("1", "true", "yes", "on"):
        return {"ignoreConnectivityGate": True, "force": True}

    return {}


def login(token: str) -> dict:
    return _client.login(token)


def start_qr_login() -> dict:
    return _client.start_qr_login()


def stop_qr_login() -> bool:
    return _client.stop_qr_login()


def connect_gateway() -> bool:
    return _client.connect_gateway()


def disconnect() -> bool:
    return _client.disconnect()


def reconnect() -> bool:
    _client.reconnect()
    return True


def fetch_private_channels() -> dict:
    return _client.fetch_private_channels()


def fetch_guild_channels(guild_id: str) -> list:
    return _client.fetch_guild_channels(guild_id)


def fetch_messages(channel_id: str, limit: int = 50, before: str = "") -> list:
    return _client.fetch_messages(channel_id, limit, before)


def send_message(channel_id: str, content: str, reply_message_id: str = "") -> dict:
    return _client.send_message(channel_id, content, reply_message_id)


def edit_message(channel_id: str, message_id: str, content: str) -> dict:
    return _client.edit_message(channel_id, message_id, content)


def delete_message(channel_id: str, message_id: str) -> dict:
    return _client.delete_message(channel_id, message_id)


def ack_message(channel_id: str, message_id: str) -> dict:
    return _client.ack_message(channel_id, message_id)


def set_active_channel(channel_id: str) -> bool:
    return _client.set_active_channel(channel_id)
