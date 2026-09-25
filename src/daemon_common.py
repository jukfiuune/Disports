# Shared helpers for the daemon and app process: both must agree on the
# token location, unix socket path and persistent settings file.
import json
import os
from pathlib import Path

PROTOCOL_VERSION = 1

SOCKET_DIR_NAME = "disports"
SOCKET_FILE_NAME = "daemon.sock"

SETTINGS_FILE_NAME = "settings.json"

SETTING_BACKGROUND_SERVICE = "background_service"
SETTING_NOTIFICATIONS = "notifications"

DEFAULT_SETTINGS = {
    SETTING_BACKGROUND_SERVICE: False,
    SETTING_NOTIFICATIONS: False,
}


def app_id_prefix() -> str:
    # Writable namespace prefix derived from APP_ID (e.g. "disports.jukfiuu").
    return os.environ.get("APP_ID", "").split("_")[0] or "disports"


def data_dir() -> Path:
    # On Ubuntu Touch, APP_ID contains the writable namespace
    # (e.g. "disports.jukfiuu_disports_1.0.0") and apps are only allowed to
    # write to ~/.local/share/<APP_ID_PREFIX>.
    base = os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share"))
    return Path(base) / app_id_prefix()


def token_path() -> Path:
    return data_dir() / "token"


def settings_path() -> Path:
    return data_dir() / SETTINGS_FILE_NAME


def socket_dir() -> Path:
    runtime = os.environ.get("XDG_RUNTIME_DIR", "")
    if runtime:
        return Path(runtime) / SOCKET_DIR_NAME
    return data_dir()


def socket_path() -> Path:
    return socket_dir() / SOCKET_FILE_NAME


def read_settings() -> dict:
    try:
        with settings_path().open(encoding="utf-8") as fh:
            stored = json.load(fh)
    except (OSError, ValueError):
        stored = {}
    settings = dict(DEFAULT_SETTINGS)
    if isinstance(stored, dict):
        for key in DEFAULT_SETTINGS:
            if key in stored:
                settings[key] = bool(stored[key])
    return settings


def write_setting(key: str, value: bool) -> dict:
    settings = read_settings()
    settings[key] = bool(value)
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(settings), encoding="utf-8")
    tmp.replace(path)
    return settings
