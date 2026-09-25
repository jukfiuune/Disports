# App-side proxy to the Disports background daemon: mirrors the call surface
# of discord_client's embedded DiscordClient. Calls go as newline-JSON
# requests over the daemon unix socket; gateway events are forwarded to
# pyotherside exactly like the embedded client would emit them.
from __future__ import annotations

import json
import socket
import threading

import daemon_common
from daemon_common import PROTOCOL_VERSION

CALL_TIMEOUT = 60.0
CONNECT_TIMEOUT = 3.0


class DaemonUnavailable(Exception):
    pass


class DaemonProxy:
    def __init__(self, emitter) -> None:
        self.emitter = emitter
        self._sock: socket.socket | None = None
        self._send_lock = threading.Lock()
        self._pending: dict[int, list] = {}
        self._pending_lock = threading.Lock()
        self._next_id = 1
        self._reader: threading.Thread | None = None
        self._closed = threading.Event()

    # Connection

    @property
    def connected(self) -> bool:
        return self._sock is not None

    def connect(self) -> None:
        # Connect and validate the daemon's protocol version.
        path = daemon_common.socket_path()
        if not path.exists():
            raise DaemonUnavailable(f"No socket at {path}")
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(CONNECT_TIMEOUT)
        try:
            sock.connect(str(path))
        except OSError as exc:
            sock.close()
            raise DaemonUnavailable(f"Socket connect failed: {exc}") from exc

        self._closed.clear()
        self._sock = sock
        sock.settimeout(None)
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        try:
            handshake = self.call("ping")
        except Exception:
            self.close()
            raise
        if not isinstance(handshake, dict) or handshake.get("protocol") != PROTOCOL_VERSION:
            self.close()
            raise DaemonUnavailable("Daemon protocol mismatch")

    def close(self) -> None:
        self._closed.set()
        sock, self._sock = self._sock, None
        if sock:
            try:
                sock.close()
            except OSError:
                pass
        with self._pending_lock:
            pending = list(self._pending.values())
            self._pending.clear()
        for slot in pending:
            slot[0].set()

    # Wire

    def _read_loop(self) -> None:
        buffer = bytearray()
        sock = self._sock
        try:
            while not self._closed.is_set() and sock is not None:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                buffer.extend(chunk)
                while True:
                    newline = buffer.find(b"\n")
                    if newline < 0:
                        break
                    line = bytes(buffer[:newline])
                    del buffer[: newline + 1]
                    if line.strip():
                        self._handle_line(line)
        except OSError:
            pass
        finally:
            self.close()

    def _handle_line(self, raw: bytes) -> None:
        try:
            message = json.loads(raw.decode("utf-8"))
        except ValueError:
            return
        if "event" in message:
            self.emitter(str(message["event"]), message.get("data") or {})
            return
        request_id = message.get("id")
        with self._pending_lock:
            slot = self._pending.pop(request_id, None)
        if slot is not None:
            slot[1] = message
            slot[0].set()

    def call(self, method: str, args: list | None = None):
        if not self.connected:
            raise DaemonUnavailable("Daemon not connected")
        with self._pending_lock:
            request_id = self._next_id
            self._next_id += 1
            done = threading.Event()
            slot = [done, None]
            self._pending[request_id] = slot

        request = json.dumps(
            {"id": request_id, "method": method, "args": list(args or [])},
            separators=(",", ":"),
        )
        try:
            with self._send_lock:
                self._sock.sendall((request + "\n").encode("utf-8"))
        except (OSError, AttributeError) as exc:
            with self._pending_lock:
                self._pending.pop(request_id, None)
            raise DaemonUnavailable(f"Send failed: {exc}") from exc

        if not done.wait(CALL_TIMEOUT):
            with self._pending_lock:
                self._pending.pop(request_id, None)
            raise DaemonUnavailable(f"Timeout waiting for {method}")

        response = slot[1]
        if response is None:
            raise DaemonUnavailable("Daemon connection closed")
        if response.get("exception"):
            raise RuntimeError(response.get("error", "Daemon call failed"))
        return response.get("result")


def proxy_available() -> bool:
    return daemon_common.socket_path().exists()
