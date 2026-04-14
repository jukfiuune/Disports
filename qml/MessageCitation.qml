import QtQuick 2.7
import Lomiri.Components 1.3

Item {
    id: citation

    property string author: ""
    property string body: ""
    property string accentColor: "#335280"

    signal clicked()

    height: column.height + units.gu(0.5)
    width: Math.min(parent ? parent.width : implicitWidth, column.width + colorBlock.width + units.gu(1))

    Rectangle {
        id: colorBlock
        anchors {
            left: parent.left
            top: parent.top
        }
        width: units.dp(3)
        height: parent.height - units.gu(0.5)
        color: citation.accentColor
        opacity: 0.85
        radius: units.dp(2)
    }

    Column {
        id: column
        anchors {
            left: colorBlock.right
            leftMargin: units.gu(1)
            top: parent.top
            right: parent.right
        }
        spacing: 0

        Label {
            width: parent.width
            text: citation.author
            elide: Text.ElideRight
            color: citation.accentColor
            font.bold: true
            font.pixelSize: units.gu(1.35)
        }

        Label {
            width: parent.width
            text: citation.body
            wrapMode: Text.WordWrap
            maximumLineCount: 2
            elide: Text.ElideRight
            color: theme.palette.normal.backgroundSecondaryText
            font.pixelSize: units.gu(1.25)
        }
    }

    MouseArea {
        anchors.fill: parent
        enabled: citation.author !== "" || citation.body !== ""
        onClicked: citation.clicked()
    }
}
