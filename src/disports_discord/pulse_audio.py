from __future__ import annotations

import ctypes
import ctypes.util
import sys
import threading
import subprocess
from typing import Optional

_log_buffer = []
_log_lock = threading.Lock()

def _vlog(msg: str):
    """Emit a voice log line to QML via polling buffer and stdout."""
    print(f"[Voice] {msg}", flush=True)
    with _log_lock:
        _log_buffer.append(msg)
        if len(_log_buffer) > 100:
            _log_buffer.pop(0)

def get_voice_logs():
    """Called by QML to fetch new logs."""
    with _log_lock:
        msgs = list(_log_buffer)
        _log_buffer.clear()
        return msgs

# PulseAudio simple API constants
PA_SAMPLE_S16LE   = 3
PA_SAMPLE_FLOAT32LE = 5
PA_STREAM_PLAYBACK = 1
PA_STREAM_RECORD   = 2

class _pa_sample_spec(ctypes.Structure):
    _fields_ = [
        ("format",   ctypes.c_int),
        ("rate",     ctypes.c_uint32),
        ("channels", ctypes.c_uint8),
    ]

_libpulse_simple = None

def _load_pulse():
    global _libpulse_simple
    if _libpulse_simple is not None:
        return _libpulse_simple
    for name in ("libpulse-simple.so.0", "libpulse-simple.so"):
        try:
            lib = ctypes.CDLL(name)
            lib.pa_simple_new.restype  = ctypes.c_void_p
            lib.pa_simple_new.argtypes = [
                ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int,
                ctypes.c_char_p, ctypes.c_char_p,
                ctypes.POINTER(_pa_sample_spec),
                ctypes.c_void_p, ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_int),
            ]
            lib.pa_simple_write.restype  = ctypes.c_int
            lib.pa_simple_write.argtypes = [
                ctypes.c_void_p, ctypes.c_void_p,
                ctypes.c_size_t, ctypes.POINTER(ctypes.c_int),
            ]
            lib.pa_simple_read.restype  = ctypes.c_int
            lib.pa_simple_read.argtypes = [
                ctypes.c_void_p, ctypes.c_void_p,
                ctypes.c_size_t, ctypes.POINTER(ctypes.c_int),
            ]
            lib.pa_simple_drain.restype  = ctypes.c_int
            lib.pa_simple_drain.argtypes = [
                ctypes.c_void_p, ctypes.POINTER(ctypes.c_int),
            ]
            lib.pa_simple_free.restype  = None
            lib.pa_simple_free.argtypes = [ctypes.c_void_p]
            _libpulse_simple = lib
            _vlog(f"libpulse-simple loaded: {name}")
            return lib
        except OSError as e:
            _vlog(f"libpulse-simple not found at {name}: {e}")
            continue
    _vlog("ERROR: libpulse-simple not found")
    return None

# Opus API constants
OPUS_OK             = 0
OPUS_APPLICATION_VOIP = 2048
OPUS_FRAME_SIZE     = 960

_libopus = None

def _load_opus():
    global _libopus
    if _libopus is not None:
        return _libopus
    for name in ("libopus.so.0", "libopus.so"):
        try:
            lib = ctypes.CDLL(name)
            lib.opus_decoder_create.restype  = ctypes.c_void_p
            lib.opus_decoder_create.argtypes = [
                ctypes.c_int32, ctypes.c_int,
                ctypes.POINTER(ctypes.c_int),
            ]
            lib.opus_decode.restype  = ctypes.c_int
            lib.opus_decode.argtypes = [
                ctypes.c_void_p,
                ctypes.c_char_p, ctypes.c_int32,
                ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
            ]
            lib.opus_decoder_destroy.restype  = None
            lib.opus_decoder_destroy.argtypes = [ctypes.c_void_p]

            lib.opus_encoder_create.restype  = ctypes.c_void_p
            lib.opus_encoder_create.argtypes = [
                ctypes.c_int32, ctypes.c_int, ctypes.c_int,
                ctypes.POINTER(ctypes.c_int),
            ]
            lib.opus_encode.restype  = ctypes.c_int32
            lib.opus_encode.argtypes = [
                ctypes.c_void_p,
                ctypes.c_void_p, ctypes.c_int,
                ctypes.c_char_p, ctypes.c_int32,
            ]
            lib.opus_encoder_destroy.restype  = None
            lib.opus_encoder_destroy.argtypes = [ctypes.c_void_p]
            _libopus = lib
            _vlog(f"libopus loaded: {name}")
            return lib
        except OSError as e:
            _vlog(f"libopus not found at {name}: {e}")
            continue
    _vlog("ERROR: libopus not found")
    return None

class OpusDecoder:
    def __init__(self, channels: int = 2):
        self._lib = _load_opus()
        self._dec = None
        self._channels = channels
        self._pcm_buf  = (ctypes.c_int16 * (OPUS_FRAME_SIZE * channels * 6))()
        if self._lib:
            err = ctypes.c_int(0)
            self._dec = self._lib.opus_decoder_create(48000, channels, ctypes.byref(err))
            if not self._dec or err.value != OPUS_OK:
                _vlog(f"OpusDecoder create failed err={err.value}")
                self._dec = None
        else:
            _vlog("OpusDecoder: libopus unavailable")

    def decode(self, opus_data: bytes) -> Optional[bytes]:
        if not self._dec or not self._lib:
            return None
        n = self._lib.opus_decode(
            self._dec,
            opus_data, len(opus_data),
            self._pcm_buf, OPUS_FRAME_SIZE * 6, 0,
        )
        if n <= 0:
            return None
        samples = n * self._channels
        return bytes(self._pcm_buf[:samples])

    def close(self):
        if self._dec and self._lib:
            self._lib.opus_decoder_destroy(self._dec)
            self._dec = None

