import QtQuick 2.7
import Lomiri.Components 1.3

Item {
    id: waitingBar
    property bool running: false

    height: units.dp(3)
    visible: running
    clip: true

    Rectangle {
        id: flyer
        width: Math.max(parent.width / 4, units.gu(6))
        height: parent.height
        color: theme.palette.normal.activity

        SequentialAnimation on x {
            running: waitingBar.running && waitingBar.visible
            loops: Animation.Infinite
            NumberAnimation {
                from: 0
                to: waitingBar.width - flyer.width
                easing.type: Easing.InOutCubic
                duration: 1000
            }
            NumberAnimation {
                from: waitingBar.width - flyer.width
                to: 0
                easing.type: Easing.InOutCubic
                duration: 1400
            }
        }
    }
}
