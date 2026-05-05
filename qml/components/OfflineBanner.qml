import QtQuick 2.7
import QtQuick.Layouts 1.3
import Lomiri.Components 1.3

/*
 * NOTE: This component uses Layout.preferredHeight and Layout.fillWidth.
 * It MUST be instantiated as a direct child of a ColumnLayout or RowLayout
 * (e.g., in Main.qml) for the animated height transition to work.
 */
Rectangle {
    id: banner
    property bool isOnline: true
    Layout.fillWidth: true
    Layout.preferredHeight: isOnline ? 0 : units.gu(4)
    color: theme.palette.normal.negative
    clip: true

    Behavior on Layout.preferredHeight {
        NumberAnimation { duration: 250; easing.type: Easing.InOutQuad }
    }

    Row {
        anchors.centerIn: parent
        spacing: units.gu(1)
        Icon {
            name: "sync-error"
            width: units.gu(2)
            height: width
            color: "white"
        }
        Label {
            text: i18n.tr("No network connection")
            color: "white"
            font.bold: true
        }
    }
}
