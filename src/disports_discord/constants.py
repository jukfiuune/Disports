from __future__ import annotations

import base64
import json
import platform
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
