import QtQuick 2.7
import Lomiri.Components 1.3

Rectangle {
    property int count: 0
    property string kind: "none"

    visible: kind !== "none"
    width: kind === "dot" ? units.gu(1.2) : countLabel.width + units.gu(1.2)
    height: kind === "dot" ? units.gu(1.2) : units.gu(2.4)
    color:  theme.palette.normal.focus
    radius: height / 2

    Label {
        id: countLabel
        anchors.centerIn: parent
        text: parent.count
        visible: parent.kind === "count"
        font.pixelSize: units.gu(1.3)
        font.bold: true
        color: "white"
    }
}
