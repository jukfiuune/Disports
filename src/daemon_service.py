# systemd user-unit management for the Disports background daemon. The unit
# file is generated at enable-time from the running environment so the daemon
# always shares the app's APP_ID prefix, data dir and install location.
from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import daemon_common

SERVICE_UNIT = "disports.service"

_UNIT_WAIT_TIMEOUT = 15.0
_UNIT_WAIT_INTERVAL = 0.5


def _systemctl() -> str:
    import shutil
    return shutil.which("systemctl") or "/usr/bin/systemctl"


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    if args and args[0] == "systemctl":
        args = [_systemctl()] + args[1:]
    return subprocess.run(
        args,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def _src_dir() -> Path:
    return Path(__file__).resolve().parent


def _click_install_dir() -> Path:
    # Inside a click, pin to the "current" symlink so the unit keeps working
    # across app updates.
    src = _src_dir()
    parts = src.parts
    if len(parts) >= 4 and parts[-4] == "click.ubuntu.com":
        parts = parts[:-2] + ("current", parts[-1])
        return Path(*parts)
    return src


def unit_content() -> str:
    src_dir = _click_install_dir()
    python = os.environ.get("DISPORTS_PYTHON", "/usr/bin/python3")
    app_prefix = daemon_common.app_id_prefix()
    return "\n".join(
        [
            "[Unit]",
            "Description=Disports background service",
            "",
            "[Service]",
            "Type=simple",
            f"WorkingDirectory={src_dir}",
            f"ExecStart={python} {src_dir / 'daemon_server.py'}",
            f"Environment=APP_ID={app_prefix}",
            "Environment=XDG_DATA_HOME=%h/.local/share",
            "Restart=always",
            "RestartSec=10",
            "",
            "[Install]",
            "WantedBy=graphical-session.target",
            "",
        ]
    )


def unit_dest_path() -> Path:
    # The systemd user manager scans ~/.config/systemd/user — deliberately
    # NOT $XDG_CONFIG_HOME, which is redirected for click app processes.
    return Path(os.path.expanduser("~")) / ".config" / "systemd" / "user" / SERVICE_UNIT


def is_installed() -> bool:
    return unit_dest_path().is_file()


def is_active() -> bool:
    result = _run(["systemctl", "--user", "is-active", SERVICE_UNIT])
    return result.returncode == 0


def install_and_start() -> str:
    # Writes the unit file, reloads systemd and starts the daemon.
    dest = unit_dest_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(unit_content(), encoding="utf-8")

    result = _run(["systemctl", "--user", "daemon-reload"])
    if result.returncode != 0:
        raise RuntimeError(f"daemon-reload failed: {result.stdout.strip()}")

    result = _run(["systemctl", "--user", "start", SERVICE_UNIT])
    if result.returncode != 0:
        raise RuntimeError(f"start failed: {result.stdout.strip()}")

    result = _run(["systemctl", "--user", "enable", SERVICE_UNIT])
    if result.returncode != 0:
        raise RuntimeError(f"enable failed: {result.stdout.strip()}")


def stop_and_remove() -> str:
    # Stops the daemon, disables it and removes the unit file.
    _run(["systemctl", "--user", "stop", SERVICE_UNIT])
    _run(["systemctl", "--user", "disable", SERVICE_UNIT])

    dest = unit_dest_path()
    removed = False
    try:
        dest.unlink()
        removed = True
    except FileNotFoundError:
        pass

    _run(["systemctl", "--user", "daemon-reload"])
    return f"Removed {SERVICE_UNIT}" if removed else ""


def wait_for_socket(timeout: float = _UNIT_WAIT_TIMEOUT) -> bool:
    # Waits until the daemon socket accepts a connection.
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if daemon_common.socket_path().exists():
            return True
        time.sleep(_UNIT_WAIT_INTERVAL)
    return False