class OpusEncoder:
    CAPTURE_CHANNELS = 1
    ENCODE_BITRATE   = 64_000

    def __init__(self):
        self._lib = _load_opus()
        self._enc = None
        self._pcm_buf = (ctypes.c_int16 * (OPUS_FRAME_SIZE * self.CAPTURE_CHANNELS))()
        self._out_buf = ctypes.create_string_buffer(4000)
        if self._lib:
            err = ctypes.c_int(0)
            self._enc = self._lib.opus_encoder_create(
                48000, self.CAPTURE_CHANNELS,
                OPUS_APPLICATION_VOIP, ctypes.byref(err),
            )
            if not self._enc or err.value != OPUS_OK:
                _vlog(f"OpusEncoder create failed err={err.value}")
                self._enc = None
            else:
                _vlog("OpusEncoder ready")
        else:
            _vlog("OpusEncoder: libopus unavailable")

    def encode(self, pcm_bytes: bytes) -> Optional[bytes]:
        if not self._enc or not self._lib:
            return None
        n_samples = len(pcm_bytes) // 2 // self.CAPTURE_CHANNELS
        ctypes.memmove(self._pcm_buf, pcm_bytes, len(pcm_bytes))
        n = self._lib.opus_encode(
            self._enc,
            self._pcm_buf, n_samples,
            self._out_buf, len(self._out_buf),
        )
        if n <= 0:
            return None
        return bytes(self._out_buf[:n])

    def close(self):
        if self._enc and self._lib:
            self._lib.opus_encoder_destroy(self._enc)
            self._enc = None

class PulsePlayback:
    def __init__(self):
        self._lib    = _load_pulse()
        self._stream = None
        self._lock   = threading.Lock()
        if self._lib:
            spec = _pa_sample_spec(PA_SAMPLE_S16LE, 48000, 2)
            err  = ctypes.c_int(0)
            self._stream = self._lib.pa_simple_new(
                None, b"Disports", PA_STREAM_PLAYBACK,
                None, b"voice-rx",
                ctypes.byref(spec), None, None, ctypes.byref(err),
            )
            if not self._stream:
                _vlog(f"PulsePlayback open FAILED err={err.value}")
            else:
                _vlog("PulsePlayback stream opened OK (48kHz stereo S16LE)")

    @property
    def available(self) -> bool:
        return self._stream is not None

    def write(self, pcm: bytes):
        if not self._stream or not self._lib:
            return
        buf = (ctypes.c_uint8 * len(pcm)).from_buffer_copy(pcm)
        err = ctypes.c_int(0)
        with self._lock:
            self._lib.pa_simple_write(self._stream, buf, len(pcm), ctypes.byref(err))

    def close(self):
        if self._stream and self._lib:
            err = ctypes.c_int(0)
            self._lib.pa_simple_drain(self._stream, ctypes.byref(err))
            self._lib.pa_simple_free(self._stream)
            self._stream = None

class PulseCapture:
    CHANNELS    = 1
    FRAME_BYTES = OPUS_FRAME_SIZE * CHANNELS * 2

    def __init__(self):
        self._lib    = _load_pulse()
        self._stream = None
        if self._lib:
            spec = _pa_sample_spec(PA_SAMPLE_S16LE, 48000, self.CHANNELS)
            err  = ctypes.c_int(0)
            self._stream = self._lib.pa_simple_new(
                None, b"Disports", PA_STREAM_RECORD,
                None, b"voice-tx",
                ctypes.byref(spec), None, None, ctypes.byref(err),
            )
            if not self._stream:
                _vlog(f"PulseCapture open FAILED err={err.value}")
            else:
                _vlog("PulseCapture stream opened OK (48kHz mono S16LE)")

    @property
    def available(self) -> bool:
        return self._stream is not None

    def read_frame(self) -> Optional[bytes]:
        if not self._stream or not self._lib:
            return None
        buf = ctypes.create_string_buffer(self.FRAME_BYTES)
        err = ctypes.c_int(0)
        ret = self._lib.pa_simple_read(self._stream, buf, self.FRAME_BYTES, ctypes.byref(err))
        if ret < 0:
            return None
        return bytes(buf)

    def close(self):
        if self._stream and self._lib:
            self._lib.pa_simple_free(self._stream)
            self._stream = None

def set_speaker_route(enabled: bool):
    """Switch PulseAudio output port: True=speaker, False=earpiece."""
    mode = "speaker" if enabled else "earpiece"
    _vlog(f"Routing audio \u2192 {mode}")
    try:
        if enabled:
            r = subprocess.run(
                ["pactl", "set-sink-port", "@DEFAULT_SINK@", "output-speaker"],
                check=False, timeout=2, capture_output=True,
            )
            _vlog(f"pactl speaker rc={r.returncode}")
        else:
            for port in ("output-earpiece", "output-handset", "earpiece", "handset"):
                r = subprocess.run(
                    ["pactl", "set-sink-port", "@DEFAULT_SINK@", port],
                    check=False, timeout=2, capture_output=True,
                )
                if r.returncode == 0:
                    _vlog(f"pactl {port} rc=0")
                    break
    except Exception as e:
        _vlog(f"route switch FAILED: {e}")

