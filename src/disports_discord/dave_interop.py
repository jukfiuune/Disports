from __future__ import annotations

import ctypes
import os
import sys
from ctypes import c_void_p, c_char_p, c_uint16, c_uint32, c_uint64, c_size_t, c_bool, POINTER, CFUNCTYPE, c_int, c_byte
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

class DAVEEncryptorResultCode:
    Success = 0
    EncryptionFailure = 1
    MissingKeyRatchet = 2
    MissingCryptor = 3
    TooManyAttempts = 4

class DAVEDecryptorResultCode:
    Success = 0
    DecryptionFailure = 1
    MissingKeyRatchet = 2
    InvalidNonce = 3
    MissingCryptor = 4

_lib = None
_load_errors: list[str] = []
_lib_paths = [
    "libdave.so",
    os.path.join(os.path.dirname(__file__), "..", "..", "lib", "libdave.so"),
    os.path.join(os.environ.get("APP_DIR", ""), "lib", "libdave.so"),
]

for path in _lib_paths:
    try:
        _lib = ctypes.CDLL(path)
        _dlog(f"Successfully loaded libdave from {path}")
        _loaded_path = path
        break
    except OSError as exc:
        _load_errors.append(f"{path}: {exc}")
        continue

if not _lib:
    _dlog("Warning: Failed to load libdave.so from any expected location")
    _loaded_path = ""

def libdave_status() -> dict[str, object]:
    return {
        "available": _lib is not None,
        "path": _loaded_path,
        "searched": list(_lib_paths),
        "errors": list(_load_errors),
    }

def _ptr_value(ptr) -> int | None:
    if not ptr:
        return None
    return getattr(ptr, "value", ptr)

DAVEMLSFailureCallback = CFUNCTYPE(None, c_char_p, c_char_p, c_void_p)

if _lib:
    _lib.daveFree.argtypes = [c_void_p]
    _lib.daveFree.restype = None

    _lib.daveSessionCreate.argtypes = [c_void_p, c_char_p, DAVEMLSFailureCallback, c_void_p]
    _lib.daveSessionCreate.restype = c_void_p

    _lib.daveSessionDestroy.argtypes = [c_void_p]
    _lib.daveSessionDestroy.restype = None

    _lib.daveSessionInit.argtypes = [c_void_p, c_uint16, c_uint64, c_char_p]
    _lib.daveSessionInit.restype = None

    _lib.daveSessionReset.argtypes = [c_void_p]
    _lib.daveSessionReset.restype = None

    _lib.daveSessionSetProtocolVersion.argtypes = [c_void_p, c_uint16]
    _lib.daveSessionSetProtocolVersion.restype = None

    _lib.daveSessionSetExternalSender.argtypes = [c_void_p, POINTER(c_byte), c_size_t]
    _lib.daveSessionSetExternalSender.restype = None

    _lib.daveSessionProcessProposals.argtypes = [
        c_void_p, POINTER(c_byte), c_size_t, c_void_p, c_size_t, POINTER(c_void_p), POINTER(c_size_t)
    ]
    _lib.daveSessionProcessProposals.restype = None

    _lib.daveSessionProcessCommit.argtypes = [c_void_p, POINTER(c_byte), c_size_t]
    _lib.daveSessionProcessCommit.restype = c_void_p

    _lib.daveSessionProcessWelcome.argtypes = [c_void_p, POINTER(c_byte), c_size_t, c_void_p, c_size_t]
    _lib.daveSessionProcessWelcome.restype = c_void_p

    _lib.daveSessionGetMarshalledKeyPackage.argtypes = [c_void_p, POINTER(c_void_p), POINTER(c_size_t)]
    _lib.daveSessionGetMarshalledKeyPackage.restype = None

    _lib.daveSessionGetKeyRatchet.argtypes = [c_void_p, c_char_p]
    _lib.daveSessionGetKeyRatchet.restype = c_void_p

    _lib.daveCommitResultIsFailed.argtypes = [c_void_p]
    _lib.daveCommitResultIsFailed.restype = c_bool

    _lib.daveCommitResultIsIgnored.argtypes = [c_void_p]
    _lib.daveCommitResultIsIgnored.restype = c_bool

    _lib.daveCommitResultGetRosterMemberIds.argtypes = [c_void_p, POINTER(c_void_p), POINTER(c_size_t)]
    _lib.daveCommitResultGetRosterMemberIds.restype = None

    _lib.daveCommitResultDestroy.argtypes = [c_void_p]
    _lib.daveCommitResultDestroy.restype = None

    _lib.daveWelcomeResultGetRosterMemberIds.argtypes = [c_void_p, POINTER(c_void_p), POINTER(c_size_t)]
    _lib.daveWelcomeResultGetRosterMemberIds.restype = None

    _lib.daveWelcomeResultDestroy.argtypes = [c_void_p]
    _lib.daveWelcomeResultDestroy.restype = None

    _lib.daveDecryptorCreate.argtypes = []
    _lib.daveDecryptorCreate.restype = c_void_p

    _lib.daveDecryptorDestroy.argtypes = [c_void_p]
    _lib.daveDecryptorDestroy.restype = None

    _lib.daveDecryptorTransitionToKeyRatchet.argtypes = [c_void_p, c_void_p]
    _lib.daveDecryptorTransitionToKeyRatchet.restype = None

    _lib.daveDecryptorDecrypt.argtypes = [
        c_void_p, c_int, POINTER(c_byte), c_size_t, POINTER(c_byte), c_size_t, POINTER(c_size_t)
    ]
    _lib.daveDecryptorDecrypt.restype = c_int

    _lib.daveDecryptorGetMaxPlaintextByteSize.argtypes = [c_void_p, c_int, c_size_t]
    _lib.daveDecryptorGetMaxPlaintextByteSize.restype = c_size_t

    _lib.daveEncryptorCreate.argtypes = []
    _lib.daveEncryptorCreate.restype = c_void_p

    _lib.daveEncryptorDestroy.argtypes = [c_void_p]
    _lib.daveEncryptorDestroy.restype = None

    _lib.daveEncryptorSetKeyRatchet.argtypes = [c_void_p, c_void_p]
    _lib.daveEncryptorSetKeyRatchet.restype = None

    _lib.daveEncryptorGetMaxCiphertextByteSize.argtypes = [c_void_p, c_int, c_size_t]
    _lib.daveEncryptorGetMaxCiphertextByteSize.restype = c_size_t

    _lib.daveEncryptorEncrypt.argtypes = [
        c_void_p, c_int, c_uint32, POINTER(c_byte), c_size_t, POINTER(c_byte), c_size_t, POINTER(c_size_t)
    ]
    _lib.daveEncryptorEncrypt.restype = c_int

