from __future__ import annotations

import json
import time
from typing import Any
from urllib.parse import urlencode

import urllib3

from .constants import API_BASE, USER_AGENT, build_super_properties


class DiscordHTTPError(Exception):
    def __init__(self, status: int, body: str):
        self.status = status
        self.body = body
        self.code: int | None = None
        self.message = ""
        self.errors: Any = None
        try:
            payload = json.loads(body) if body else {}
        except json.JSONDecodeError:
            payload = {}
        if isinstance(payload, dict):
            try:
                self.code = int(payload["code"]) if payload.get("code") is not None else None
            except (TypeError, ValueError):
                self.code = None
            self.message = str(payload.get("message") or "")
            self.errors = payload.get("errors")
        super().__init__(f"Discord API request failed with status {status}")

    def display_message(self) -> str:
        parts = [f"Discord API error ({self.status})"]
        if self.code is not None:
            parts.append(f"code {self.code}")
        if self.message:
            return f"{' / '.join(parts)}: {self.message}"
        if self.body:
            return f"{' / '.join(parts)}: {self.body[:300]}"
        return f"{' / '.join(parts)}: no response details"


class DiscordHTTP:
    def __init__(self) -> None:
        import threading
        self.token: str | None = None
        self._pool = urllib3.PoolManager(
            timeout=urllib3.Timeout(connect=10.0, read=30.0),
            retries=False,
        )
        self._lock = threading.Lock()
        self._default_headers = {
            "Accept": "*/*",
            "Accept-Encoding": "gzip, deflate",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
            "X-Super-Properties": build_super_properties(),
        }
        self._rate_limit_until = 0.0

    def set_token(self, token: str | None) -> None:
        self.token = token.strip() if token else None

    def _headers(
        self,
        extra: dict[str, str] | None = None,
        *,
        include_auth: bool = True,
    ) -> dict[str, str]:
        headers = dict(self._default_headers)
        if include_auth and self.token:
            headers["Authorization"] = self.token
        if extra:
            headers.update(extra)
        return headers

    def _respect_rate_limit(self, response: urllib3.HTTPResponse) -> None:
        remaining = response.headers.get("X-RateLimit-Remaining")
        reset_after = response.headers.get("X-RateLimit-Reset-After")
        if remaining is None or reset_after is None:
            return
        try:
            if int(remaining) <= 0:
                wait = float(reset_after)
                if wait > 0:
                    with self._lock:
                        self._rate_limit_until = max(
                            self._rate_limit_until,
                            time.monotonic() + min(wait, 30.0),
                        )
        except (ValueError, TypeError):
            return

    def _wait_if_needed(self) -> None:
        with self._lock:
            now = time.monotonic()
            wait_time = self._rate_limit_until - now
        if wait_time > 0:
            time.sleep(wait_time)

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        headers: dict[str, str] | None = None,
        auth: bool = True,
        _429_attempts: int = 4,
    ) -> Any:
        self._wait_if_needed()

        url = f"{API_BASE}/{path.lstrip('/')}"
        if params:
            url = f"{url}?{urlencode(params)}"

        body = None
        if json_body is not None:
            body = json.dumps(json_body, separators=(",", ":")).encode("utf-8")

        response = self._pool.request(
            method.upper(),
            url,
            body=body,
            headers=self._headers(headers, include_auth=auth),
            decode_content=True,
        )

        if response.status < 400:
            self._respect_rate_limit(response)
            if not response.data:
                return None
            return json.loads(response.data)

        text = response.data.decode("utf-8", errors="replace")

        if response.status == 429 and _429_attempts > 0:
            retry_after = response.headers.get("Retry-After")
            try:
                wait = float(retry_after) if retry_after else 1.0
            except (ValueError, TypeError):
                wait = 1.0
            wait = min(max(wait, 0.5), 60.0)
            time.sleep(wait)
            return self.request(
                method,
                path,
                params=params,
                json_body=json_body,
                headers=headers,
                auth=auth,
                _429_attempts=_429_attempts - 1,
            )

        raise DiscordHTTPError(response.status, text)
