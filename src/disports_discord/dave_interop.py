from __future__ import annotations

import ctypes
import os
from ctypes import c_void_p, c_uint16, c_uint32, c_uint64, c_size_t, c_bool, POINTER, CFUNCTYPE, c_int, c_uint8
from typing import Optional

def _dlog(message: str) -> None:
    try:
        from .pulse_audio import _vlog
        _vlog(f"DAVE: {message}")
    except Exception:
        print(f"[DAVE] {message}", flush=True)

class DAVEMediaType:
    Audio = 0
    Video = 1

_lib = None
_load_errors: list[str] = []
_loaded_path = ""

# Try to find libdisportsvoice.so instead of libdave.so
_lib_names = ["libdisportsvoice.so"]
_search_paths = [
    "", # Global symbol table / already loaded
]
if "APP_DIR" in os.environ:
    _search_paths.append(os.path.join(os.environ["APP_DIR"], "lib"))

# Try to load the C-API. It may already be loaded into the current process by Qt.
try:
    _lib = ctypes.CDLL(None)
    if hasattr(_lib, "disports_dave_create"):
        _dlog("Successfully found disports_dave symbols in current process")
        _loaded_path = "current_process"
    else:
        _lib = None
except Exception:
    pass

if not _lib:
    # Try finding it in the filesystem
    for root, dirs, files in os.walk(os.path.join(os.environ.get("APP_DIR", "."), "lib")):
        for file in files:
            if file == "libdisportsvoice.so":
                path = os.path.join(root, file)
                try:
                    _lib = ctypes.CDLL(path)
                    if hasattr(_lib, "disports_dave_create"):
                        _dlog(f"Successfully loaded disports_dave from {path}")
                        _loaded_path = path
                        break
                    else:
                        _lib = None
                except Exception as e:
                    _load_errors.append(f"{path}: {e}")
        if _lib:
            break

if not _lib:
    _dlog("Warning: Failed to load disports_dave from libdisportsvoice.so")

def libdave_status() -> dict[str, object]:
    return {
        "available": _lib is not None,
        "path": _loaded_path,
        "errors": list(_load_errors),
    }

SendBinaryCB = CFUNCTYPE(None, c_int, POINTER(c_uint8), c_size_t, c_void_p)
SendJsonCB = CFUNCTYPE(None, c_int, c_int, c_bool, c_void_p)

def _byte_buffer(payload: bytes):
    return (c_uint8 * len(payload)).from_buffer_copy(payload)

