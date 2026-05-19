from __future__ import annotations

import base64
import hashlib
import json
import threading
from typing import Callable

import qrcode
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.hashes import SHA256
from websocket import ABNF

from .errors import GatewayClosed
from .gateway import DiscordWsClient
from .http import DiscordHTTP, DiscordHTTPError


REMOTE_AUTH_GATEWAY_URL = "wss://remote-auth-gateway.discord.gg/?v=2"
REMOTE_AUTH_URL_PREFIX = "https://discord.com/ra/"


def _url_to_data_uri(url: str) -> str:
    # Render a QR code for *url* and return an SVG data URI (no PIL needed).
    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        border=2,
    )
    qr.add_data(url)
    qr.make(fit=True)
    matrix = qr.get_matrix()

    box = 10  # px per module
    size = len(matrix)
    dim = size * box

    rects = []
    for y, row in enumerate(matrix):
        for x, dark in enumerate(row):
            if dark:
                rects.append(
                    f'<rect x="{x * box}" y="{y * box}" '
                    f'width="{box}" height="{box}"/>'
                )

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{dim}" height="{dim}" viewBox="0 0 {dim} {dim}">'
        f'<rect width="{dim}" height="{dim}" fill="white"/>'
        f'<g fill="black">{"".join(rects)}</g>'
        f'</svg>'
    )

    b64 = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{b64}"


class DiscordRemoteAuth:
    def __init__(
        self,
        http: DiscordHTTP | None = None,
        emitter: Callable[[str, dict], None] | None = None,
    ) -> None:
        self.emitter = emitter
        self.http = http or DiscordHTTP()
        self._ws: DiscordWsClient | None = None
        self._thread: threading.Thread | None = None
        self._heartbeat_thread: threading.Thread | None = None
        self._heartbeat_stop = threading.Event()
        self._stop = threading.Event()
        self._private_key: rsa.RSAPrivateKey | None = None
        self._expected_fingerprint = ""

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._stop_heartbeat()
        if self._ws:
            self._ws.close()

    def _run(self) -> None:
        try:
            self._private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048, backend=default_backend())
            self._ws = DiscordWsClient(REMOTE_AUTH_GATEWAY_URL)
            self._ws.connect()

            while not self._stop.is_set():
                opcode, payload = self._ws.recv_data()
                if opcode != ABNF.OPCODE_TEXT:
                    continue
                self._handle_message(json.loads(payload.decode("utf-8")))
        except GatewayClosed:
            if not self._stop.is_set():
                self._emit("qr_login_error", {"error": "QR login connection closed."})
        except DiscordHTTPError as exc:
            self._emit("qr_login_error", {"error": f"Discord QR login failed: {exc.display_message()}."})
        except Exception as exc:
            if not self._stop.is_set():
                self._emit("qr_login_error", {"error": f"QR login failed: {exc}"})
        finally:
            self._stop_heartbeat()
            if self._ws:
                self._ws.close()
                self._ws = None

    def _handle_message(self, message: dict) -> None:
        op = message.get("op", "")
        if op == "hello":
            self._start_heartbeat(message.get("heartbeat_interval"))
            self._send_init()
            return
        if op == "nonce_proof":
            self._send_nonce_proof(message.get("encrypted_nonce", ""))
            return
        if op == "pending_remote_init":
            fingerprint = message.get("fingerprint", "")
            if fingerprint:
                if fingerprint != self._expected_fingerprint:
                    self._emit("qr_login_error", {"error": "Discord QR login fingerprint mismatch."})
                    self.stop()
                    return
                url = REMOTE_AUTH_URL_PREFIX + fingerprint
                self._emit("qr_login_image", {"dataUri": _url_to_data_uri(url)})
            return
        if op == "pending_ticket":
            self._emit_pending_user(message.get("encrypted_user_payload", ""))
            return
        if op == "pending_login":
            self._complete_login(message.get("ticket", ""))
            return
        if op == "cancel":
            self._emit("qr_login_error", {"error": "QR login was canceled on your phone."})
            self.stop()

    def _send_init(self) -> None:
        assert self._private_key is not None
        assert self._ws is not None
        public_key = self._private_key.public_key().public_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        self._expected_fingerprint = base64.urlsafe_b64encode(
            hashlib.sha256(public_key).digest()
        ).decode("ascii").rstrip("=")
        self._ws.send_json(
            {
                "op": "init",
                "encoded_public_key": base64.b64encode(public_key).decode("ascii"),
            }
        )

    def _send_nonce_proof(self, encrypted_nonce: str) -> None:
        assert self._private_key is not None
        assert self._ws is not None
        nonce = self._private_key.decrypt(
            base64.b64decode(encrypted_nonce),
            padding.OAEP(
                mgf=padding.MGF1(algorithm=SHA256()),
                algorithm=SHA256(),
                label=None,
            ),
        )
        proof = base64.urlsafe_b64encode(nonce).decode("ascii").rstrip("=")
        self._ws.send_json({"op": "nonce_proof", "nonce": proof})

    def _start_heartbeat(self, interval_ms: object) -> None:
        self._stop_heartbeat()
        try:
            interval = float(interval_ms) / 1000.0
        except (TypeError, ValueError):
            interval = 41.25
        interval = max(interval, 1.0)
        self._heartbeat_stop.clear()
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            args=(interval,),
            daemon=True,
        )
        self._heartbeat_thread.start()

    def _stop_heartbeat(self) -> None:
        self._heartbeat_stop.set()
        self._heartbeat_thread = None

    def _heartbeat_loop(self, interval: float) -> None:
        while not self._heartbeat_stop.wait(interval):
            if self._stop.is_set() or not self._ws:
                return
            try:
                self._ws.send_json({"op": "heartbeat"})
            except Exception:
                return

    def _emit_pending_user(self, encrypted_user_payload: str) -> None:
        payload = self._decrypt_text(encrypted_user_payload)
        if not payload:
            self._emit("qr_login_pending", {"message": "Confirm the login on your phone."})
            return
        user_id, discriminator, avatar, username = (payload.split(":", 3) + ["", "", "", ""])[:4]
        display_name = username or "this account"
        suffix = f"#{discriminator}" if discriminator and discriminator != "0" else ""
        self._emit(
            "qr_login_pending",
            {
                "message": f"Confirm the login for {display_name}{suffix} on your phone.",
                "userId": user_id,
                "username": username,
                "discriminator": discriminator,
                "avatar": "" if avatar == "0" else avatar,
            },
        )

    def _decrypt_text(self, value: str) -> str:
        if not value or not self._private_key:
            return ""
        try:
            return self._private_key.decrypt(
                base64.b64decode(value),
                padding.OAEP(
                    mgf=padding.MGF1(algorithm=SHA256()),
                    algorithm=SHA256(),
                    label=None,
                ),
            ).decode("utf-8")
        except Exception:
            return ""

    def _complete_login(self, ticket: str) -> None:
        if not ticket or self._stop.is_set():
            return
        assert self._private_key is not None
        response = self.http.request(
            "POST",
            "users/@me/remote-auth/login",
            json_body={"ticket": ticket},
            auth=False,
        )
        encrypted_token = (response or {}).get("encrypted_token", "")
        token = self._decrypt_text(encrypted_token)
        if not token:
            self._emit("qr_login_error", {"error": "Discord QR login returned an unreadable token."})
            self.stop()
            return
        self._emit("qr_login_token", {"token": token})
        self.stop()

    def _emit(self, name: str, payload: dict) -> None:
        if self.emitter:
            self.emitter(name, payload)
