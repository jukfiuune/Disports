import QtQuick 2.7
import QtQuick.Layouts 1.3
import Lomiri.Components 1.3

Rectangle {
    id: root
    Layout.fillWidth: true
    Layout.preferredHeight: units.gu(4.5)
    radius: units.gu(0.6)
    color: theme.palette.normal.base
    opacity: 0.45

    property color accentColor: "#335280"
    property string title: ""
    property string subtitle: ""

    signal dismissed()

    Rectangle {
        anchors {
            left: parent.left
            top: parent.top
            bottom: parent.bottom
            margins: units.gu(0.7)
        }
        width: units.dp(3)
        radius: units.dp(2)
        color: root.accentColor
    }

    Column {
        anchors {
            left: parent.left
            right: closeButton.left
            top: parent.top
            bottom: parent.bottom
            leftMargin: units.gu(2)
            rightMargin: units.gu(1)
            topMargin: units.gu(0.5)
            bottomMargin: units.gu(0.5)
        }
        spacing: units.dp(1)

        Label {
            width: parent.width
            text: root.title
            elide: Text.ElideRight
            color: root.accentColor
            font.bold: true
            font.pixelSize: units.gu(1.25)
        }

        Label {
            width: parent.width
            text: root.subtitle
            elide: Text.ElideRight
            maximumLineCount: 1
            color: theme.palette.normal.backgroundSecondaryText
            font.pixelSize: units.gu(1.2)
            visible: text !== ""
        }
    }

    Item {
        id: closeButton
        anchors {
            right: parent.right
            rightMargin: units.gu(0.5)
            verticalCenter: parent.verticalCenter
        }
        width: units.gu(3)
        height: width

        Icon {
            anchors.centerIn: parent
            width: units.gu(1.6)
            height: width
            name: "close"
            color: theme.palette.normal.backgroundSecondaryText
        }

        MouseArea {
            anchors.fill: parent
            onClicked: root.dismissed()
        }
    }
}