if _lib:
    _lib.disports_dave_create.argtypes = [c_uint64, c_uint64]
    _lib.disports_dave_create.restype = c_void_p
    _lib.disports_dave_destroy.argtypes = [c_void_p]
    _lib.disports_dave_destroy.restype = None

    _lib.disports_dave_init.argtypes = [c_void_p, c_uint16]
    _lib.disports_dave_init.restype = None
    _lib.disports_dave_reset.argtypes = [c_void_p]
    _lib.disports_dave_reset.restype = None
    _lib.disports_dave_set_local_ssrc.argtypes = [c_void_p, c_uint32]
    _lib.disports_dave_set_local_ssrc.restype = None

    _lib.disports_dave_update_roster.argtypes = [c_void_p, POINTER(c_uint32), POINTER(c_uint64), c_int]
    _lib.disports_dave_update_roster.restype = None
    _lib.disports_dave_add_connected_user.argtypes = [c_void_p, c_uint64]
    _lib.disports_dave_add_connected_user.restype = None

    _lib.disports_dave_set_callbacks.argtypes = [c_void_p, SendBinaryCB, SendJsonCB, c_void_p]
    _lib.disports_dave_set_callbacks.restype = None

    _lib.disports_dave_process_welcome.argtypes = [c_void_p, c_int, POINTER(c_uint8), c_size_t]
    _lib.disports_dave_process_welcome.restype = None
    _lib.disports_dave_process_commit.argtypes = [c_void_p, c_int, POINTER(c_uint8), c_size_t]
    _lib.disports_dave_process_commit.restype = None
    _lib.disports_dave_process_proposals.argtypes = [c_void_p, POINTER(c_uint8), c_size_t]
    _lib.disports_dave_process_proposals.restype = None
    _lib.disports_dave_set_external_sender.argtypes = [c_void_p, POINTER(c_uint8), c_size_t]
    _lib.disports_dave_set_external_sender.restype = None

    _lib.disports_dave_execute_transition.argtypes = [c_void_p, c_int]
    _lib.disports_dave_execute_transition.restype = None
    _lib.disports_dave_prepare_epoch.argtypes = [c_void_p, c_int]
    _lib.disports_dave_prepare_epoch.restype = None
    _lib.disports_dave_prepare_transition.argtypes = [c_void_p, c_int, c_int]
    _lib.disports_dave_prepare_transition.restype = None

    _lib.disports_dave_encrypt.argtypes = [c_void_p, c_uint32, POINTER(c_uint8), c_size_t, POINTER(c_uint8), c_size_t]
    _lib.disports_dave_encrypt.restype = c_size_t
    _lib.disports_dave_decrypt.argtypes = [c_void_p, c_uint32, POINTER(c_uint8), c_size_t, POINTER(c_uint8), c_size_t]
    _lib.disports_dave_decrypt.restype = c_size_t

    _lib.disports_dave_get_max_ciphertext_size.argtypes = [c_void_p, c_size_t]
    _lib.disports_dave_get_max_ciphertext_size.restype = c_size_t
    _lib.disports_dave_get_max_plaintext_size.argtypes = [c_void_p, c_uint32, c_size_t]
    _lib.disports_dave_get_max_plaintext_size.restype = c_size_t

    _lib.disports_dave_is_ready.argtypes = [c_void_p]
    _lib.disports_dave_is_ready.restype = c_bool

