from __future__ import annotations

import base64
import json
import platform

API_VERSION = 9
API_BASE = f"https://discord.com/api/v{API_VERSION}"
GATEWAY_URL = f"wss://gateway.discord.gg/?encoding=json&v={API_VERSION}&compress=zlib-stream"

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64; rv:115.0) "
    "Gecko/20100101 Firefox/115.0"
)


def build_super_properties() -> str:
    payload = {
        "os": platform.system() or "Linux",
        "browser": "Firefox",
        "device": "",
        "system_locale": "en-US",
        "browser_user_agent": USER_AGENT,
        "browser_version": "115.0",
        "os_version": platform.release(),
        "referrer": "",
        "referring_domain": "",
        "release_channel": "stable",
        "client_build_number": 9999,
        "client_event_source": None,
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.b64encode(raw).decode("ascii")
