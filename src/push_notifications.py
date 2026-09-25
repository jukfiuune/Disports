# Builds a Postal notification card from a Disports daemon envelope.
#
# Used by the push helper (pushexec): the system runs it when a notification
# envelope posted by the background daemon arrives while the app process is
# dead. The envelope is fully pre-computed by the daemon, so this module
# stays dependency-free.

import json

NOTIFICATION_ICON = "notification"


def build_postal_output(raw_payload: str) -> dict:
    try:
        envelope = json.loads(raw_payload or "{}")
    except ValueError:
        return {}
    if not isinstance(envelope, dict) or envelope.get("event_type") != "Message":
        return {}

    summary = str(envelope.get("summary") or "").strip()
    if not summary:
        return {}
    body = str(envelope.get("body") or "").strip()

    card = {
        "icon": str(envelope.get("icon") or "") or NOTIFICATION_ICON,
        "summary": summary,
        "body": body,
        "popup": True,
        "persist": True,
    }
    timestamp = envelope.get("timestamp")
    if isinstance(timestamp, int):
        card["timestamp"] = timestamp

    notification = {
        "card": card,
        "vibrate": True,
        "sound": True,
    }
    tag = str(envelope.get("tag") or "")
    if tag:
        notification["tag"] = tag

    return {"notification": notification}
