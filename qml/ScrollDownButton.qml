import QtQuick
import Lomiri.Components

// Floats over the chat's bottom right corner while it is scrolled away from
// the newest messages, like TELEports' button; slides in from the side.
LomiriShape {
    id: button

    property bool shown: false
    signal clicked()

    width: units.gu(6)
    height: width
    aspect: LomiriShape.DropShadow
    radius: "large"
    backgroundColor: area.pressed ? Qt.darker(theme.palette.normal.foreground, 1.3) : theme.palette.normal.foreground
    opacity: 0.9
    // Out of sight beside the chat until shown.
    anchors.rightMargin: shown ? width / 2 : -width * 2
    visible: anchors.rightMargin > -width * 2

    Behavior on anchors.rightMargin {
        SpringAnimation { spring: 2; damping: 0.2 }
    }

    MouseArea {
        id: area
        anchors.fill: parent
        enabled: button.shown
        onClicked: button.clicked()
    }

    Icon {
        anchors.centerIn: parent
        width: units.gu(3.5)
        height: width
        name: "toolkit_chevron-down_3gu"
        color: theme.palette.normal.baseText
    }
}
