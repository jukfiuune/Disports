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
        super().__init__(f"Discord API request failed with status {status}")


class DiscordHTTP:
    def __init__(self) -> None:
        self.token: str | None = None
        self._pool = urllib3.PoolManager(
            timeout=urllib3.Timeout(connect=10.0, read=30.0),
            retries=False,
        )
        self._default_headers = {
            "Accept": "*/*",
            "Accept-Encoding": "identity",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
            "X-Super-Properties": build_super_properties(),
        }
        self._rate_limit_until = 0.0

    def set_token(self, token: str | None) -> None:
        self.token = token.strip() if token else None

    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = dict(self._default_headers)
        if self.token:
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
                    self._rate_limit_until = max(
                        self._rate_limit_until,
                        time.monotonic() + min(wait, 30.0),
                    )
        except (ValueError, TypeError):
            return

    def _wait_if_needed(self) -> None:
        now = time.monotonic()
        if now < self._rate_limit_until:
            time.sleep(self._rate_limit_until - now)

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        headers: dict[str, str] | None = None,
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
            headers=self._headers(headers),
        )
        text = response.data.decode("utf-8", errors="replace")

        if response.status < 400:
            self._respect_rate_limit(response)
            if not text:
                return None
            return json.loads(text)

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
                _429_attempts=_429_attempts - 1,
            )

        raise DiscordHTTPError(response.status, text)
