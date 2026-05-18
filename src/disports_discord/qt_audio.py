"""
qt_audio.py — Native audio engine for Disports on Ubuntu Touch.

THREADING MODEL
---------------
VoiceAudio (C++ QObject) lives on the Qt main thread.  Any Q_INVOKABLE call
from a Python background thread is marshalled through pyotherside as a queued
Qt invocation — it executes on the main thread and the Python thread blocks
waiting for the result.  For 50-byte control calls this is fine.  For a call
that blocks *inside* C++ (like pullCaptureFrame waiting on a mutex), the main
thread is frozen for the full wait duration, causing the UI freeze.

Fix: the audio data path never calls any QObject method at all.
Python resolves the raw AudioPipe* from the C++ plugin and then calls two
plain C functions — pipe_write() and pipe_read() — that operate directly on
the ring buffer memory with no Qt involvement whatsoever.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import os
import threading
from typing import Optional

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
_log_buffer: list[str] = []
_log_lock = threading.Lock()


def _vlog(msg: str) -> None:
    safe_msg = str(msg).encode("ascii", errors="replace").decode("ascii")
    print(f"[Voice] {safe_msg}", flush=True)
    with _log_lock:
        _log_buffer.append(safe_msg)
        if len(_log_buffer) > 100:
            _log_buffer.pop(0)


def get_voice_logs() -> list[str]:
    with _log_lock:
        msgs = list(_log_buffer)
        _log_buffer.clear()
        return msgs


# ---------------------------------------------------------------------------
# Opus
# ---------------------------------------------------------------------------
OPUS_OK               = 0
OPUS_APPLICATION_VOIP = 2048
OPUS_FRAME_SIZE       = 960   # 20 ms at 48 kHz

_libopus: Optional[ctypes.CDLL] = None


def _load_opus() -> Optional[ctypes.CDLL]:
    global _libopus
    if _libopus is not None:
        return _libopus
    for name in ("libopus.so.0", "libopus.so"):
        try:
            lib = ctypes.CDLL(name)
            lib.opus_decoder_create.restype  = ctypes.c_void_p
            lib.opus_decoder_create.argtypes = [ctypes.c_int32, ctypes.c_int,
                                                 ctypes.POINTER(ctypes.c_int)]
            lib.opus_decode.restype  = ctypes.c_int
            lib.opus_decode.argtypes = [ctypes.c_void_p, ctypes.c_char_p,
                                         ctypes.c_int32, ctypes.c_void_p,
                                         ctypes.c_int, ctypes.c_int]
            lib.opus_decoder_destroy.restype  = None
            lib.opus_decoder_destroy.argtypes = [ctypes.c_void_p]
            lib.opus_encoder_create.restype  = ctypes.c_void_p
            lib.opus_encoder_create.argtypes = [ctypes.c_int32, ctypes.c_int,
                                                 ctypes.c_int, ctypes.POINTER(ctypes.c_int)]
            lib.opus_encode.restype  = ctypes.c_int32
            lib.opus_encode.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int,
                                         ctypes.c_char_p, ctypes.c_int32]
            lib.opus_encoder_destroy.restype  = None
            lib.opus_encoder_destroy.argtypes = [ctypes.c_void_p]
            _libopus = lib
            _vlog(f"libopus loaded: {name}")
            return lib
        except OSError as e:
            _vlog(f"libopus not at {name}: {e}")
    _vlog("ERROR: libopus not found")
    return None


class OpusDecoder:
    def __init__(self, channels: int = 2):
        self._lib = _load_opus()
        self._dec = None
        self._channels = channels
        self._pcm_buf = (ctypes.c_int16 * (OPUS_FRAME_SIZE * channels * 6))()
        if self._lib:
            err = ctypes.c_int(0)
            self._dec = self._lib.opus_decoder_create(48000, channels, ctypes.byref(err))
            if not self._dec or err.value != OPUS_OK:
                _vlog(f"OpusDecoder create failed err={err.value}")
                self._dec = None

    def decode(self, data: bytes) -> Optional[bytes]:
        if not self._dec:
            return None
        n = self._lib.opus_decode(self._dec, data, len(data),
                                   self._pcm_buf, OPUS_FRAME_SIZE * 6, 0)
        if n <= 0:
            return None
        return ctypes.string_at(
            ctypes.byref(self._pcm_buf),
            n * self._channels * ctypes.sizeof(ctypes.c_int16),
        )

    def close(self):
        if self._dec and self._lib:
            self._lib.opus_decoder_destroy(self._dec)
            self._dec = None


class OpusEncoder:
    CAPTURE_CHANNELS = 1

    def __init__(self):
        self._lib = _load_opus()
        self._enc = None
        self._pcm_buf = (ctypes.c_int16 * (OPUS_FRAME_SIZE * self.CAPTURE_CHANNELS))()
        self._out_buf = ctypes.create_string_buffer(4000)
        if self._lib:
            err = ctypes.c_int(0)
            self._enc = self._lib.opus_encoder_create(
                48000, self.CAPTURE_CHANNELS, OPUS_APPLICATION_VOIP, ctypes.byref(err))
            if not self._enc or err.value != OPUS_OK:
                _vlog(f"OpusEncoder create failed err={err.value}")
                self._enc = None
            else:
                _vlog("OpusEncoder ready")

    def encode(self, pcm: bytes) -> Optional[bytes]:
        if not self._enc:
            return None
        n_samples = len(pcm) // 2 // self.CAPTURE_CHANNELS
        ctypes.memmove(self._pcm_buf, pcm, len(pcm))
        n = self._lib.opus_encode(self._enc, self._pcm_buf, n_samples,
                                   self._out_buf, len(self._out_buf))
        if n <= 0:
            return None
        return bytes(self._out_buf[:n])

    def close(self):
        if self._enc and self._lib:
            self._lib.opus_encoder_destroy(self._enc)
            self._enc = None


# ---------------------------------------------------------------------------
# AudioPipe - direct ring-buffer access from Python
# ---------------------------------------------------------------------------

_pipe_lib: Optional[ctypes.CDLL] = None
_pipe_ptr: Optional[int] = None


def _load_pipe_lib() -> Optional[ctypes.CDLL]:
    global _pipe_lib, _pipe_ptr
    if _pipe_lib is not None:
        return _pipe_lib

    candidates = ["libdisportsvoice.so"]
    app_dir = os.environ.get("APP_DIR")
    if app_dir:
        for root, _dirs, files in os.walk(os.path.join(app_dir, "lib")):
            if "libdisportsvoice.so" in files:
                candidates.insert(0, os.path.join(root, "libdisportsvoice.so"))
                break

    for name in candidates:
        try:
            lib = ctypes.CDLL(name)
            lib.disports_voice_audio_pipe.restype = ctypes.c_void_p
            lib.disports_voice_audio_pipe.argtypes = []
            lib.disports_pipe_write.restype = ctypes.c_int
            lib.disports_pipe_write.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
            lib.disports_pipe_read.restype = ctypes.c_int
            lib.disports_pipe_read.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
            lib.disports_pipe_cap_ready.restype = ctypes.c_int
            lib.disports_pipe_cap_ready.argtypes = [ctypes.c_void_p]
            _pipe_lib = lib
            _pipe_ptr = lib.disports_voice_audio_pipe()
            _vlog(f"libdisportsvoice audio pipe loaded: {name}")
            return lib
        except OSError as e:
            _vlog(f"libdisportsvoice not at {name}: {e}")
        except AttributeError as e:
            _vlog(f"libdisportsvoice missing audio pipe symbol at {name}: {e}")
    return None


def _audio_pipe_ptr() -> Optional[int]:
    global _pipe_ptr
    lib = _load_pipe_lib()
    if not lib:
        return None
    _pipe_ptr = lib.disports_voice_audio_pipe()
    return _pipe_ptr or None


FRAME_BYTES = OPUS_FRAME_SIZE * OpusEncoder.CAPTURE_CHANNELS * 2


def put_capture_frame(_b64_frame: str) -> None:
    # Kept for older QML builds; current audio capture uses AudioPipe directly.
    return None

# ---------------------------------------------------------------------------
# QtPlayback — pushes decoded stereo S16LE PCM into the playback ring
# ---------------------------------------------------------------------------
class QtPlayback:
    def write(self, pcm: bytes) -> None:
        lib = _load_pipe_lib()
        ptr = _audio_pipe_ptr()
        if not lib or not ptr:
            return
        try:
            lib.disports_pipe_write(ptr, pcm, len(pcm))
        except Exception as e:
            _vlog(f"pipe_write error: {e}")

    def close(self) -> None:
        pass

# ---------------------------------------------------------------------------
# QtCapture — pulls mono S16LE frames from the capture queue
# ---------------------------------------------------------------------------
class QtCapture:
    def __init__(self):
        self._buf = ctypes.create_string_buffer(FRAME_BYTES)

    @property
    def available(self) -> bool:
        lib = _load_pipe_lib()
        ptr = _audio_pipe_ptr()
        if not lib or not ptr:
            return False
        try:
            return bool(lib.disports_pipe_cap_ready(ptr))
        except Exception:
            return False

    def read_frame(self) -> Optional[bytes]:
        lib = _load_pipe_lib()
        ptr = _audio_pipe_ptr()
        if not lib or not ptr:
            import time
            time.sleep(0.02)
            return None
        try:
            n = lib.disports_pipe_read(ptr, self._buf, FRAME_BYTES)
            if n == FRAME_BYTES:
                return bytes(self._buf.raw)
            return None
        except Exception as e:
            _vlog(f"pipe_read error: {e}")
            return None

    def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Control helpers — these DO go via pyotherside (small control messages only)
# ---------------------------------------------------------------------------

def start_audio() -> None:
    try:
        import pyotherside
        pyotherside.send("voice_start", {})
        _vlog("Sent voice_start signal to QML")
    except Exception as e:
        _vlog(f"Failed to send voice_start: {e}")


def stop_audio() -> None:
    try:
        import pyotherside
        pyotherside.send("voice_stop", {})
        _vlog("Sent voice_stop signal to QML")
    except Exception as e:
        _vlog(f"Failed to send voice_stop: {e}")


def set_speaker_route(enabled: bool) -> None:
    try:
        import pyotherside
        pyotherside.send("voice_speaker", {"enabled": enabled})
    except Exception as e:
        _vlog(f"Failed to send voice_speaker: {e}")


def set_muted(muted: bool) -> None:
    try:
        import pyotherside
        pyotherside.send("voice_mute", {"enabled": muted})
    except Exception as e:
        _vlog(f"Failed to send voice_mute: {e}")
