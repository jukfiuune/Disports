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
VoiceAudio.getAudioPipeCapsule() is called ONCE from the main thread during
setup and returns a PyCapsule wrapping a raw AudioPipe*.  Python then calls
two plain C functions — pipe_write() and pipe_read() — that operate directly
on the ring buffer memory with no Qt involvement whatsoever.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import threading
from typing import Optional

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
_log_buffer: list[str] = []
_log_lock = threading.Lock()


def _vlog(msg: str) -> None:
    print(f"[Voice] {msg}", flush=True)
    with _log_lock:
        _log_buffer.append(msg)
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
        return bytes(self._pcm_buf[: n * self._channels])

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
# AudioPipe — direct ring-buffer access from Python
#
# The C++ layout (from voiceaudio.h) is:
#   struct AudioPipe {
#       RingBuffer *play;   // offset 0
#       RingBuffer *cap;    // offset 8
#       bool        capStop; // offset 16
#   };
#
# We never touch the RingBuffer internals from Python — we call back into
# the compiled plugin via ctypes to use its write()/readExact() methods.
# The plugin exports two plain C helper functions for exactly this purpose.
# ---------------------------------------------------------------------------

_pipe_capsule = None   # PyCapsule set by set_audio_pipe_capsule()
_pipe_lib: Optional[ctypes.CDLL] = None   # handle to libdisportsvoice.so


def _load_pipe_lib() -> Optional[ctypes.CDLL]:
    global _pipe_lib
    if _pipe_lib is not None:
        return _pipe_lib
    for name in ("libdisportsvoice.so", "libdisportsvoice.so.1"):
        try:
            lib = ctypes.CDLL(name)
            # int  disports_pipe_write(void *pipe, const char *data, int len)
            lib.disports_pipe_write.restype  = ctypes.c_int
            lib.disports_pipe_write.argtypes = [ctypes.c_void_p,
                                                 ctypes.c_char_p,
                                                 ctypes.c_int]
            # int  disports_pipe_read(void *pipe, char *out, int len)
            # Blocks until len bytes available or capStop set.
            # Returns 0 on shutdown, len on success.
            lib.disports_pipe_read.restype  = ctypes.c_int
            lib.disports_pipe_read.argtypes = [ctypes.c_void_p,
                                                ctypes.c_char_p,
                                                ctypes.c_int]
            # int  disports_pipe_cap_ready(void *pipe)  → 0 or 1
            lib.disports_pipe_cap_ready.restype  = ctypes.c_int
            lib.disports_pipe_cap_ready.argtypes = [ctypes.c_void_p]
            _pipe_lib = lib
            _vlog(f"libdisportsvoice loaded: {name}")
            return lib
        except OSError as e:
            _vlog(f"libdisportsvoice not at {name}: {e}")
    _vlog("ERROR: libdisportsvoice not found — audio data path unavailable")
    return None


def set_audio_pipe_capsule(ptr_int) -> None:
    """
    Called from QML/PythonBridge once, on the main thread, immediately after
    VoiceAudio is instantiated. `ptr_int` is the raw memory address (int) 
    of the AudioPipe struct in C++.
    """
    global _pipe_capsule
    _pipe_capsule = ptr_int
    _vlog(f"AudioPipe pointer registered: 0x{ptr_int:x}")
    _load_pipe_lib()


def _pipe_ptr() -> Optional[int]:
    if _pipe_capsule is None:
        _vlog("WARNING: AudioPipe not yet registered")
    return _pipe_capsule


FRAME_BYTES = OPUS_FRAME_SIZE * OpusEncoder.CAPTURE_CHANNELS * 2  # 1920 bytes


# ---------------------------------------------------------------------------
# QtPlayback — pushes decoded stereo S16LE PCM into the playback ring
# ---------------------------------------------------------------------------
class QtPlayback:
    def write(self, pcm: bytes) -> None:
        ptr = _pipe_ptr()
        lib = _pipe_lib
        if ptr is None or lib is None:
            return
        try:
            lib.disports_pipe_write(ptr, pcm, len(pcm))
        except Exception as e:
            _vlog(f"pipe_write error: {e}")

    def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# QtCapture — pulls mono S16LE frames from the capture ring
#             disports_pipe_read() blocks in C++ with NO Qt involvement
# ---------------------------------------------------------------------------
class QtCapture:
    def __init__(self):
        self._buf = ctypes.create_string_buffer(FRAME_BYTES)

    @property
    def available(self) -> bool:
        ptr = _pipe_ptr()
        lib = _pipe_lib
        if ptr is None or lib is None:
            return False
        try:
            return bool(lib.disports_pipe_cap_ready(ptr))
        except Exception:
            return False

    def read_frame(self) -> Optional[bytes]:
        """
        Blocks in C++ until a 20ms frame is ready or stopAudio() is called.
        Never touches the Qt main thread — runs entirely in the Python daemon
        thread that calls it.
        """
        ptr = _pipe_ptr()
        lib = _pipe_lib
        if ptr is None or lib is None:
            import time; time.sleep(0.02)
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
