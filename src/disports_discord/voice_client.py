from __future__ import annotations

import json
import socket
import ssl
import struct
import threading
import time
import uuid
import zlib
from typing import Callable, Optional

import websocket
from websocket import ABNF, WebSocketException
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst, GObject

Gst.init(None)

from .dave_interop import DaveSession 

class VoiceUdpClient:
    def __init__(self, ssrc: int):
        self.ssrc = ssrc
        self.secret_key: Optional[bytes] = None
        self.dave_session = None
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.settimeout(0.5)
        self.server_ip = None
        self.server_port = None
        self._stop = threading.Event()
        self._recv_thread = None
        
        self._send_sequence = 0
        self._send_timestamp = 0
        self._send_nonce = 0
        
        self.play_pipeline = None
        self.mixer = None
        self.capture_pipeline = None
        self.mic_sink = None
        self.appsrcs = {}
        
        self._init_gstreamer()

    def _init_gstreamer(self):
        # Playback Pipeline
        self.play_pipeline = Gst.Pipeline.new("play-pipeline")
        self.mixer = Gst.ElementFactory.make("audiomixer", "mixer")
        sink = Gst.ElementFactory.make("pulsesink", "sink")
        
        if self.mixer and sink:
            self.play_pipeline.add(self.mixer)
            self.play_pipeline.add(sink)
            self.mixer.link(sink)
            self.play_pipeline.set_state(Gst.State.PLAYING)

        # Capture Pipeline
        self.capture_pipeline = Gst.parse_launch(
            "pulsesrc ! audioconvert ! audioresample ! audio/x-raw,rate=48000,channels=1 ! "
            "opusenc bitrate=64000 frame-size=20 ! appsink name=mic_sink emit-signals=true"
        )
        if self.capture_pipeline:
            self.mic_sink = self.capture_pipeline.get_by_name("mic_sink")
            self.mic_sink.connect("new-sample", self._on_mic_data)
            self.capture_pipeline.set_state(Gst.State.PLAYING)

    def _get_appsrc_for_ssrc(self, ssrc: int):
        if ssrc in self.appsrcs:
            return self.appsrcs[ssrc]
            
        src = Gst.ElementFactory.make("appsrc", f"src_{ssrc}")
        parse = Gst.ElementFactory.make("opusparse", f"parse_{ssrc}")
        dec = Gst.ElementFactory.make("opusdec", f"dec_{ssrc}")
        conv = Gst.ElementFactory.make("audioconvert", f"conv_{ssrc}")
        res = Gst.ElementFactory.make("audioresample", f"res_{ssrc}")
        
        if not (src and parse and dec and conv and res and self.play_pipeline and self.mixer):
            return None
            
        src.set_property("format", Gst.Format.TIME)
        src.set_property("is-live", True)
        src.set_property("do-timestamp", True)
        caps = Gst.Caps.from_string("audio/x-opus,rate=48000,channels=2")
        src.set_property("caps", caps)
        
        self.play_pipeline.add(src)
        self.play_pipeline.add(parse)
        self.play_pipeline.add(dec)
        self.play_pipeline.add(conv)
        self.play_pipeline.add(res)
        
        src.link(parse)
        parse.link(dec)
        dec.link(conv)
        conv.link(res)
        res.link(self.mixer)
        
        src.sync_state_with_parent()
        parse.sync_state_with_parent()
        dec.sync_state_with_parent()
        conv.sync_state_with_parent()
        res.sync_state_with_parent()
        
        self.appsrcs[ssrc] = src
        return src

    def _on_mic_data(self, sink):
        sample = sink.emit("pull-sample")
        if not sample:
            return Gst.FlowReturn.OK
            
        if not self.secret_key or not self.dave_session:
            return Gst.FlowReturn.OK
            
        buf = sample.get_buffer()
        success, map_info = buf.map(Gst.MapFlags.READ)
        if success:
            try:
                opus_data = map_info.data
                dave_frame = self.dave_session.encrypt_audio_frame(self.ssrc, opus_data)
                if dave_frame:
                    packet = self._build_rtp_packet(dave_frame)
                    if packet and self.server_ip and self.server_port:
                        self._sock.send(packet)
            finally:
                buf.unmap(map_info)
                
        return Gst.FlowReturn.OK

    def _build_rtp_packet(self, payload: bytes) -> Optional[bytes]:
        hdr = bytearray(12)
        hdr[0] = 0x80
        hdr[1] = 0x78
        hdr[2:4] = struct.pack(">H", self._send_sequence)
        hdr[4:8] = struct.pack(">I", self._send_timestamp)
        hdr[8:12] = struct.pack(">I", self.ssrc)
        
        self._send_sequence = (self._send_sequence + 1) & 0xFFFF
        self._send_timestamp = (self._send_timestamp + 960) & 0xFFFFFFFF
        self._send_nonce = (self._send_nonce + 1) & 0xFFFFFFFF
        
        nonce = struct.pack(">I", self._send_nonce).rjust(12, b'\x00')
        
        try:
            aesgcm = AESGCM(self.secret_key)
            ciphertext = aesgcm.encrypt(nonce, payload, bytes(hdr))
        except Exception:
            return None
            
        packet = hdr + ciphertext + struct.pack(">I", self._send_nonce)
        return bytes(packet)

    def connect(self, ip: str, port: int) -> tuple[str, int]:
        self.server_ip = ip
        self.server_port = port
        self._sock.connect((ip, port))
        
        # IP Discovery
        packet = bytearray(74)
        packet[0:4] = struct.pack(">H", 1) + struct.pack(">H", 70)
        packet[4:8] = struct.pack(">I", self.ssrc)
        self._sock.send(packet)
        
        resp = self._sock.recv(74)
        local_ip = resp[8:72].decode('ascii').strip('\x00')
        local_port = struct.unpack(">H", resp[72:74])[0]
        return local_ip, local_port

    def set_speakerphone(self, enabled: bool):
        import subprocess
        port = "speaker" if enabled else "handset"
        # On Ubuntu Touch, standard ports are usually 'speaker' and 'handset' or 'earpiece'
        # We try both common variants for handset
        try:
            if enabled:
                subprocess.run(["pactl", "set-sink-port", "@DEFAULT_SINK@", "speaker"], check=False)
            else:
                res = subprocess.run(["pactl", "set-sink-port", "@DEFAULT_SINK@", "handset"], check=False)
                if res.returncode != 0:
                    subprocess.run(["pactl", "set-sink-port", "@DEFAULT_SINK@", "earpiece"], check=False)
        except Exception as e:
            print(f"Failed to set audio routing: {e}")

    def update_secret_key(self, key: bytes):
        self.secret_key = key
        
    def start_receive_loop(self):
        self._stop.clear()
        self._recv_thread = threading.Thread(target=self._receive_loop, daemon=True)
        self._recv_thread.start()

    def stop(self):
        self._stop.set()
        if self._sock:
            self._sock.close()
        if self.play_pipeline:
            self.play_pipeline.set_state(Gst.State.NULL)
        if self.capture_pipeline:
            self.capture_pipeline.set_state(Gst.State.NULL)

    def _receive_loop(self):
        while not self._stop.is_set():
            try:
                data = self._sock.recv(4096)
                if len(data) < 12:
                    continue
                # IP discovery response
                if data[0] == 0x00 and data[1] == 0x02:
                    continue
                    
                payload_type = data[1]
                if 200 <= payload_type <= 204:
                    continue # RTCP

                if not self.secret_key:
                    continue

                # Decrypt transport layer
                cc = data[0] & 0x0F
                has_ext = (data[0] & 0x10) != 0
                hdr_len = 12 + (cc * 4)
                if has_ext and len(data) > hdr_len + 4:
                    hdr_len += 4
                
                nonce_val = struct.unpack(">I", data[-4:])[0]
                nonce = struct.pack(">I", nonce_val).rjust(12, b'\x00')
                
                ciphertext = data[hdr_len:-4]
                aad = data[:hdr_len]
                
                try:
                    aesgcm = AESGCM(self.secret_key)
                    decrypted = aesgcm.decrypt(nonce, ciphertext, aad)
                except Exception:
                    continue
                
                # Silence packet
                if len(decrypted) == 3 and decrypted == b"\xf8\xff\xfe":
                    continue

                if not self.dave_session:
                    continue

                dave_payload = decrypted
                if has_ext and len(data) > hdr_len + 4:
                    ext_len = struct.unpack(">H", data[hdr_len + 2:hdr_len + 4])[0]
                    ext_body_bytes = ext_len * 4
                    if len(decrypted) > ext_body_bytes:
                        dave_payload = decrypted[ext_body_bytes:]

                opus_frame = self.dave_session.decrypt_audio_frame(self.ssrc, dave_payload)
                if not opus_frame:
                    continue

                src = self._get_appsrc_for_ssrc(ssrc)
                if src:
                    buf = Gst.Buffer.new_wrapped(opus_frame)
                    src.emit("push-buffer", buf)
                
            except socket.timeout:
                continue
            except Exception as e:
                print(f"UDP Error: {e}")

