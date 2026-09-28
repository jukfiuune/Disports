# Disports background daemon: holds the single Discord gateway connection,
# serves the app over a unix socket and broadcasts gateway events to every
# connected client.
#
# Wire protocol (newline-delimited JSON):
#   request   {"id": 1, "method": "fetch_messages", "args": ["123", 50, ""]}
#   response  {"id": 1, "ok": true, "result": ...}
#             {"id": 1, "ok": false, "error": "...", "exception": true}
#   event     {"event": "message_create", "data": {...}}
from __future__ import annotations

import argparse
import json
import os
import queue
import signal
import socket
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import daemon_common
from daemon_common import PROTOCOL_VERSION
from daemon_notifications import Notifier, build_envelope, postal_app_id
from disports_discord import DiscordClient

# A client that stops reading (e.g. an app suspended by Lomiri) is dropped
# once its writes have made no progress for CLIENT_STALL_SECONDS; it
# reconnects and resyncs when it resumes. Healthy clients can absorb large
# bursts (member list chunks, presence storms); the hard cap only bounds
# memory.
CLIENT_STALL_SECONDS = 10.0
CLIENT_QUEUE_LIMIT = 50000
REQUEST_WORKERS = 8

# Methods that replace or tear down the Discord session. They are serialized
# with the automatic login loop so every path converges on one gateway.
SESSION_METHODS = {
    "save_token",
    "clear_token",
    "login",
    "connect_gateway",
    "disconnect",
    "reconnect",
    "start_qr_login",
    "stop_qr_login",
}


