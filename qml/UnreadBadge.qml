/*
 * UnreadBadge.qml
 * Shows a small count badge; invisible when count is 0.
 */

import QtQuick 2.7
import Lomiri.Components 1.3

Rectangle {
    property int count: 0

    visible: count > 0
    width:  countLabel.width + units.gu(1.2)
    height: units.gu(2.4)
    color:  theme.palette.normal.focus    // Ubuntu orange

    Label {
        id: countLabel
        anchors.centerIn: parent
        text: parent.count
        font.pixelSize: units.gu(1.3)
        font.bold: true
        color: "white"
    }
}
