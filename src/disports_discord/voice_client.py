"""
voice_client.py — Discord voice gateway and UDP client for Disports.

Changes from the ctypes/PulseAudio version
------------------------------------------
1. All audio I/O routed through qt_audio.QtPlayback / QtCapture instead of
   PulsePlayback / PulseCapture, so hardware routing is handled natively by
   the C++ VoiceAudio plugin.
2. speaking flag fixed: 0x01 (Microphone) instead of the previous 0x02
   (Soundshare), which was causing the remote party to not receive audio.
3. Mute state is forwarded to C++ via qt_audio.set_muted() so the hardware
   capture path is silenced rather than just suppressing the send.
4. Five Opus silence frames are sent on capture-loop exit before the UDP
   socket is closed, preventing server-side interpolation artefacts.
5. qt_audio.start_audio() / stop_audio() lifecycle calls added around
   the UDP session so the C++ plugin is properly initialised.
"""
from __future__ import annotations

import json
import socket
import ssl
import struct
import threading
import time
import uuid
from typing import Optional

import websocket
from websocket import ABNF

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    _HAS_AESGCM = True
except ImportError:
    _HAS_AESGCM = False
    AESGCM = None

from .dave_interop import DaveSession, libdave_status
from .qt_audio import (
    OpusDecoder, OpusEncoder,
    QtPlayback, QtCapture,
    set_speaker_route, set_muted,
    start_audio, stop_audio,
    _vlog,
)

_OPUS_SILENCE = bytes([0xF8, 0xFF, 0xFE])
_SILENCE_FRAMES = 5


