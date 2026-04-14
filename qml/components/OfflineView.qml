import QtQuick 2.7
import Lomiri.Components 1.3

Rectangle {
    id: offlineView
    anchors.fill: parent
    property bool visibleState: false
    visible: visibleState
    color: "#1f1f1f"
    z: 10000

    signal retryRequested()

    Column {
        anchors.centerIn: parent
        width: parent.width - units.gu(8)
        spacing: units.gu(3)

        Icon {
            name: "sync-error"
            width: units.gu(8)
            height: width
            color: "white"
            anchors.horizontalCenter: parent.horizontalCenter
        }

        Label {
            width: parent.width
            text: i18n.tr("No internet connection. Please check your network and try again.")
            color: "white"
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
            font.pixelSize: units.gu(2)
        }

        Button {
            text: i18n.tr("Retry")
            anchors.horizontalCenter: parent.horizontalCenter
            onClicked: offlineView.retryRequested()
        }
    }
}
