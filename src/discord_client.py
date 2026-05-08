from __future__ import annotations

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
    dm = os.environ.get("CLICKABLE_DESKTOP_MODE", "").strip().lower()

    if dm in ("1", "true", "yes", "on"):
        return {"clickableDesktopMode": True}

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


def pop_voice_logs() -> list:
    from disports_discord.qt_audio import get_voice_logs
    return get_voice_logs()


def set_muted(muted: bool) -> None:
    _client.set_muted(muted)


def fetch_private_channels() -> dict:
    return _client.fetch_private_channels()


def fetch_guild_channels(guild_id: str) -> list:
    return _client.fetch_guild_channels(guild_id)


def fetch_guild_emojis(guild_id: str) -> list:
    return _client.fetch_guild_emojis(guild_id)


def fetch_unicode_emojis() -> list:
    return _client.fetch_unicode_emojis()


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


def mark_seen(channel_id: str, message_id: str) -> dict:
    return _client.mark_seen(channel_id, message_id)


def set_active_channel(channel_id: str) -> bool:
    return _client.set_active_channel(channel_id)


def resolve_channel(channel_id: str) -> dict:
    return _client.resolve_channel(channel_id)


def add_reaction(channel_id: str, message_id: str, emoji: str) -> dict:
    return _client.add_reaction(channel_id, message_id, emoji)


def remove_reaction(channel_id: str, message_id: str, emoji: str) -> dict:
    return _client.remove_reaction(channel_id, message_id, emoji)


def join_voice_channel(guild_id: str | None, channel_id: str | None) -> None:
    _client.join_voice_channel(guild_id, channel_id)


def leave_voice_channel(guild_id: str | None) -> None:
    _client.leave_voice_channel(guild_id)


def set_speakerphone(enabled: bool) -> None:
    _client.set_speakerphone(enabled)


def set_audio_pipe_capsule(capsule) -> None:
    from disports_discord.qt_audio import set_audio_pipe_capsule as _set
    _set(capsule)
