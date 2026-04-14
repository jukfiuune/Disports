from __future__ import annotations


class GatewayClosed(Exception):
    pass


class ReconnectRequested(Exception):
    def __init__(self, reset_session: bool = False) -> None:
        self.reset_session = reset_session
        super().__init__("Gateway requested reconnect")
