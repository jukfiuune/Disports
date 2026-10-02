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


def _new_version_paths() -> dict:
    """Where Disports 1.0 (the Qt 6 rewrite) keeps its sign-in, settings
    and caches. Same app, so the same folders as this version."""
    app_dir = _token_path().parent.name
    config = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    cache = os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache"))
    data = _token_path().parent
    caches = [Path(cache) / app_dir / name for name in ("offline", "pictures", "sounds", "QtWebEngine")]
    # Qt 6's compiled QML and graphics caches: this version (Qt 5) rebuilds
    # its own, and shouldn't have to tell them apart.
    caches.append(Path(cache) / app_dir / "qmlcache")
    caches += sorted((Path(cache) / app_dir).glob("qtpipelinecache-*"))
    return {
        "settings": data / "settings.json",
        "preferences": Path(config) / app_dir / "preferences.ini",
        # The captcha page's web data (Qt WebEngine).
        "caches": caches + [data / "QtWebEngine"],
    }


def migrate_from_new_version() -> dict:
    """Someone went back from Disports 1.0 to this version: carry over the
    sign-in (unless this version has one) and the settings both versions
    have, then remove what 1.0 left behind, as 1.0 does with ours. 1.0
    carries them forward again if they install it later.

    Returns {"migrated": bool, "settings": {...}} with the settings for
    the QML side (themeMode, inlineGifPlayback, blockedMessageVisibility,
    maxComposerLines)."""
    import configparser
    import json
    import shutil

    paths = _new_version_paths()
    if not paths["settings"].is_file() and not paths["preferences"].is_file():
        return {"migrated": False, "settings": {}}

    try:
        token = str(json.loads(paths["settings"].read_text(encoding="utf-8")).get("Token") or "").strip()
    except (OSError, ValueError, AttributeError):
        token = ""
    if token and not load_token()["token"]:
        save_token(token)

    settings = {}
    ini = configparser.ConfigParser(interpolation=None)
    try:
        ini.read(paths["preferences"], encoding="utf-8")
        if ini.has_option("appearance", "theme"):
            settings["themeMode"] = min(2, max(0, ini.getint("appearance", "theme")))
        if ini.has_option("chat", "autoplayGifs"):
            settings["inlineGifPlayback"] = ini.getboolean("chat", "autoplayGifs")
        if ini.get("chat", "blockedMessages", fallback="") in ("hide", "reveal", "show"):
            settings["blockedMessageVisibility"] = ini.get("chat", "blockedMessages")
        if ini.has_option("chat", "composerMaxLines"):
            settings["maxComposerLines"] = min(6, max(1, ini.getint("chat", "composerMaxLines")))
    except (configparser.Error, ValueError):
        pass

    # Nothing of 1.0 is kept: not a second copy of the token either.
    for path in (paths["settings"], paths["preferences"]):
        try:
            path.unlink()
        except OSError:
            pass
    for folder in paths["caches"]:
        shutil.rmtree(folder, ignore_errors=True)
    return {"migrated": True, "settings": settings}


def set_preference(key: str, value: str) -> None:
    _client.set_preference(key, value)


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