class VoiceUdpClient:
    def __init__(self, ssrc: int):
        self.ssrc = ssrc
        self.secret_key: Optional[bytes] = None
        self.dave_session: Optional[DaveSession] = None

        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.settimeout(0.5)
        self.server_ip: Optional[str] = None
        self.server_port: Optional[int] = None
        self.local_ip: str = ""
        self.local_port: int = 0

        self._stop = threading.Event()
        self._recv_thread: Optional[threading.Thread] = None
        self._cap_thread: Optional[threading.Thread] = None

        self._send_sequence  = 0
        self._send_timestamp = 0
        self._send_nonce     = 0

        self._playback = QtPlayback()
        self._capture  = QtCapture()
        self._encoder  = OpusEncoder()
        self._decoders: dict[int, OpusDecoder] = {}

        _vlog(f"VoiceUDP init: encoder={'ok' if self._encoder._enc is not None else 'FAIL'}")

    def _get_decoder(self, ssrc: int) -> Optional[OpusDecoder]:
        if ssrc not in self._decoders:
            dec = OpusDecoder(channels=2)
            if dec._dec is None:
                return None
            self._decoders[ssrc] = dec
        return self._decoders[ssrc]

    def connect(self, ip: str, port: int) -> tuple[str, int]:
        self.server_ip   = ip
        self.server_port = port
        _vlog(f"UDP discovery: connecting to {ip}:{port} ssrc={self.ssrc}")
        self._sock.connect((ip, port))
        packet = struct.pack(">HHI", 0x0001, 70, self.ssrc) + b"\x00" * 66
        self._sock.send(packet)
        resp = self._sock.recv(74)
        local_ip   = resp[8:72].decode("ascii").rstrip("\x00")
        local_port = struct.unpack(">H", resp[72:74])[0]
        self.local_ip   = local_ip
        self.local_port = local_port
        _vlog(f"UDP discovery: local address {local_ip}:{local_port}")
        return local_ip, local_port

    def start_receive_loop(self):
        self._stop.clear()
        start_audio()
        self._recv_thread = threading.Thread(
            target=self._receive_loop, daemon=True, name="voice-recv"
        )
        self._recv_thread.start()
        _vlog("UDP receive loop started")
        if self._encoder._enc is not None:
            self._cap_thread = threading.Thread(
                target=self._capture_loop, daemon=True, name="voice-cap"
            )
            self._cap_thread.start()
            _vlog("UDP capture loop started")
        else:
            _vlog("UDP capture loop disabled: Opus encoder unavailable")

    def stop(self):
        _vlog("VoiceUDP stopping")
        self._stop.set()
        stop_audio()
        try:
            self._sock.close()
        except Exception:
            pass
        for dec in self._decoders.values():
            dec.close()
        self._decoders.clear()
        self._encoder.close()

    def set_speakerphone(self, enabled: bool):
        set_speaker_route(enabled)

    def set_muted(self, muted: bool):
        set_muted(muted)

    def update_secret_key(self, key: bytes):
        self.secret_key = key
        _vlog(f"UDP secret key updated len={len(key)}")

    def _receive_loop(self):
        while not self._stop.is_set():
            try:
                data = self._sock.recv(4096)
            except socket.timeout:
                continue
            except Exception:
                if not self._stop.is_set():
                    _vlog("UDP receive loop stopped after socket error")
                break
            if len(data) < 12:
                continue
            if data[0] == 0x00 and data[1] == 0x02:
                continue
            payload_type = data[1] & 0x7F
            if 200 <= payload_type <= 204:
                continue
            if not self.secret_key:
                continue
            cc      = data[0] & 0x0F
            has_ext = bool(data[0] & 0x10)
            hdr_len = 12 + cc * 4
            if has_ext and len(data) > hdr_len + 4:
                hdr_len += 4 + struct.unpack_from(">H", data, hdr_len + 2)[0] * 4
            pkt_ssrc  = struct.unpack_from(">I", data, 8)[0]
            nonce_val = struct.unpack(">I", data[-4:])[0]
            nonce     = struct.pack(">I", nonce_val).ljust(12, b"\x00")
            ciphertext = data[hdr_len:-4]
            aad        = data[:hdr_len]
            try:
                if not _HAS_AESGCM:
                    continue
                decrypted = AESGCM(self.secret_key).decrypt(nonce, ciphertext, aad)
            except Exception:
                continue
            if decrypted == _OPUS_SILENCE:
                continue
            if not self.dave_session:
                continue
            opus_frame = self.dave_session.decrypt_audio_frame(pkt_ssrc, decrypted)
            if not opus_frame:
                continue
            dec = self._get_decoder(pkt_ssrc)
            if dec is None:
                continue
            pcm = dec.decode(opus_frame)
            if pcm:
                self._playback.write(pcm)

    def _capture_loop(self):
        while not self._stop.is_set():
            frame = self._capture.read_frame()
            if not frame:
                if self._stop.is_set():
                    break
                # No device available (capture disabled): avoid a busy-spin.
                # pullCaptureFrame() returns empty immediately when captureReady
                # is False, so we need a small sleep here in that path only.
                if not self._capture.available:
                    import time; time.sleep(0.02)
                continue
            if not self.secret_key or not self.dave_session:
                continue
            opus_data = self._encoder.encode(frame)
            if not opus_data:
                continue
            dave_frame = self.dave_session.encrypt_audio_frame(self.ssrc, opus_data)
            if not dave_frame:
                continue
            packet = self._build_rtp_packet(dave_frame)
            if packet and self.server_ip and self.server_port:
                try:
                    self._sock.sendto(packet, (self.server_ip, self.server_port))
                except Exception:
                    pass
        _vlog("Capture loop ending — sending silence frames")
        self._send_silence_frames()

    def _send_silence_frames(self):
        if not self.secret_key or not self.dave_session:
            return
        for _ in range(_SILENCE_FRAMES):
            dave_frame = self.dave_session.encrypt_audio_frame(self.ssrc, _OPUS_SILENCE)
            if not dave_frame:
                continue
            packet = self._build_rtp_packet(dave_frame)
            if packet and self.server_ip and self.server_port:
                try:
                    self._sock.sendto(packet, (self.server_ip, self.server_port))
                except Exception:
                    pass

    def _build_rtp_packet(self, payload: bytes) -> Optional[bytes]:
        hdr = bytearray(12)
        hdr[0] = 0x80
        hdr[1] = 0x78
        hdr[2:4] = struct.pack(">H", self._send_sequence)
        hdr[4:8] = struct.pack(">I", self._send_timestamp)
        hdr[8:12] = struct.pack(">I", self.ssrc)
        self._send_sequence  = (self._send_sequence + 1)   & 0xFFFF
        self._send_timestamp = (self._send_timestamp + 960) & 0xFFFFFFFF
        self._send_nonce     = (self._send_nonce + 1)       & 0xFFFFFFFF
        nonce = struct.pack(">I", self._send_nonce).ljust(12, b"\x00")
        try:
            if not _HAS_AESGCM:
                return None
            ciphertext = AESGCM(self.secret_key).encrypt(nonce, payload, bytes(hdr))
        except Exception:
            return None
        return bytes(hdr) + ciphertext + struct.pack(">I", self._send_nonce)


