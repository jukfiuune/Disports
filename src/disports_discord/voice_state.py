from __future__ import annotations
from typing import Any

class VoiceStateMixin:
    def __init__(self) -> None:
        self.voice_states: dict[str, Any] = {}
        self.calls: dict[str, Any] = {}
        self.active_voice_server: dict[str, Any] | None = None
        self.active_voice_state: dict[str, Any] | None = None
        super().__init__()

    def apply_voice_state_update(self, data: dict[str, Any]) -> None:
        user_id = str(data.get("user_id") or "")
        self.voice_states[user_id] = data
        if str(user_id) == str((getattr(self, "me", {}) or {}).get("id", "")):
            self.active_voice_state = data

    def apply_voice_server_update(self, data: dict[str, Any]) -> None:
        self.active_voice_server = data
        
    def apply_call_create(self, data: dict[str, Any]) -> None:
        channel_id = data.get("channel_id")
        if channel_id:
            self.calls[channel_id] = data

    def apply_call_update(self, data: dict[str, Any]) -> None:
        channel_id = data.get("channel_id")
        if channel_id and channel_id in self.calls:
            self.calls[channel_id].update(data)

    def apply_call_delete(self, data: dict[str, Any]) -> None:
        channel_id = data.get("channel_id")
        if channel_id in self.calls:
            del self.calls[channel_id]
