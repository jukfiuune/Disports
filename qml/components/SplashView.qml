import QtQuick 2.7
import Lomiri.Components 1.3

// Startup renders the exact page component used by the live navigation stack.
// Cache hydration therefore fills the real models without a visual handoff to
// a separately maintained approximation.
Rectangle {
    id: startupView
    anchors.fill: parent
    property string startupPhase: ""
    property Component pageComponent
    visible: startupPhase === "initializing"
             || startupPhase === "checking"
             || startupPhase === "syncing"
    color: theme.palette.normal.background
    z: 10000

    Loader {
        anchors.fill: parent
        active: startupView.visible
        sourceComponent: startupView.pageComponent
    }

    WaitingBar {
        anchors { top: parent.top; left: parent.left; right: parent.right }
        running: startupView.visible
        z: 2
    }

    // This is a visual handoff while session initialization resolves. Avoid
    // accepting actions against partially initialized state.
    MouseArea { anchors.fill: parent; z: 3 }
}
