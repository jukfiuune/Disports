from __future__ import annotations

import base64
import json
import uuid
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

API_VERSION = 9
API_BASE = f"https://discord.com/api/v{API_VERSION}"
GATEWAY_ENCODING = "json"
GATEWAY_COMPRESSION = "zlib-stream"


def build_gateway_url(base_url: str = "wss://gateway.discord.gg/") -> str:
    """Return a Discord Gateway URL with this client's negotiated options."""
    parts = urlsplit(base_url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update(
        {
            "encoding": GATEWAY_ENCODING,
            "v": str(API_VERSION),
            "compress": GATEWAY_COMPRESSION,
        }
    )
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path or "/", urlencode(query), parts.fragment)
    )


GATEWAY_URL = build_gateway_url()

USER_AGENT = (
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:150.0) "
    "Gecko/20100101 Firefox/150.0"
)

import random

def _format_uuid(part1: int, part2: int) -> str:
    s = f"{part1:016x}{part2:016x}"
    return f"{s[:8]}-{s[8:12]}-{s[12:16]}-{s[16:20]}-{s[20:32]}"

def _generate_launch_signature() -> str:
    part1 = random.getrandbits(64)
    part2 = random.getrandbits(64)
    # Mask specific bits as seen in Discord Messenger
    part1 &= ~((1 << 11) | (1 << 24) | (1 << 38) | (1 << 48) | (1 << 55) | (1 << 61))
    part2 &= ~((1 << 11) | (1 << 20) | (1 << 27) | (1 << 36) | (1 << 44) | (1 << 55))
    return _format_uuid(part1, part2)

_LAUNCH_ID = _format_uuid(random.getrandbits(64), random.getrandbits(64))
_HEARTBEAT_SESSION_ID = _format_uuid(random.getrandbits(64), random.getrandbits(64))
_LAUNCH_SIGNATURE = _generate_launch_signature()

def build_super_properties() -> str:
    payload = {
        "os": "Linux",
        "browser": "Firefox",
        "device": "",
        "system_locale": "en-US",
        "has_client_mods": False,
        "browser_user_agent": USER_AGENT,
        "browser_version": "150.0",
        "os_version": "",
        "referrer": "",
        "referring_domain": "",
        "referrer_current": "https://discord.com/",
        "referring_domain_current": "discord.com",
        "release_channel": "stable",
        "client_build_number": 545032,
        "client_event_source": None,
        "client_launch_id": _LAUNCH_ID,
        "launch_signature": _LAUNCH_SIGNATURE,
        "client_heartbeat_session_id": _HEARTBEAT_SESSION_ID,
        "client_app_state": "focused",
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.b64encode(raw).decode("ascii")


GATEWAY_PROPERTIES = {
    "os": "Linux",
    "browser": "Firefox",
    "device": "",
    "system_locale": "en-US",
    "has_client_mods": False,
    "browser_user_agent": USER_AGENT,
    "browser_version": "150.0",
    "os_version": "",
    "referrer": "",
    "referring_domain": "",
    "referrer_current": "https://discord.com/",
    "referring_domain_current": "discord.com",
    "release_channel": "stable",
    "client_build_number": 545032,
    "client_event_source": None,
    "client_launch_id": _LAUNCH_ID,
    "launch_signature": _LAUNCH_SIGNATURE,
    "client_heartbeat_session_id": _HEARTBEAT_SESSION_ID,
    "client_app_state": "focused",
}