class VoiceGateway:
    def __init__(self, endpoint: str, token: str, session_id: str, user_id: str, channel_id: str):
        self.endpoint = endpoint
        self.token = token
        self.session_id = session_id
        self.user_id = user_id
        self.channel_id = channel_id
        
        self._ws = None
        self._stop = threading.Event()
        self._heartbeat_thread = None
        self._heartbeat_interval = 41.25
        self._seq = -1
        
        self.pending_ssrc_map = {}
        self.pending_external_sender = None
        self.pending_epoch = -1
        self._send_lock = threading.Lock()
        self.pending_epoch_proto = 1
        self.udp = None
        
    def start(self):
        self._stop.clear()
        threading.Thread(target=self._run, daemon=True).start()

    def stop(self):
        self._stop.set()
        if self._ws:
            self._ws.close()
        if self.udp:
            self.udp.stop()

    def _run(self):
        url = f"wss://{self.endpoint}/?v=9"
        self._ws = websocket.create_connection(url, sslopt={"cert_reqs": ssl.CERT_REQUIRED})
        
        identify = {
            "op": 0,
            "d": {
                "server_id": self.channel_id,
                "channel_id": self.channel_id,
                "user_id": self.user_id,
                "session_id": self.session_id,
                "token": self.token,
                "max_dave_protocol_version": 1,
                "video": True,
                "streams": [
                    {"type": "video", "rid": "100", "quality": 100},
                    {"type": "video", "rid": "50", "quality": 50}
                ]
            }
        }
        self._send_json(identify)
        
        while not self._stop.is_set():
            try:
                opcode, payload = self._ws.recv_data()
                if opcode == ABNF.OPCODE_TEXT:
                    self._handle_json(json.loads(payload))
                elif opcode == ABNF.OPCODE_BINARY:
                    self._handle_binary(payload)
            except Exception as e:
                print(f"Voice WS Error: {e}")
                break

    def _send_json(self, data: dict):
        try:
            with self._send_lock:
                if self._ws:
                    self._ws.send(json.dumps(data))
        except (websocket.WebSocketConnectionClosedException, BrokenPipeError):
            print("Voice WS: Tried to send on closed socket")
            self.stop()

    def _send_binary(self, opcode: int, payload: bytes):
        packet = bytearray([opcode]) + payload
        with self._send_lock:
            self._ws.send_binary(packet)

    def _handle_json(self, data: dict):
        op = data.get("op")
        seq = data.get("seq")
        if seq is not None:
            self._seq = seq
            
        d = data.get("d", {})
        
        if op == 2:  # Ready
            ip = d.get("ip")
            port = d.get("port")
            ssrc = d.get("ssrc")
            
            self.udp = VoiceUdpClient(ssrc)
            local_ip, local_port = self.udp.connect(ip, port)
            self.udp.start_receive_loop()
            
            # Send unknown op 16 payload just like C# impl
            self._send_json({"op": 16, "d": {}})
            
        elif op == 8:  # Hello
            self._heartbeat_interval = d.get("heartbeat_interval", 41250) / 1000.0
            self._start_heartbeat()
            
        elif op == 4:  # Session Description
            dave_version = d.get("dave_protocol_version", 1)
            secret_key = d.get("secret_key")
            if secret_key:
                self.udp.update_secret_key(bytes(secret_key))
            
            self.udp.dave_session = DaveSession()
            self.udp.dave_session.init(dave_version, self.channel_id, self.user_id)
            
            for ssrc, uid in self.pending_ssrc_map.items():
                self.udp.dave_session.register_ssrc(ssrc, uid)
                
            if self.pending_external_sender:
                self.udp.dave_session.set_external_sender(self.pending_external_sender)
                self.pending_external_sender = None
                
            if self.pending_epoch == 1:
                kp = self.udp.dave_session.reset_and_get_key_package(self.pending_epoch_proto)
                if kp: self._send_binary(26, kp)
            
            # Send speaking payload
            if self.udp:
                self._send_json({
                    "op": 5,
                    "d": {
                        "speaking": 2,
                        "delay": 0,
                        "ssrc": self.udp.ssrc
                    }
                })
            
        elif op == 5:
            spk_uid = d.get("user_id")
            spk_ssrc = d.get("ssrc")
            if spk_uid and spk_ssrc:
                self.pending_ssrc_map[spk_ssrc] = str(spk_uid)
                if self.udp and self.udp.dave_session:
                    self.udp.dave_session.register_ssrc(spk_ssrc, str(spk_uid))
                    
        elif op == 12:
            op12_uid = d.get("user_id")
            op12_ssrc = d.get("ssrc")
            if op12_uid and op12_ssrc and self.udp and self.udp.dave_session:
                self.udp.dave_session.register_ssrc(op12_ssrc, str(op12_uid))
                
        elif op == 24:
            epoch = d.get("epoch", 0)
            epoch_proto = d.get("protocol_version", 1)
            self.pending_epoch = epoch
            self.pending_epoch_proto = epoch_proto
            if epoch == 1 and self.udp and self.udp.dave_session:
                kp = self.udp.dave_session.reset_and_get_key_package(epoch_proto)
                if kp: self._send_binary(26, kp)
            
        elif op == 16:
            rtc_connection_id = str(uuid.uuid4())
            self._send_json({
                "op": 1,
                "d": {
                    "protocol": "udp",
                    "data": {
                        "address": self.udp.server_ip,
                        "port": self.udp.server_port,
                        "mode": "aead_aes256_gcm_rtpsize"
                    },
                    "address": self.udp.server_ip,
                    "port": self.udp.server_port,
                    "mode": "aead_aes256_gcm_rtpsize",
                    "codecs": [
                        {"name": "opus", "type": "audio", "priority": 1000, "payload_type": 120, "encode": False, "decode": False}
                    ],
                    "rtc_connection_id": rtc_connection_id,
                    "experiments": ["fixed_keyframe_interval", "keyframe_on_join", "network_aware_socket", "clear_cuda_cache"]
                }
            }) if (self.udp and self.udp.server_ip) else None

    def _handle_binary(self, payload: bytes):
        if len(payload) < 3: return
        seq = struct.unpack(">H", payload[0:2])[0]
        self._seq = seq
        opcode = payload[2]
        data = payload[3:]
        
        if not self.udp or not self.udp.dave_session:
            if opcode == 25:
                self.pending_external_sender = data
            return
            
        ds = self.udp.dave_session
        
        if opcode == 25:
            ds.set_external_sender(data)
            kp = ds.get_key_package()
            if kp: self._send_binary(26, kp)
            
        elif opcode == 27:
            cw = ds.process_proposals(data)
            if cw: self._send_binary(28, cw)
            
        elif opcode == 29:
            if len(data) < 2: return
            tid = struct.unpack(">H", data[0:2])[0]
            if ds.process_commit(data[2:]):
                self._send_json({"op": 23, "d": {"transition_id": tid}})
            else:
                self._send_json({"op": 31, "d": {"transition_id": tid}})
                
        elif opcode == 30:
            if len(data) < 2: return
            tid = struct.unpack(">H", data[0:2])[0]
            if ds.process_welcome(data[2:]):
                self._send_json({"op": 23, "d": {"transition_id": tid}})
            else:
                self._send_json({"op": 31, "d": {"transition_id": tid}})

    def _start_heartbeat(self):
        self._heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self._heartbeat_thread.start()

    def _heartbeat_loop(self):
        while not self._stop.is_set():
            time.sleep(self._heartbeat_interval)
            if self._stop.is_set():
                break
            self._send_json({"op": 3, "d": {"t": int(time.time() * 1000), "seq_ack": self._seq}})
