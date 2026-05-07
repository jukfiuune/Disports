from __future__ import annotations

from .read_state import ReadStateMixin
from .guild_state import GuildStateMixin
from .message_formatter import MessageFormatterMixin
from .reactions import ReactionsMixin
from .permissions import PermissionsMixin
from .formatters import FormattersMixin
from .voice_state import VoiceStateMixin

class DiscordState(
    ReadStateMixin,
    GuildStateMixin,
    MessageFormatterMixin,
    ReactionsMixin,
    PermissionsMixin,
    FormattersMixin,
    VoiceStateMixin,
):
    MESSAGE_TYPE_NAMES = {
        0: "Default",
        1: "RecipientAdd",
        2: "RecipientRemove",
        3: "Call",
        4: "ChannelNameChange",
        5: "ChannelIconChange",
        6: "ChannelPinnedMessage",
        7: "GuildMemberJoin",
        8: "UserPremiumGuildSubscription",
        9: "TierOneUserPremiumGuildSubscription",
        10: "TierTwoUserPremiumGuildSubscription",
        11: "TierThreeUserPremiumGuildSubscription",
        12: "ChannelFollowAdd",
        14: "GuildDiscoveryDisqualified",
        15: "GuildDiscoveryRequalified",
        16: "GuildDiscoveryGracePeriodInitialWarning",
        17: "GuildDiscoveryGracePeriodFinalWarning",
        18: "ThreadCreated",
        19: "Reply",
        20: "ApplicationCommand",
        21: "ThreadStarterMessage",
        22: "GuildInviteReminder",
        23: "ContextMenuCommand",
        24: "AutoModAlert",
        25: "RoleSubscriptionPurchase",
        26: "InteractionPremiumUpsell",
        27: "StageStart",
        28: "StageEnd",
        29: "StageSpeaker",
        30: "StageRaiseHand",
        31: "StageTopic",
        32: "GuildApplicationPremiumSubscription",
        35: "PremiumReferral",
        36: "GuildIncidentAlertModeEnabled",
        37: "GuildIncidentAlertModeDisabled",
        38: "GuildIncidentReportRaid",
        39: "GuildIncidentReportFalseAlarm",
        44: "PurchaseNotification",
        46: "PollResult",
    }

    def __init__(self) -> None:
        # Note: All mixins call super().__init__() to ensure full initialization chain.
        super().__init__()

# Re-export for any direct imports that exist elsewhere
__all__ = ["DiscordState"]
