/*
 * SectionHeader.qml
 * Muted uppercase section label used in DmPanel and ServerPanel.
 */

import QtQuick 2.7
import Lomiri.Components 1.3

Item {
    property alias text: label.text
    width: parent.width
    height: units.gu(4)

    Label {
        id: label
        anchors {
            left: parent.left; right: parent.right
            verticalCenter: parent.verticalCenter
            leftMargin: units.gu(2)
        }
        font.pixelSize: units.gu(1.4)
        font.bold: true
        color: theme.palette.normal.backgroundSecondaryText
    }
}