def free(ptr):
    if _lib and ptr:
        _lib.daveFree(ptr)

def session_create(auth_session_id: str, callback: DAVEMLSFailureCallback) -> c_void_p:
    if not _lib: return None
    return _lib.daveSessionCreate(None, auth_session_id.encode('utf-8'), callback, None)

def session_destroy(session: c_void_p):
    if _lib and session:
        _lib.daveSessionDestroy(session)

def _on_mls_failure(source: bytes, reason: bytes, user_data: c_void_p):
    src = source.decode('utf-8', errors='replace') if source else "unknown"
    rsn = reason.decode('utf-8', errors='replace') if reason else "unknown"
    _dlog(f"MLS failure source={src}, reason={rsn}")

_mls_failure_cb_instance = DAVEMLSFailureCallback(_on_mls_failure)

class DaveSession:
    def __init__(self):
        self._session = session_create("", _mls_failure_cb_instance)
        self._encryptor = c_void_p(None)
        self._decryptors = {}
        self._ssrc_to_user_id = {}
        self._last_external_sender = None
        self._self_user_id = ""
        self._disposed = False
        if not self._session:
            _dlog("Warning: daveSessionCreate returned None.")
        else:
            _dlog("Session created.")

    @property
    def available(self) -> bool:
        return bool(_lib and self._session)

    def status_summary(self) -> str:
        return (
            f"available={self.available} "
            f"encryptor={_ptr_value(self._encryptor)} "
            f"decryptors={len(self._decryptors)} "
            f"ssrcs={len(self._ssrc_to_user_id)} "
            f"self_user_id={self._self_user_id or '<unset>'}"
        )

    def init(self, protocol_version: int, channel_id: str, self_user_id: str):
        self._self_user_id = self_user_id
        try:
            group_id = int(channel_id)
        except ValueError:
            group_id = 0
        if _lib and self._session:
            _lib.daveSessionInit(self._session, protocol_version, group_id, self_user_id.encode('utf-8'))
            _dlog(f"Session init proto={protocol_version} group_id={group_id} self={self_user_id}")
        else:
            _dlog("Session init skipped: lib/session unavailable.")

    def set_external_sender(self, payload: bytes):
        self._last_external_sender = payload
        if _lib and self._session:
            payload_ptr = ctypes.cast(payload, POINTER(c_byte))
            _lib.daveSessionSetExternalSender(self._session, payload_ptr, len(payload))
            _dlog(f"External sender set len={len(payload)}")
        else:
            _dlog(f"External sender cached len={len(payload)}; lib/session unavailable.")

    def process_proposals(self, payload: bytes) -> Optional[bytes]:
        if not _lib or not self._session:
            _dlog("Proposals skipped: lib/session unavailable.")
            return None
        ids = list(set(list(self._ssrc_to_user_id.values()) + [self._self_user_id]))
        ids_c = [s.encode('utf-8') for s in ids]
        arr_type = c_char_p * len(ids_c)
        ids_arr = arr_type(*ids_c)
        payload_ptr = ctypes.cast(payload, POINTER(c_byte))
        out_ptr = c_void_p()
        out_len = c_size_t()
        _lib.daveSessionProcessProposals(
            self._session, payload_ptr, len(payload),
            ctypes.cast(ids_arr, c_void_p), len(ids_c),
            ctypes.byref(out_ptr), ctypes.byref(out_len)
        )
        result = self._read_and_free(out_ptr, out_len)
        _dlog(f"Proposals processed in={len(payload)} out={len(result or b'')}")
        return result

    def process_welcome(self, welcome_payload: bytes) -> bool:
        if not _lib or not self._session:
            _dlog("Welcome skipped: lib/session unavailable.")
            return False
        ids = list(set(list(self._ssrc_to_user_id.values()) + [self._self_user_id]))
        ids_c = [s.encode('utf-8') for s in ids]
        arr_type = c_char_p * len(ids_c)
        ids_arr = arr_type(*ids_c)
        payload_ptr = ctypes.cast(welcome_payload, POINTER(c_byte))
        result = _lib.daveSessionProcessWelcome(
            self._session, payload_ptr, len(welcome_payload),
            ctypes.cast(ids_arr, c_void_p), len(ids_c)
        )
        if not result:
            _dlog("ProcessWelcome returned None.")
            return False
        self._update_decryptors_from_welcome(result)
        _lib.daveWelcomeResultDestroy(result)
        if not self._decryptors:
            for uid in set(self._ssrc_to_user_id.values()):
                self._try_create_decryptor(uid)
        self._init_self_encryptor()
        _dlog(f"Welcome processed OK; {self.status_summary()}")
        return True

    def process_commit(self, commit_payload: bytes) -> bool:
        if not _lib or not self._session:
            _dlog("Commit skipped: lib/session unavailable.")
            return False
        payload_ptr = ctypes.cast(commit_payload, POINTER(c_byte))
        result = _lib.daveSessionProcessCommit(self._session, payload_ptr, len(commit_payload))
        if not result:
            _dlog("ProcessCommit returned None.")
            return False
        failed = _lib.daveCommitResultIsFailed(result)
        ignored = _lib.daveCommitResultIsIgnored(result)
        if not failed and not ignored:
            self._update_decryptors_from_commit(result)
            self._init_self_encryptor()
        else:
            _dlog(f"Commit skipped: failed={failed}, ignored={ignored}")
        _lib.daveCommitResultDestroy(result)
        _dlog(f"Commit processed failed={failed} ignored={ignored}; {self.status_summary()}")
        return not failed and not ignored

    def get_key_package(self) -> Optional[bytes]:
        if not _lib or not self._session:
            _dlog("Key package unavailable: lib/session unavailable.")
            return None
        out_ptr = c_void_p()
        out_len = c_size_t()
        _lib.daveSessionGetMarshalledKeyPackage(self._session, ctypes.byref(out_ptr), ctypes.byref(out_len))
        result = self._read_and_free(out_ptr, out_len)
        _dlog(f"Key package len={len(result or b'')}")
        return result

    def reset_and_get_key_package(self, protocol_version: int) -> Optional[bytes]:
        if not _lib or not self._session:
            _dlog("Reset/key package skipped: lib/session unavailable.")
            return None
        _lib.daveSessionReset(self._session)
        _lib.daveSessionSetProtocolVersion(self._session, protocol_version)
        _dlog(f"Session reset; protocol={protocol_version}")
        if self._last_external_sender:
            self.set_external_sender(self._last_external_sender)
        return self.get_key_package()

    def register_ssrc(self, ssrc: int, user_id: str):
        self._ssrc_to_user_id[ssrc] = user_id
        _dlog(f"Registered SSRC {ssrc} -> user {user_id}")

    def encrypt_audio_frame(self, ssrc: int, opus_frame: bytes) -> Optional[bytes]:
        if not _lib or not self._encryptor:
            return None
        max_out = _lib.daveEncryptorGetMaxCiphertextByteSize(
            self._encryptor, DAVEMediaType.Audio, len(opus_frame)
        )
        out_buf = (c_byte * max_out)()
        written = c_size_t()
        frame_ptr = ctypes.cast(opus_frame, POINTER(c_byte))
        code = _lib.daveEncryptorEncrypt(
            self._encryptor,
            DAVEMediaType.Audio,
            c_uint32(ssrc),
            frame_ptr, len(opus_frame),
            ctypes.cast(out_buf, POINTER(c_byte)), max_out,
            ctypes.byref(written),
        )
        if code != DAVEEncryptorResultCode.Success:
            return None
        return bytes(out_buf)[: written.value]

    def decrypt_audio_frame(self, ssrc: int, encrypted_frame: bytes) -> Optional[bytes]:
        if not _lib: return None
        user_id = self._ssrc_to_user_id.get(ssrc)
        if not user_id: return None
        decryptor = self._decryptors.get(user_id)
        if not decryptor: return None
        max_out = _lib.daveDecryptorGetMaxPlaintextByteSize(decryptor, DAVEMediaType.Audio, len(encrypted_frame))
        out_buf = (c_byte * max_out)()
        written = c_size_t()
        frame_ptr = ctypes.cast(encrypted_frame, POINTER(c_byte))
        code = _lib.daveDecryptorDecrypt(
            decryptor, DAVEMediaType.Audio,
            frame_ptr, len(encrypted_frame),
            ctypes.cast(out_buf, POINTER(c_byte)), max_out,
            ctypes.byref(written)
        )
        if code != DAVEDecryptorResultCode.Success:
            if code != DAVEDecryptorResultCode.MissingKeyRatchet:
                _dlog(f"Decrypt failed ssrc={ssrc} code={code}")
            return None
        return bytes(out_buf)[:written.value]

    def _init_self_encryptor(self):
        ratchet = _lib.daveSessionGetKeyRatchet(self._session, self._self_user_id.encode('utf-8'))
        if not ratchet:
            _dlog("No key ratchet for self.")
            return
        if not self._encryptor:
            self._encryptor = _lib.daveEncryptorCreate()
        _lib.daveEncryptorSetKeyRatchet(self._encryptor, ratchet)

    def _try_create_decryptor(self, user_id: str):
        ratchet = _lib.daveSessionGetKeyRatchet(self._session, user_id.encode('utf-8'))
        if not ratchet:
            _dlog(f"No key ratchet for userId {user_id}")
            return
        if user_id not in self._decryptors:
            self._decryptors[user_id] = _lib.daveDecryptorCreate()
        _lib.daveDecryptorTransitionToKeyRatchet(self._decryptors[user_id], ratchet)

    def _update_decryptors_from_commit(self, commit_result: c_void_p):
        out_ptr = c_void_p()
        out_len = c_size_t()
        _lib.daveCommitResultGetRosterMemberIds(commit_result, ctypes.byref(out_ptr), ctypes.byref(out_len))
        self._update_decryptors_from_roster(out_ptr, out_len)

    def _update_decryptors_from_welcome(self, welcome_result: c_void_p):
        out_ptr = c_void_p()
        out_len = c_size_t()
        _lib.daveWelcomeResultGetRosterMemberIds(welcome_result, ctypes.byref(out_ptr), ctypes.byref(out_len))
        self._update_decryptors_from_roster(out_ptr, out_len)

    def _update_decryptors_from_roster(self, roster_ptr: c_void_p, roster_len: c_size_t):
        if not roster_ptr or roster_len.value == 0: return
        count = roster_len.value
        uint64_array = ctypes.cast(roster_ptr, POINTER(c_uint64))
        for i in range(count):
            uid_str = str(uint64_array[i])
            if uid_str == self._self_user_id: continue
            ratchet = _lib.daveSessionGetKeyRatchet(self._session, uid_str.encode('utf-8'))
            if not ratchet: continue
            if uid_str not in self._decryptors:
                self._decryptors[uid_str] = _lib.daveDecryptorCreate()
            _lib.daveDecryptorTransitionToKeyRatchet(self._decryptors[uid_str], ratchet)
        _lib.daveFree(roster_ptr)

    def _read_and_free(self, ptr: c_void_p, length: c_size_t) -> Optional[bytes]:
        if not ptr or length.value == 0: return None
        data = ctypes.string_at(ptr, length.value)
        _lib.daveFree(ptr)
        return data

    def dispose(self):
        if self._disposed: return
        self._disposed = True
        if _lib:
            for d in self._decryptors.values():
                if d: _lib.daveDecryptorDestroy(d)
            self._decryptors.clear()
            if self._session:
                _lib.daveSessionDestroy(self._session)
                self._session = None
            if self._encryptor:
                _lib.daveEncryptorDestroy(self._encryptor)
                self._encryptor = None

