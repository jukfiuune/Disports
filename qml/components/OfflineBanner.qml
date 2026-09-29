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
    property bool networkOnline: true
    property bool connectionReady: true
    property bool hasCachedSession: false
    property bool applicationActive: true
    property string reconnectPhase: "connecting"
    property int retrySeconds: 0
    property bool refreshing: false
    property bool showSuccess: false
    property bool successClosing: false
    property bool showReconnect: false
    property bool reconnectObserved: false
    readonly property bool reconnecting: hasCachedSession && !connectionReady
    readonly property bool expanded: showReconnect || showSuccess
    Layout.fillWidth: true
    Layout.preferredHeight: expanded ? units.gu(4) : 0
    // Keep the success color while its height animates closed. The rectangle
    // is already hidden when the next reconnect changes it back to red.
    color: showReconnect
           ? (networkOnline ? theme.palette.normal.activity : theme.palette.normal.negative)
           : theme.palette.normal.positive
    clip: true

    onReconnectingChanged: {
        if (reconnecting) {
            showSuccess = false
            successClosing = false
            successDelay.stop()
            successCloseDelay.stop()
            if (applicationActive)
                disconnectDelay.restart()
        } else {
            disconnectDelay.stop()
            if (reconnectObserved) {
                reconnectObserved = false
                showReconnect = false
                if (applicationActive) {
                    showSuccess = true
                    successDelay.restart()
                }
            }
        }
    }

    onApplicationActiveChanged: {
        if (!applicationActive) {
            disconnectDelay.stop()
            successDelay.stop()
            successCloseDelay.stop()
            showReconnect = false
            showSuccess = false
            successClosing = false
            reconnectObserved = false
        } else if (reconnecting) {
            disconnectDelay.restart()
        }
    }

    Behavior on Layout.preferredHeight {
        NumberAnimation { duration: 250; easing.type: Easing.InOutQuad }
    }

    Row {
        anchors.centerIn: parent
        spacing: units.gu(1)
        Icon {
            name: (showSuccess || successClosing) ? "tick" : (networkOnline ? "sync" : "sync-error")
            width: units.gu(2)
            height: width
            color: "white"
        }
        Label {
            text: {
                if (showSuccess || successClosing)
                    return i18n.tr("Connected")
                if (!networkOnline)
                    return i18n.tr("Offline - showing saved conversations")
                var action = i18n.tr("connecting to Discord")
                if (refreshing)
                    action = i18n.tr("refreshing the conversation")
                else if (reconnectPhase === "retry_wait" && retrySeconds > 0)
                    action = i18n.tr("retrying in %1 seconds").arg(retrySeconds)
                else if (reconnectPhase === "resume_wait" && retrySeconds > 0)
                    action = i18n.tr("resuming in %1 seconds").arg(retrySeconds)
                else if (reconnectPhase === "resuming")
                    action = i18n.tr("resuming your session")
                else if (reconnectPhase === "identifying")
                    action = i18n.tr("starting a new session")
                else if (reconnectPhase === "interrupted")
                    action = i18n.tr("connection interrupted")
                else if (reconnectPhase === "heartbeat")
                    action = i18n.tr("restoring the gateway")
                return i18n.tr("Reconnecting - %1").arg(action)
            }
            color: "white"
            font.bold: true
            elide: Text.ElideRight
        }
    }

    SequentialAnimation {
        id: successDelay
        PauseAnimation { duration: 2000 }
        ScriptAction {
            script: {
                banner.successClosing = true
                banner.showSuccess = false
                successCloseDelay.restart()
            }
        }
    }

    Timer {
        id: successCloseDelay
        interval: 275
        repeat: false
        onTriggered: banner.successClosing = false
    }

    Timer {
        id: disconnectDelay
        interval: 750
        repeat: false
        onTriggered: {
            if (!banner.reconnecting || !banner.applicationActive)
                return
            banner.reconnectObserved = true
            banner.showReconnect = true
        }
    }
}