class DaveSession:
    def __init__(self, channel_id: str, self_user_id: str):
        self._channel_id = channel_id
        self._self_user_id = self_user_id
        self._session = None
        self._ssrc_to_user_id: dict[int, str] = {}
        self._cb_refs = []
        self._ready = False

        if not _lib:
            return

        self._session = _lib.disports_dave_create(int(channel_id), int(self_user_id))

    def __del__(self):
        if _lib and self._session:
            _lib.disports_dave_destroy(self._session)
            self._session = None

    def set_callbacks(self, send_binary, send_json):
        if not _lib or not self._session:
            return

        def _on_binary(opcode, data_ptr, size, user_data):
            data = ctypes.string_at(data_ptr, size)
            send_binary(opcode, data)

        def _on_json(opcode, transition_id, ok, user_data):
            payload = {"op": opcode, "d": {"transition_id": transition_id}}
            send_json(payload)

        cb1 = SendBinaryCB(_on_binary)
        cb2 = SendJsonCB(_on_json)
        self._cb_refs = [cb1, cb2] # keep alive
        _lib.disports_dave_set_callbacks(self._session, cb1, cb2, None)

    def init_session(self, protocol_version: int):
        if not _lib or not self._session: return
        self._ready = False
        _lib.disports_dave_init(self._session, protocol_version)
        _dlog(f"Session init proto={protocol_version} group_id={self._channel_id} self={self._self_user_id}")

    def reset(self):
        if not _lib or not self._session: return
        self._ready = False
        _lib.disports_dave_reset(self._session)

    def set_local_ssrc(self, ssrc: int):
        if not _lib or not self._session: return
        _lib.disports_dave_set_local_ssrc(self._session, c_uint32(ssrc))

    def register_ssrc(self, ssrc: int, user_id: str):
        if user_id == self._self_user_id:
            return
        self._ssrc_to_user_id[ssrc] = user_id
        _dlog(f"Registered SSRC {ssrc} -> user {user_id}")
        self._sync_roster()

    def add_connected_user(self, user_id: str):
        if not _lib or not self._session: return
        _lib.disports_dave_add_connected_user(self._session, c_uint64(int(user_id)))

    def remove_ssrc(self, ssrc: int):
        if ssrc in self._ssrc_to_user_id:
            del self._ssrc_to_user_id[ssrc]
            self._sync_roster()

    def _sync_roster(self):
        if not _lib or not self._session: return
        count = len(self._ssrc_to_user_id)
        ssrcs = (c_uint32 * count)()
        uids = (c_uint64 * count)()
        for i, (ssrc, uid_str) in enumerate(self._ssrc_to_user_id.items()):
            ssrcs[i] = ssrc
            uids[i] = int(uid_str)
        _lib.disports_dave_update_roster(self._session, ssrcs, uids, count)

    def process_welcome(self, transition_id: int, payload: bytes):
        if not _lib or not self._session: return
        buf = _byte_buffer(payload)
        _lib.disports_dave_process_welcome(self._session, transition_id, buf, len(payload))
        if transition_id == 0:
            self._ready = bool(_lib.disports_dave_is_ready(self._session))

    def process_commit(self, transition_id: int, payload: bytes):
        if not _lib or not self._session: return
        buf = _byte_buffer(payload)
        _lib.disports_dave_process_commit(self._session, transition_id, buf, len(payload))
        if transition_id == 0:
            self._ready = bool(_lib.disports_dave_is_ready(self._session))

    def process_proposals(self, payload: bytes):
        if not _lib or not self._session: return
        buf = _byte_buffer(payload)
        _lib.disports_dave_process_proposals(self._session, buf, len(payload))

    def set_external_sender(self, payload: bytes):
        if not _lib or not self._session: return
        buf = _byte_buffer(payload)
        _lib.disports_dave_set_external_sender(self._session, buf, len(payload))

    def execute_transition(self, transition_id: int):
        if not _lib or not self._session: return
        _lib.disports_dave_execute_transition(self._session, transition_id)
        self._ready = bool(_lib.disports_dave_is_ready(self._session))

    def prepare_epoch(self, epoch: int):
        if not _lib or not self._session: return
        if epoch == 1:
            self._ready = False
        _lib.disports_dave_prepare_epoch(self._session, epoch)

    def prepare_transition(self, transition_id: int, protocol_version: int):
        if not _lib or not self._session: return
        _lib.disports_dave_prepare_transition(self._session, transition_id, protocol_version)

    @property
    def is_ready(self) -> bool:
        if not _lib or not self._session or not self._ready: return False
        return _lib.disports_dave_is_ready(self._session)

    def encrypt_audio_frame(self, ssrc: int, opus_frame: bytes) -> Optional[bytes]:
        if not self.is_ready: return None
        max_out = _lib.disports_dave_get_max_ciphertext_size(self._session, len(opus_frame))
        out_buf = (c_uint8 * max_out)()
        frame_buf = _byte_buffer(opus_frame)
        written = _lib.disports_dave_encrypt(
            self._session, c_uint32(ssrc), frame_buf, len(opus_frame), out_buf, max_out
        )
        if written > 0:
            return bytes(out_buf[:written])
        return None

    def decrypt_audio_frame(self, ssrc: int, encrypted_frame: bytes) -> Optional[bytes]:
        if not self.is_ready: return None
        max_out = _lib.disports_dave_get_max_plaintext_size(self._session, c_uint32(ssrc), len(encrypted_frame))
        out_buf = (c_uint8 * max_out)()
        frame_buf = _byte_buffer(encrypted_frame)
        written = _lib.disports_dave_decrypt(
            self._session, c_uint32(ssrc), frame_buf, len(encrypted_frame), out_buf, max_out
        )
        if written > 0:
            return bytes(out_buf[:written])
        return None

    def debug_info(self) -> str:
        return f"available={_lib is not None} ready={self.is_ready} ssrcs={len(self._ssrc_to_user_id)}"
