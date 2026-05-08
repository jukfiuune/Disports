import QtQuick 2.7
import Lomiri.Components 1.3

Rectangle {
    id: root
    property alias model: listView.model
    property bool show: false

    anchors.fill: parent
    anchors.margins: units.gu(2)
    anchors.topMargin: units.gu(10)
    anchors.bottomMargin: units.gu(10)
    color: "#f2000000"
    radius: units.gu(1)
    border.color: "#333333"
    border.width: 1
    clip: true
    z: 10000
    visible: show

    ListView {
        id: listView
        anchors.fill: parent
        anchors.margins: units.gu(1)
        spacing: units.gu(0.5)

        delegate: Label {
            width: ListView.view.width
            text: logMessage
            color: "#00ff00"
            font.pixelSize: units.gu(1.5)
            font.family: "monospace"
            wrapMode: Text.Wrap
        }

        onCountChanged: {
            if (root.visible) {
                listView.positionViewAtEnd()
            }
        }
    }

    Button {
        anchors.top: parent.top
        anchors.right: parent.right
        anchors.margins: units.gu(1)
        text: i18n.tr("Clear")
        width: units.gu(8)
        onClicked: root.model.clear()
    }
}
