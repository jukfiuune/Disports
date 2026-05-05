import QtQuick 2.7
import Lomiri.Components 1.3
import "./"

Page {
    id: chatPage
    objectName: "chatPage"
    property var stack

    header: PageHeader {
        title: appState.activeChannelName !== "" ? appState.activeChannelName : i18n.tr("Chat")

        leadingActionBar.actions: [
            Action {
                iconName: "back"
                text: i18n.tr("Back")
                onTriggered: chatPage.stack.pop()
            }
        ]

        trailingActionBar.actions: [
            Action {
                iconName: "info"
                text: i18n.tr("Info")
                onTriggered: { /* TODO: channel/contact info sheet */ }
            }
        ]
    }

    ActiveChatPanel {
        anchors {
            top: chatPage.header.bottom
            left: parent.left
            right: parent.right
            bottom: parent.bottom
        }
        showHeader: false
    }
}
