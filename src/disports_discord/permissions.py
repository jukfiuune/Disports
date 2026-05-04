from __future__ import annotations

from typing import Any


class PermissionsMixin:
    ADMINISTRATOR_PERMISSION = 1 << 3
    VIEW_CHANNEL_PERMISSION = 1 << 10
    CONNECT_PERMISSION = 1 << 20

    # ------------------------------------------------------------------
    # Channel visibility
    # ------------------------------------------------------------------

    @classmethod
    def can_access_channel(cls, channel: dict[str, Any]) -> bool:
        permissions = channel.get("permissions")
        if permissions is None:
            return True
        try:
            permission_bits = int(permissions)
        except (TypeError, ValueError):
            return True
        if not (permission_bits & cls.VIEW_CHANNEL_PERMISSION):
            return False
        channel_type = int(channel.get("type", -1))
        if channel_type in (2, 13) and not (permission_bits & cls.CONNECT_PERMISSION):
            return False
        return True

    def is_visible_guild_channel(self, guild_id: str, channel: dict[str, Any]) -> bool:
        channel_type = int(channel.get("type", -1))
        if channel_type not in (0, 2, 5, 10, 11, 12, 13, 15):
            return False
        return self.has_channel_access(guild_id, channel)

    def iter_visible_guild_channels(self, guild_id: str) -> list[dict[str, Any]]:
        return [
            channel
            for channel in self.guild_channels.get(guild_id, [])  # type: ignore[attr-defined]
            if self.is_visible_guild_channel(guild_id, channel)
        ]

    def has_channel_access(self, guild_id: str, channel: dict[str, Any]) -> bool:
        computed = self.compute_channel_permissions(guild_id, channel)
        if computed is None:
            return self.can_access_channel(channel)
        if not (computed & self.VIEW_CHANNEL_PERMISSION):
            return False
        channel_type = int(channel.get("type", -1))
        if channel_type in (2, 13) and not (computed & self.CONNECT_PERMISSION):
            return False
        return True

    def compute_channel_permissions(self, guild_id: str, channel: dict[str, Any]) -> int | None:
        if not self.me:  # type: ignore[attr-defined]
            return None

        role_permissions = self.guild_roles.get(guild_id)  # type: ignore[attr-defined]
        member = self.guild_members.get(guild_id)  # type: ignore[attr-defined]
        if not role_permissions or not member:
            return None

        me_id = (self.me or {}).get("id", "")  # type: ignore[attr-defined]
        everyone_permissions = role_permissions.get(guild_id, 0)
        permissions = everyone_permissions

        for role_id in member.get("roles", []) or []:
            permissions |= role_permissions.get(role_id, 0)

        if permissions & self.ADMINISTRATOR_PERMISSION:
            return (1 << 53) - 1

        overwrites = channel.get("permission_overwrites", []) or []

        everyone_overwrite = self._find_overwrite(overwrites, guild_id)
        permissions = self._apply_overwrite(permissions, everyone_overwrite)

        allow_roles = 0
        deny_roles = 0
        member_roles = set(member.get("roles", []) or [])
        for overwrite in overwrites:
            if overwrite.get("id") not in member_roles:
                continue
            if int(overwrite.get("type", 0)) != 0:
                continue
            allow_roles |= self._permission_value(overwrite.get("allow"))
            deny_roles |= self._permission_value(overwrite.get("deny"))
        permissions &= ~deny_roles
        permissions |= allow_roles

        member_overwrite = self._find_overwrite(overwrites, me_id)
        permissions = self._apply_overwrite(permissions, member_overwrite)
        return permissions

    # ------------------------------------------------------------------
    # Overwrite helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _find_overwrite(overwrites: list[dict[str, Any]], target_id: str) -> dict[str, Any] | None:
        for overwrite in overwrites:
            if overwrite.get("id") == target_id:
                return overwrite
        return None

    @classmethod
    def _apply_overwrite(cls, permissions: int, overwrite: dict[str, Any] | None) -> int:
        if not overwrite:
            return permissions
        deny = cls._permission_value(overwrite.get("deny"))
        allow = cls._permission_value(overwrite.get("allow"))
        permissions &= ~deny
        permissions |= allow
        return permissions

    @staticmethod
    def _permission_value(raw_value: Any) -> int:
        try:
            return int(raw_value or 0)
        except (TypeError, ValueError):
            return 0
