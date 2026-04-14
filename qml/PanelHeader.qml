import QtQuick 2.7
import Lomiri.Components 1.3

Rectangle {
    id: panelHeader

    property string title: ""
    property bool shown: true

    height: shown ? units.gu(5) : 0
    visible: shown
    color: theme.palette.normal.background

    Label {
        anchors {
            left: parent.left
            right: parent.right
            verticalCenter: parent.verticalCenter
            leftMargin: units.gu(2)
            rightMargin: units.gu(2)
        }
        text: panelHeader.title
        font.pixelSize: units.gu(1.8)
        font.bold: true
        elide: Text.ElideRight
    }

    Rectangle {
        anchors.bottom: parent.bottom
        width: parent.width
        height: units.dp(1)
        color: theme.palette.normal.base
    }
}