class VoiceGateway:
    def __init__(self, endpoint: str, token: str, session_id: str,
                 user_id: str, channel_id: str, server_id: Optional[str] = None):
        self.endpoint   = endpoint
        self.token      = token
        self.session_id = session_id
        self.user_id    = user_id
        self.channel_id = channel_id
        self.server_id  = server_id or channel_id

        self._ws: Optional[websocket.WebSocket] = None
        self._stop = threading.Event()
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._heartbeat_interval = 41.25
        self._seq       = -1
        self._send_lock = threading.Lock()

        self.pending_ssrc_map: dict[int, str] = {}
        self.pending_external_sender: Optional[bytes] = None
        self.pending_epoch       = -1
        self.pending_epoch_proto = 1
        self.udp: Optional[VoiceUdpClient] = None

    def start(self):
        self._stop.clear()
        _vlog(f"VoiceGW starting endpoint={self.endpoint} channel={self.channel_id}")
        threading.Thread(target=self._run, daemon=True).start()

    def stop(self):
        _vlog("VoiceGW stopping")
        self._stop.set()
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass
        if self.udp:
            self.udp.stop()

    def set_speakerphone(self, enabled: bool):
        if self.udp:
            self.udp.set_speakerphone(enabled)
        else:
            set_speaker_route(enabled)

    def set_muted(self, muted: bool):
        if self.udp:
            self.udp.set_muted(muted)
        else:
            set_muted(muted)

    def _run(self):
        url = f"wss://{self.endpoint}/?v=8"
        try:
            self._ws = websocket.create_connection(
                url, sslopt={"cert_reqs": ssl.CERT_REQUIRED}
            )
            _vlog(f"VoiceGW connected: {url}")
        except Exception as e:
            _vlog(f"VoiceGW connect FAILED: {e}")
            return

        identify = {
            "op": 0,
            "d": {
                "server_id":  self.server_id,
                "channel_id": self.channel_id,
                "user_id":    self.user_id,
                "session_id": self.session_id,
                "token":      self.token,
                "max_dave_protocol_version": 1,
            }
        }
        _vlog(f"VoiceGW identify: server={self.server_id} user={self.user_id}")
        self._send_json(identify)

        while not self._stop.is_set():
            try:
                opcode, payload = self._ws.recv_data()
                if opcode == ABNF.OPCODE_TEXT:
                    self._handle_json(json.loads(payload))
                elif opcode == ABNF.OPCODE_BINARY:
                    self._handle_binary(payload)
                elif opcode == ABNF.OPCODE_CLOSE:
                    _vlog(f"VoiceGW close: {self._format_close_payload(payload)}")
                    break
            except Exception as e:
                if not self._stop.is_set():
                    _vlog(f"VoiceGW receive error: {e}")
                break

    def _send_json(self, data: dict):
        try:
            with self._send_lock:
                if self._ws:
                    self._ws.send(json.dumps(data, separators=(",", ":")))
                    _vlog(f"VoiceGW -> op {data.get('op')}")
        except Exception as e:
            _vlog(f"VoiceGW send error: {e}")
            self.stop()

    def _send_binary(self, opcode: int, payload: bytes):
        packet = bytes([opcode]) + payload
        try:
            with self._send_lock:
                if self._ws:
                    self._ws.send_binary(packet)
                    _vlog(f"VoiceGW -> binary op {opcode} len={len(payload)}")
        except Exception as e:
            _vlog(f"VoiceGW binary send error: {e}")

    @staticmethod
    def _format_close_payload(payload) -> str:
        if not isinstance(payload, (bytes, bytearray)) or len(payload) < 2:
            return repr(payload)
        code   = struct.unpack(">H", payload[:2])[0]
        reason = bytes(payload[2:]).decode("utf-8", errors="replace")
        return f"code={code} reason={reason or '<empty>'}"

    def _handle_json(self, data: dict):
        op  = data.get("op")
        seq = data.get("seq")
        if seq is not None:
            self._seq = seq
        d = data.get("d") or {}
        _vlog(f"VoiceGW <- op {op}")

        if op == 2:    self._on_ready(d)
        elif op == 8:  self._on_hello(d)
        elif op == 4:  self._on_session_description(d)
        elif op == 5:  self._on_speaking(d)
        elif op == 12: self._on_client_connect(d)
        elif op == 16: self._on_capabilities_ack()
        elif op == 24: self._on_dave_prepare_epoch(d)

    def _on_ready(self, d: dict):
        ip, port, ssrc = d.get("ip"), d.get("port"), d.get("ssrc")
        _vlog(f"READY: ssrc={ssrc} server={ip}:{port}")
        self.udp = VoiceUdpClient(ssrc)
        try:
            self.udp.connect(ip, port)
        except Exception as exc:
            _vlog(f"UDP discovery FAILED: {exc}")
            return
        _vlog(f"UDP connected: local={self.udp.local_ip}:{self.udp.local_port}")
        self.udp.start_receive_loop()
        self._send_json({"op": 16, "d": {}})

    def _on_hello(self, d: dict):
        self._heartbeat_interval = d.get("heartbeat_interval", 41250) / 1000.0
        _vlog(f"VoiceGW HELLO heartbeat={self._heartbeat_interval:.3f}s")
        self._start_heartbeat()

    def _on_session_description(self, d: dict):
        if not self.udp:
            _vlog("SESSION_DESC ignored: UDP client is not ready")
            return
        secret_key = d.get("secret_key")
        if secret_key:
            self.udp.update_secret_key(bytes(secret_key))
            _vlog(f"SESSION_DESC: secret_key len={len(secret_key)}")

        dave_version = d.get("dave_protocol_version", 1)
        status = libdave_status()
        if not status["available"]:
            for error in status["errors"]:
                _vlog(f"libdave load error: {error}")

        _vlog(f"Init DaveSession proto={dave_version} channel={self.channel_id}")
        self.udp.dave_session = DaveSession()
        self.udp.dave_session.init(dave_version, self.channel_id, self.user_id)
        _vlog(f"DAVE session: {self.udp.dave_session.status_summary()}")

        for ssrc, uid in self.pending_ssrc_map.items():
            self.udp.dave_session.register_ssrc(ssrc, uid)

        if self.pending_external_sender:
            self.udp.dave_session.set_external_sender(self.pending_external_sender)
            _vlog(f"Applied pending external sender len={len(self.pending_external_sender)}")
            self.pending_external_sender = None

        if self.pending_epoch == 1:
            kp = self.udp.dave_session.reset_and_get_key_package(self.pending_epoch_proto)
            if kp:
                self._send_binary(26, kp)

        # FIX: was speaking=2 (Soundshare). Correct flag is 1 (Microphone, 1<<0).
        self._send_json({"op": 5, "d": {"speaking": 1, "delay": 0, "ssrc": self.udp.ssrc}})

    def _on_speaking(self, d: dict):
        spk_uid, spk_ssrc = d.get("user_id"), d.get("ssrc")
        if spk_uid and spk_ssrc:
            _vlog(f"SPEAKING: user={spk_uid} ssrc={spk_ssrc}")
            self.pending_ssrc_map[spk_ssrc] = str(spk_uid)
            if self.udp and self.udp.dave_session:
                self.udp.dave_session.register_ssrc(spk_ssrc, str(spk_uid))

    def _on_client_connect(self, d: dict):
        uid, ssrc = d.get("user_id"), d.get("ssrc")
        _vlog(f"CLIENT_CONNECT: user={uid} ssrc={ssrc}")
        if uid and ssrc and self.udp and self.udp.dave_session:
            self.udp.dave_session.register_ssrc(ssrc, str(uid))

    def _on_capabilities_ack(self):
        if not (self.udp and self.udp.local_ip):
            _vlog("CAPABILITIES_ACK ignored: UDP local address missing")
            return
        _vlog("CAPABILITIES_ACK: selecting UDP transport")
        self._send_json({
            "op": 1,
            "d": {
                "protocol": "udp",
                "data": {
                    "address": self.udp.local_ip,
                    "port":    self.udp.local_port,
                    "mode":    "aead_aes256_gcm_rtpsize",
                },
                "address": self.udp.local_ip,
                "port":    self.udp.local_port,
                "mode":    "aead_aes256_gcm_rtpsize",
                "codecs": [
                    {"name": "opus", "type": "audio", "priority": 1000,
                     "payload_type": 120, "rtx_payload_type": None,
                     "encode": True, "decode": True},
                ],
                "rtc_connection_id": str(uuid.uuid4()),
                "experiments": [
                    "fixed_keyframe_interval", "keyframe_on_join",
                    "network_aware_socket", "clear_cuda_cache",
                ],
            }
        })

    def _on_dave_prepare_epoch(self, d: dict):
        epoch       = d.get("epoch", 0)
        epoch_proto = d.get("protocol_version", 1)
        _vlog(f"DAVE_PREPARE_EPOCH epoch={epoch} proto={epoch_proto}")
        self.pending_epoch       = epoch
        self.pending_epoch_proto = epoch_proto
        if epoch == 1 and self.udp and self.udp.dave_session:
            kp = self.udp.dave_session.reset_and_get_key_package(epoch_proto)
            if kp:
                _vlog(f"Sending key package len={len(kp)}")
                self._send_binary(26, kp)

    def _handle_binary(self, payload: bytes):
        if len(payload) < 3:
            return
        seq = struct.unpack(">H", payload[0:2])[0]
        self._seq = seq
        opcode = payload[2]
        data   = payload[3:]
        _vlog(f"VoiceGW <- binary op {opcode} len={len(data)}")

        if not self.udp or not self.udp.dave_session:
            if opcode == 25:
                self.pending_external_sender = data
                _vlog(f"Cached external sender before DAVE init len={len(data)}")
            else:
                _vlog(f"Binary op {opcode} ignored before DAVE init")
            return

        ds = self.udp.dave_session

        if opcode == 25:
            _vlog(f"MLS: external_sender len={len(data)}")
            ds.set_external_sender(data)
            kp = ds.get_key_package()
            if kp:
                _vlog(f"MLS: sending key_package len={len(kp)}")
                self._send_binary(26, kp)

        elif opcode == 27:
            _vlog(f"MLS: proposals len={len(data)}")
            cw = ds.process_proposals(data)
            if cw:
                _vlog(f"MLS: sending commit len={len(cw)}")
                self._send_binary(28, cw)

        elif opcode == 29:
            if len(data) < 2:
                return
            tid = struct.unpack(">H", data[0:2])[0]
            ok  = ds.process_commit(data[2:])
            _vlog(f"MLS: commit tid={tid} ok={ok}")
            self._send_json({"op": 23 if ok else 31, "d": {"transition_id": tid}})

        elif opcode == 30:
            if len(data) < 2:
                return
            tid = struct.unpack(">H", data[0:2])[0]
            ok  = ds.process_welcome(data[2:])
            _vlog(f"MLS: welcome tid={tid} ok={ok}")
            self._send_json({"op": 23 if ok else 31, "d": {"transition_id": tid}})

    def _start_heartbeat(self):
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop, daemon=True
        )
        self._heartbeat_thread.start()

    def _heartbeat_loop(self):
        while not self._stop.is_set():
            time.sleep(self._heartbeat_interval)
            if self._stop.is_set():
                break
            self._send_json({
                "op": 3,
                "d": {"t": int(time.time() * 1000), "seq_ack": self._seq}
            })
