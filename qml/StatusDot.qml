/*
 * StatusDot.qml
 * Small square status indicator matching Discord's four presence states.
 * Colors are Discord's canonical brand values (independent of UITK theme).
 *
 * Discord gateway status strings:
 *   "online"    → green  (#23A55A)
 *   "idle"      → amber  (#F0B232)
 *   "dnd"       → red    (#F23F43)
 *   "offline"   → grey   (#80848E)
 *   "invisible" → grey   (#80848E)  (appears offline to others)
 *
 * Square rather than circular to match Ubuntu Touch's flatter aesthetic.
 */

import QtQuick 2.7
import Lomiri.Components 1.3

Rectangle {
    property string status: "offline"   // "online" | "idle" | "dnd" | "offline" | "invisible"

    width:  units.gu(1.2)
    height: units.gu(1.2)

    color: {
        if (status === "online")    return "#23A55A"
        if (status === "idle")      return "#F0B232"
        if (status === "dnd")       return "#F23F43"
        return "#80848E"   // offline / invisible / unknown
    }
}
