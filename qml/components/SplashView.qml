import QtQuick 2.7
import Lomiri.Components 1.3

Rectangle {
    id: splashView
    anchors.fill: parent
    property string startupPhase: ""
    visible: startupPhase === "initializing" || startupPhase === "checking" || startupPhase === "syncing"
    color: "#1f1f1f"
    z: 10000

    Column {
        anchors.centerIn: parent
        spacing: units.gu(4)

        Image {
            source: "../../assets/splash.svg"
            width: units.gu(20)
            height: units.gu(15)
            anchors.horizontalCenter: parent.horizontalCenter
            fillMode: Image.PreserveAspectFit
        }

        Column {
            spacing: units.gu(1)
            anchors.horizontalCenter: parent.horizontalCenter

            ActivityIndicator {
                anchors.horizontalCenter: parent.horizontalCenter
                running: splashView.visible
            }

            Label {
                text: {
                    if (splashView.startupPhase === "initializing")
                        return i18n.tr("Starting Disports…")
                    if (splashView.startupPhase === "syncing")
                        return i18n.tr("Loading your conversations…")
                    return i18n.tr("Signing in…")
                }
                color: "white"
                font.pixelSize: units.gu(1.5)
            }
        }
    }
}
