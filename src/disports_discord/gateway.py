from __future__ import annotations

import json
import random
import ssl
import threading
import time
import zlib
from typing import Callable

import websocket
from websocket import ABNF, WebSocketException

from .constants import GATEWAY_URL, USER_AGENT
from .errors import GatewayClosed, ReconnectRequested


class DiscordWsClient:
    """Thin sync WebSocket wrapper around websocket-client (RFC framing + TLS)."""

    def __init__(self, url: str) -> None:
        self._url = url
        self._ws: websocket.WebSocket | None = None
        self._send_lock = threading.Lock()

    def connect(self, extra_headers: dict[str, str] | None = None) -> None:
        hdrs = [
            f"User-Agent: {USER_AGENT}",
            "Origin: https://discord.com",
        ]
        if extra_headers:
            for name, value in extra_headers.items():
                hdrs.append(f"{name}: {value}")
        self._ws = websocket.create_connection(
            self._url,
            header=hdrs,
            timeout=60,
            sslopt={"cert_reqs": ssl.CERT_REQUIRED},
        )

    def send_json(self, payload: dict) -> None:
        if not self._ws:
            raise GatewayClosed("WebSocket not connected")
        data = json.dumps(payload, separators=(",", ":"))
        with self._send_lock:
            self._ws.send(data)

    def recv_data(self) -> tuple[int, bytes]:
        if not self._ws:
            raise GatewayClosed("WebSocket not connected")
        try:
            opcode, payload = self._ws.recv_data()
        except WebSocketException as exc:
            raise GatewayClosed(str(exc)) from exc
        if opcode == ABNF.OPCODE_CLOSE:
            raise GatewayClosed("Close frame received")
        if opcode == ABNF.OPCODE_PING:
            with self._send_lock:
                self._ws.pong(payload)
            return self.recv_data()
        return opcode, payload

    def close(self) -> None:
        if not self._ws:
            return
        try:
            self._ws.close()
        except Exception:
            pass
        finally:
            self._ws = None


class DiscordGateway:
    def __init__(
        self,
        token: str,
        event_handler: Callable[[str, dict], None],
        log_handler: Callable[[str], None] | None = None,
    ) -> None:
        self.token = token
        self.event_handler = event_handler
        self.log_handler = log_handler
        self.session_id: str | None = None
        self.resume_gateway_url: str | None = None
        self.seq: int | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._ws: DiscordWsClient | None = None
        self._heartbeat_thread: threading.Thread | None = None
        self._heartbeat_stop = threading.Event()
        self._heartbeat_interval = 41.25
        self._inflater = zlib.decompressobj()
        self._compressed_buffer = bytearray()
        self._reconnect_event = threading.Event()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._reconnect_event.clear()
        self._thread = threading.Thread(target=self._run_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._reconnect_event.set()
        self._stop_heartbeat()
        if self._ws:
            self._ws.close()

    def reconnect(self) -> None:
        self._reconnect_event.set()

    def _run_forever(self) -> None:
        attempt = 0
        while not self._stop.is_set():
            try:
                self._run_connection()
                attempt = 0
            except ReconnectRequested as exc:
                if exc.reset_session:
                    self.session_id = None
                    self.resume_gateway_url = None
                    self.seq = None
            except Exception as exc:
                self._log(f"Gateway error: {exc}")

            if self._stop.is_set():
                break

            attempt += 1
            self._reconnect_event.wait(min(2**attempt, 30))
            self._reconnect_event.clear()

    def _run_connection(self) -> None:
        self._reconnect_event.clear()
        gateway_url = self.resume_gateway_url or GATEWAY_URL
        self._ws = DiscordWsClient(gateway_url)
        self._ws.connect()
        self._inflater = zlib.decompressobj()
        self._compressed_buffer.clear()

        hello = self._recv_json()
        if hello.get("op") != 10:
            raise GatewayClosed("Expected HELLO from Discord gateway")

        self._heartbeat_interval = hello.get("d", {}).get("heartbeat_interval", 41250) / 1000.0
        self._start_heartbeat()

        if self.session_id and self.seq is not None:
            self._send_resume()
        else:
            self._send_identify()

        while not self._stop.is_set():
            payload = self._recv_json()
            self._handle_payload(payload)

    def _recv_json(self) -> dict:
        assert self._ws is not None
        while not self._stop.is_set():
            opcode, payload = self._ws.recv_data()
            if opcode == ABNF.OPCODE_TEXT:
                return json.loads(payload.decode("utf-8"))
            if opcode == ABNF.OPCODE_BINARY:
                self._compressed_buffer.extend(payload)
                if self._compressed_buffer[-4:] != b"\x00\x00\xff\xff":
                    continue
                decoded = self._inflater.decompress(bytes(self._compressed_buffer))
                self._compressed_buffer.clear()
                return json.loads(decoded.decode("utf-8"))
        raise GatewayClosed("Gateway receive loop stopped")

    def _handle_payload(self, payload: dict) -> None:
        op = payload.get("op")
        if payload.get("s") is not None:
            self.seq = payload["s"]

        if op == 0:
            event_type = payload.get("t", "")
            data = payload.get("d", {})
            if event_type == "READY":
                self.session_id = data.get("session_id")
                self.resume_gateway_url = data.get("resume_gateway_url") or GATEWAY_URL
            self.event_handler(event_type, data)
            return

        if op == 1:
            self._send_heartbeat()
            return

        if op == 7:
            raise ReconnectRequested()

        if op == 9:
            raise ReconnectRequested(reset_session=True)

    def _start_heartbeat(self) -> None:
        self._stop_heartbeat()
        self._heartbeat_stop.clear()
        self._heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self._heartbeat_thread.start()

    def _stop_heartbeat(self) -> None:
        self._heartbeat_stop.set()
        self._heartbeat_thread = None

    def _heartbeat_loop(self) -> None:
        time.sleep(random.random() * min(self._heartbeat_interval, 5.0))
        while not self._heartbeat_stop.is_set() and not self._stop.is_set():
            self._send_heartbeat()
            self._heartbeat_stop.wait(self._heartbeat_interval)

    def _send_heartbeat(self) -> None:
        if not self._ws:
            return
        self._ws.send_json({"op": 1, "d": self.seq})

    def _send_identify(self) -> None:
        assert self._ws is not None
        self._ws.send_json(
            {
                "op": 2,
                "d": {
                    "token": self.token,
                    "compress": False,
                    "properties": {
                        "os": "Linux",
                        "browser": "Firefox",
                        "device": "",
                    },
                },
            }
        )

    def _send_resume(self) -> None:
        assert self._ws is not None
        self._ws.send_json(
            {
                "op": 6,
                "d": {
                    "token": self.token,
                    "session_id": self.session_id,
                    "seq": self.seq,
                },
            }
        )

    def _log(self, message: str) -> None:
        if self.log_handler:
            self.log_handler(message)
