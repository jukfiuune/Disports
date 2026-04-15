from __future__ import annotations

import base64
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
        emitter: Callable[[str, dict], None] | None = None,
    ) -> None:
        self.emitter = emitter
        self.http = DiscordHTTP()
        self._ws: DiscordWsClient | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._private_key: rsa.RSAPrivateKey | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
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
            self._emit("qr_login_error", {"error": f"Discord QR login failed ({exc.status})."})
        except Exception as exc:
            if not self._stop.is_set():
                self._emit("qr_login_error", {"error": f"QR login failed: {exc}"})
        finally:
            if self._ws:
                self._ws.close()
                self._ws = None

    def _handle_message(self, message: dict) -> None:
        op = message.get("op", "")
        if op == "hello":
            self._send_init()
            return
        if op == "nonce_proof":
            self._send_nonce_proof(message.get("encrypted_nonce", ""))
            return
        if op == "pending_remote_init":
            fingerprint = message.get("fingerprint", "")
            if fingerprint:
                url = REMOTE_AUTH_URL_PREFIX + fingerprint
                self._emit("qr_login_image", {"dataUri": _url_to_data_uri(url)})
            return
        if op == "pending_ticket":
            self._emit("qr_login_pending", {"message": "Confirm the login on your phone."})
            return
        if op == "pending_login":
            self._complete_login(message.get("ticket", ""))

    def _send_init(self) -> None:
        assert self._private_key is not None
        assert self._ws is not None
        public_key = self._private_key.public_key().public_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
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

    def _complete_login(self, ticket: str) -> None:
        if not ticket or self._stop.is_set():
            return
        assert self._private_key is not None
        response = self.http.request(
            "POST",
            "users/@me/remote-auth/login",
            json_body={"ticket": ticket},
        )
        encrypted_token = (response or {}).get("encrypted_token", "")
        token = self._private_key.decrypt(
            base64.b64decode(encrypted_token),
            padding.OAEP(
                mgf=padding.MGF1(algorithm=SHA256()),
                algorithm=SHA256(),
                label=None,
            ),
        ).decode("utf-8")
        self._emit("qr_login_token", {"token": token})
        self.stop()

    def _emit(self, name: str, payload: dict) -> None:
        if self.emitter:
            self.emitter(name, payload)