class _ClientConnection:
    # One attached app process. Writes go through a bounded queue drained by
    # a dedicated thread, so a client that stops reading can never block the
    # gateway thread that broadcasts events.

    def __init__(self, conn: socket.socket, on_dead) -> None:
        self.conn = conn
        self.foreground = True
        self._queue: queue.Queue[bytes | None] = queue.Queue(CLIENT_QUEUE_LIMIT)
        self._on_dead = on_dead
        self._dead = threading.Event()
        self._last_progress = time.monotonic()
        threading.Thread(target=self._write_loop, daemon=True).start()

    @property
    def alive(self) -> bool:
        return not self._dead.is_set()

    def send(self, payload: dict) -> None:
        if self._dead.is_set():
            return
        line = (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")
        stalled = (
            not self._queue.empty()
            and time.monotonic() - self._last_progress > CLIENT_STALL_SECONDS
        )
        if not stalled:
            try:
                self._queue.put_nowait(line)
                return
            except queue.Full:
                pass
        print("daemon: client stopped reading; dropping it", flush=True)
        self.close()

    def _write_loop(self) -> None:
        while not self._dead.is_set():
            line = self._queue.get()
            if line is None:
                break
            self._last_progress = time.monotonic()
            try:
                self.conn.sendall(line)
                self._last_progress = time.monotonic()
            except OSError:
                self.close()
                break

    def close(self) -> None:
        if self._dead.is_set():
            return
        self._dead.set()
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
        try:
            # Unblocks both the reader thread and a writer stuck in sendall.
            self.conn.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.conn.close()
        except OSError:
            pass
        self._on_dead(self)


class DaemonServer:
    def __init__(self, socket_path) -> None:
        self.socket_path = socket_path
        self._session_lock = threading.RLock()
        self._clients_lock = threading.Lock()
        self._clients: list[_ClientConnection] = []
        self._workers = ThreadPoolExecutor(max_workers=REQUEST_WORKERS)
        self._stop = threading.Event()
        self._auto_connect_cancel = threading.Event()
        self._notifications_enabled = daemon_common.read_settings()[
            daemon_common.SETTING_NOTIFICATIONS
        ]
        self._posted_tags: set[str] = set()
        self._tags_lock = threading.Lock()
        self._app_id = postal_app_id()
        self.notifier = Notifier()
        self.client = DiscordClient(emitter=self._on_event)

        self.methods = {
            "save_token": self.client_token_save,
            "load_token": self.client_token_load,
            "clear_token": self.client_token_clear,
            "set_preference": self.client.set_preference,
            "set_notifications": self.set_notifications,
            "login": self.client.login,
            "start_qr_login": self.client.start_qr_login,
            "stop_qr_login": self.client.stop_qr_login,
            "connect_gateway": self.client.connect_gateway,
            "disconnect": self.client.disconnect,
            "reconnect": self.client.reconnect,
            "fetch_private_channels": self.client.fetch_private_channels,
            "fetch_guild_channels": self.client.fetch_guild_channels,
            "fetch_guild_emojis": self.client.fetch_guild_emojis,
            "fetch_unicode_emojis": self.client.fetch_unicode_emojis,
            "fetch_messages": self.client.fetch_messages,
            "send_message": self.client.send_message,
            "edit_message": self.client.edit_message,
            "delete_message": self.client.delete_message,
            "ack_message": self.ack_message,
            "mark_seen": self.mark_seen,
            "set_active_channel": self.set_active_channel,
            "resolve_channel": self.client.resolve_channel,
            "channel_info": self.client.channel_info,
            "add_reaction": self.client.add_reaction,
            "remove_reaction": self.client.remove_reaction,
        }

    # Token helpers (files are shared with the app)

    def client_token_save(self, token: str) -> dict:
        raw = (token or "").strip()
        if not raw:
            return {"ok": False, "error": "Empty token."}
        path = daemon_common.token_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(raw, encoding="utf-8")
            os.chmod(path, 0o600)
            return {"ok": True}
        except OSError as exc:
            return {"ok": False, "error": f"Save fail: {exc}"}

    def client_token_load(self) -> dict:
        path = daemon_common.token_path()
        if not path.is_file():
            return {"token": ""}
        try:
            return {"token": path.read_text(encoding="utf-8").strip()}
        except OSError:
            return {"token": ""}

    def client_token_clear(self) -> dict:
        # Logout: drop the live session too, otherwise the daemon keeps
        # receiving (and notifying about) the old account's messages.
        self._auto_connect_cancel.set()
        self.client.disconnect()
        try:
            daemon_common.token_path().unlink()
        except FileNotFoundError:
            pass
        self.client.cache.clear()
        self._clear_notifications()
        return {"ok": True}

    # Read tracking: reading a channel anywhere dismisses its notification

    def set_active_channel(self, channel_id: str) -> bool:
        result = self.client.set_active_channel(channel_id)
        self._clear_channel_notification(channel_id)
        return result

    def ack_message(self, channel_id: str, message_id: str) -> dict:
        result = self.client.ack_message(channel_id, message_id)
        self._clear_channel_notification(channel_id)
        return result

    def mark_seen(self, channel_id: str, message_id: str) -> dict:
        result = self.client.mark_seen(channel_id, message_id)
        self._clear_channel_notification(channel_id)
        return result

    def _clear_channel_notification(self, channel_id: str) -> None:
        channel_id = str(channel_id or "")
        if not channel_id:
            return
        with self._tags_lock:
            if channel_id not in self._posted_tags:
                return
            self._posted_tags.discard(channel_id)
        try:
            self.notifier.clear_persistent(self._app_id, [channel_id])
        except Exception:
            traceback.print_exc()

    # Event broadcast + notifications

    def _on_event(self, name: str, payload: dict) -> None:
        self._broadcast(name, payload)
        if name == "message_create":
            self._maybe_notify(payload)

    def _app_in_foreground(self) -> bool:
        with self._clients_lock:
            return any(client.alive and client.foreground for client in self._clients)

    def _maybe_notify(self, message: dict) -> None:
        if not self._notifications_enabled or not isinstance(message, dict):
            return
        # A foreground app posts its own live notifications. A backgrounded
        # (and possibly suspended) one cannot, so the daemon takes over.
        if self._app_in_foreground():
            return
        summary = str(message.get("notifySummary") or "")
        if not summary:
            return
        try:
            channel_id = str(message.get("channelId") or "")
            envelope = build_envelope(
                summary,
                str(message.get("notifyBody") or ""),
                tag=channel_id,
                timestamp=str(message.get("rawTimestamp") or ""),
                action=f"disports://channel/{channel_id}",
            )
            with self._tags_lock:
                replace = channel_id in self._posted_tags
            if replace:
                self.notifier.clear_persistent(self._app_id, [channel_id])
            posted = self.notifier.post(self._app_id, envelope)
            print(
                f"notification: postal post channel={channel_id} ok={posted}",
                flush=True,
            )
            if posted:
                with self._tags_lock:
                    self._posted_tags.add(channel_id)
        except Exception:
            traceback.print_exc()

    def set_notifications(self, enabled: bool) -> dict:
        self._notifications_enabled = bool(enabled)
        daemon_common.write_setting(
            daemon_common.SETTING_NOTIFICATIONS, self._notifications_enabled
        )
        if not self._notifications_enabled:
            self._clear_notifications()
        return {"ok": True}

    def _clear_notifications(self) -> None:
        with self._tags_lock:
            tags = list(self._posted_tags)
            self._posted_tags.clear()
        try:
            self.notifier.clear_persistent(self._app_id, tags)
            self.notifier.set_counter(self._app_id, 0, False)
        except Exception:
            traceback.print_exc()

    def _broadcast(self, name: str, payload: dict) -> None:
        with self._clients_lock:
            clients = list(self._clients)
        for client in clients:
            client.send({"event": name, "data": payload})

    def _remove_client(self, client: _ClientConnection) -> None:
        with self._clients_lock:
            if client in self._clients:
                self._clients.remove(client)
            detached = not self._clients
        if detached:
            self.client.set_active_channel("")

    # Request handling

    def _handle_line(self, client: _ClientConnection, raw: bytes) -> None:
        try:
            request = json.loads(raw.decode("utf-8"))
        except ValueError as exc:
            client.send({"id": None, "ok": False, "error": f"Bad request: {exc}", "exception": True})
            return

        request_id = request.get("id")
        method = request.get("method", "")
        args = request.get("args") or []

        if method == "ping":
            client.send({
                "id": request_id,
                "ok": True,
                "result": {
                    "protocol": PROTOCOL_VERSION,
                    "gatewayConnected": self.client.gateway is not None,
                },
            })
            return

        if method == "set_app_foreground":
            client.foreground = bool(args[0]) if args else True
            client.send({"id": request_id, "ok": True, "result": True})
            return

        handler = self.methods.get(method)
        if handler is None:
            client.send({
                "id": request_id,
                "ok": False,
                "error": f"Unknown method: {method}",
                "exception": True,
            })
            return

        # Run off the connection's reader thread so slow Discord requests do
        # not hold up unrelated calls from the same app.
        self._workers.submit(self._run_request, client, request_id, method, handler, args)

    def _run_request(self, client, request_id, method, handler, args) -> None:
        try:
            if method in SESSION_METHODS:
                with self._session_lock:
                    result = handler(*args)
            else:
                result = handler(*args)
        except Exception as exc:
            traceback.print_exc()
            client.send({
                "id": request_id,
                "ok": False,
                "error": str(exc),
                "exception": True,
            })
            return
        client.send({"id": request_id, "ok": True, "result": result})

    def _serve_connection(self, client: _ClientConnection) -> None:
        conn = client.conn
        buffer = bytearray()
        try:
            while not self._stop.is_set() and client.alive:
                chunk = conn.recv(65536)
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
                        self._handle_line(client, line)
        except OSError:
            pass
        finally:
            client.close()

    # Lifecycle

    def _auto_connect(self) -> None:
        token = self.client_token_load().get("token", "")
        if not token:
            return
        delay = 2
        self._auto_connect_cancel.clear()
        while not self._stop.is_set() and not self._auto_connect_cancel.is_set():
            # Serialize each attempt with session RPCs so notification
            # launches and background recovery converge on one gateway.
            with self._session_lock:
                if self._auto_connect_cancel.is_set():
                    return
                result = self.client.login(token)
                if result.get("ok"):
                    try:
                        self.client.connect_gateway()
                        print("daemon: gateway connected", flush=True)
                        return
                    except Exception as exc:
                        result = {
                            "ok": False,
                            "error": str(exc),
                            "retryable": True,
                        }

            if not result.get("retryable"):
                print(
                    f"daemon: automatic login stopped: {result.get('error', 'unknown error')}",
                    flush=True,
                )
                return
            print(
                f"daemon: Discord unavailable; retrying in {delay}s: "
                f"{result.get('error', 'network error')}",
                flush=True,
            )
            if self._auto_connect_cancel.wait(delay) or self._stop.is_set():
                return
            delay = min(delay * 2, 60)

    def run(self) -> None:
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.socket_path.unlink()
        except FileNotFoundError:
            pass

        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(self.socket_path))
        os.chmod(self.socket_path, 0o600)
        server.listen(8)
        server.settimeout(0.5)
        print(f"daemon: listening on {self.socket_path}", flush=True)

        threading.Thread(target=self._auto_connect, daemon=True).start()

        while not self._stop.is_set():
            try:
                conn, _ = server.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            conn.settimeout(None)
            client = _ClientConnection(conn, self._remove_client)
            with self._clients_lock:
                self._clients.append(client)
            threading.Thread(target=self._serve_connection, args=(client,), daemon=True).start()

        server.close()
        try:
            self.socket_path.unlink()
        except FileNotFoundError:
            pass
        print("daemon: stopped", flush=True)

    def stop(self) -> None:
        self._stop.set()
        self._auto_connect_cancel.set()
        try:
            self.client.flush_cache()
        except Exception:
            pass
        try:
            self._clear_notifications()
        except Exception:
            pass
        self.notifier.close()
        try:
            if self.client.gateway:
                self.client.gateway.stop()
        except Exception:
            pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Disports background daemon")
    parser.add_argument("--socket", default="", help="Override the unix socket path")
    args = parser.parse_args()

    path = Path(args.socket) if args.socket else daemon_common.socket_path()
    server = DaemonServer(path)

    def handle_signal(_signum, _frame) -> None:
        server.stop()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)
    server.run()


if __name__ == "__main__":
    main()
