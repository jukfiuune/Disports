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
import html
import json
import os
import re
import signal
import socket
import sys
import threading
import traceback
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import daemon_common
from daemon_common import PROTOCOL_VERSION
from daemon_notifications import Notifier, build_envelope, postal_app_id
from disports_discord import DiscordClient

USER_MENTION_RE = re.compile(r"<@!?(\d+)>")


def _plain_text(rich: str) -> str:
    text = re.sub(r"<[^>]+>", "", str(rich or ""))
    return html.unescape(text).strip()


def _media_label(medias: list) -> str:
    for media in medias or []:
        kind = str((media or {}).get("messageType") or "")
        if kind == "image":
            return "📷 Photo"
        if kind == "video":
            return "🎥 Video"
        if kind == "audio":
            return "🎵 Audio"
        if kind == "link":
            return "🔗 Link"
        if kind:
            return "📎 File"
    return ""


def _channel_summary(state, channel_id: str, author: str, text: str):
    # Returns (summary, body) for a notification from message context.
    channel = state.get_channel(channel_id) or {}
    guild_id = state.get_guild_for_channel(channel_id) or ""
    if guild_id:
        guild_name = state.guild_name(guild_id) or ""
        channel_name = str(channel.get("name") or "channel")
        summary = f"{guild_name} • #{channel_name}" if guild_name else f"#{channel_name}"
        return summary, f"{author}: {text}"
    group_name = str(channel.get("name") or "").strip()
    if not group_name and channel.get("recipients"):
        group_name = state.group_name(channel)
    if group_name and group_name != author:
        return group_name, f"{author}: {text}"
    return author, text


class DaemonServer:
    def __init__(self, socket_path) -> None:
        self.socket_path = socket_path
        self._dispatch_lock = threading.RLock()
        self._clients_lock = threading.Lock()
        self._clients: list[socket.socket] = []
        self._stop = threading.Event()
        self._next_id = 1
        self._notifications_enabled = daemon_common.read_settings()[
            daemon_common.SETTING_NOTIFICATIONS
        ]
        self._posted_tags: dict[str, bool] = {}
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
            "ack_message": self.client.ack_message,
            "mark_seen": self.client.mark_seen,
            "set_active_channel": self.client.set_active_channel,
            "resolve_channel": self.client.resolve_channel,
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
        try:
            daemon_common.token_path().unlink()
        except FileNotFoundError:
            pass
        return {"ok": True}

    # Event broadcast + notifications

    def _on_event(self, name: str, payload: dict) -> None:
        self._broadcast(name, payload)
        if name == "message_create":
            self._maybe_notify(payload)

    def _maybe_notify(self, message: dict) -> None:
        if not self._notifications_enabled:
            return
        with self._clients_lock:
            app_attached = bool(self._clients)
        if app_attached:
            return  # the app holds the socket and owns notifications itself
        try:
            if not isinstance(message, dict):
                return
            if str(message.get("displayKind") or "") == "system":
                return
            me = str((self.client.state.me or {}).get("id") or "")
            if not me:
                return
            author_id = str(message.get("authorId") or "")
            if author_id == me:
                return
            channel_id = str(message.get("channelId") or "")
            if not channel_id:
                return

            is_dm = not (self.client.state.get_guild_for_channel(channel_id) or "")
            mentioned = any(
                match.group(1) == me
                for match in USER_MENTION_RE.finditer(str(message.get("rawBody") or ""))
            )
            if not (is_dm or mentioned):
                return

            text = _plain_text(message.get("body") or "")
            if not text:
                text = _media_label(message.get("medias") or [])
            if not text:
                return

            summary, body = _channel_summary(
                self.client.state, channel_id,
                str(message.get("author") or "Unknown"), text,
            )
            envelope = build_envelope(
                summary,
                body,
                tag=channel_id,
                timestamp=str(message.get("rawTimestamp") or ""),
            )
            if channel_id in self._posted_tags:
                self.notifier.clear_persistent(self._app_id, [channel_id])
            if self.notifier.post(self._app_id, envelope):
                self._posted_tags[channel_id] = True
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
        tags = list(self._posted_tags)
        self._posted_tags.clear()
        try:
            self.notifier.clear_persistent(self._app_id, tags)
            self.notifier.set_counter(self._app_id, 0, False)
        except Exception:
            traceback.print_exc()

    # Event broadcast

    def _broadcast(self, name: str, payload: dict) -> None:
        line = json.dumps({"event": name, "data": payload}, separators=(",", ":"))
        with self._clients_lock:
            dead: list[socket.socket] = []
            for conn in self._clients:
                try:
                    conn.sendall((line + "\n").encode("utf-8"))
                except OSError:
                    dead.append(conn)
            for conn in dead:
                self._clients.remove(conn)
        if dead:
            for conn in dead:
                try:
                    conn.close()
                except OSError:
                    pass

    # Request handling

    def _handle_line(self, conn: socket.socket, raw: bytes) -> None:
        try:
            request = json.loads(raw.decode("utf-8"))
        except ValueError as exc:
            self._send(conn, {"id": None, "ok": False, "error": f"Bad request: {exc}", "exception": True})
            return

        request_id = request.get("id")
        method = request.get("method", "")
        args = request.get("args") or []

        if method == "ping":
            self._send(conn, {
                "id": request_id,
                "ok": True,
                "result": {
                    "protocol": PROTOCOL_VERSION,
                    "gatewayConnected": self.client.gateway is not None,
                },
            })
            return

        handler = self.methods.get(method)
        if handler is None:
            self._send(conn, {
                "id": request_id,
                "ok": False,
                "error": f"Unknown method: {method}",
                "exception": True,
            })
            return

        with self._dispatch_lock:
            try:
                result = handler(*args)
            except Exception as exc:
                traceback.print_exc()
                self._send(conn, {
                    "id": request_id,
                    "ok": False,
                    "error": str(exc),
                    "exception": True,
                })
                return

        self._send(conn, {"id": request_id, "ok": True, "result": result})

    def _send(self, conn: socket.socket, payload: dict) -> None:
        try:
            conn.sendall((json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8"))
        except OSError:
            pass

    def _serve_connection(self, conn: socket.socket) -> None:
        conn.settimeout(None)
        buffer = bytearray()
        try:
            while not self._stop.is_set():
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
                        self._handle_line(conn, line)
        except OSError:
            pass
        finally:
            with self._clients_lock:
                if conn in self._clients:
                    self._clients.remove(conn)
            try:
                conn.close()
            except OSError:
                pass

    # Lifecycle

    def _auto_connect(self) -> None:
        token = self.client_token_load().get("token", "")
        if not token:
            return
        result = self.client.login(token)
        if result.get("ok"):
            try:
                self.client.connect_gateway()
                print("daemon: gateway connected", flush=True)
            except Exception as exc:
                print(f"daemon: gateway connect failed: {exc}", flush=True)

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
            with self._clients_lock:
                self._clients.append(conn)
            threading.Thread(target=self._serve_connection, args=(conn,), daemon=True).start()

        server.close()
        try:
            self.socket_path.unlink()
        except FileNotFoundError:
            pass
        print("daemon: stopped", flush=True)

    def stop(self) -> None:
        self._stop.set()
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
