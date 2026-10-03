import QtQuick
import Lomiri.Components
import Lomiri.Components.Popups
import Disports.Core

// The open channel: its messages, the message box and the emoji panel.
Item {
    id: chatPanel

    // Where the media viewer, file picker and channel info open.
    property var pageStack
    property bool showHeader: true
    property bool emojiOpen: false

    function openMedia(media) {
        closeEmoji()
        if (media.viewType === "none")
            Qt.openUrlExternally(media.openUrl || media.viewUrl)
        else
            pageStack.push(Qt.resolvedUrl("MediaViewerPage.qml"), { "media": media })
    }

    function pickAttachment() {
        closeEmoji()
        const picker = pageStack.push(Qt.resolvedUrl("ContentPickerPage.qml"))
        picker.picked.connect(function(url, transfer) { composer.attach(url, transfer) })
    }

    function openEmoji() {
        emojiLoader.active = true
        if (emojiLoader.item)
            emojiLoader.item.reset()
        emojiOpen = true
        composer.hideKeyboard()
    }

    function closeEmoji() {
        emojiOpen = false
    }

    // Custom emoji a bit taller than a line of text, and large in messages
    // of only 1-3 emoji.
    Binding {
        target: Session.messages
        property: "emojiSize"
        value: Math.round(units.gu(2.2))
    }

    Binding {
        target: Session.messages
        property: "jumboEmojiSize"
        value: Math.round(units.gu(5))
    }

    Connections {
        target: Session
        function onCurrentChannelChanged() {
            chatPanel.closeEmoji()
            composer.reset()
        }
    }

    Rectangle {
        anchors.fill: parent
        color: theme.palette.normal.background
    }

    PanelHeader {
        id: header
        anchors { top: parent.top; left: parent.left; right: parent.right }
        visible: chatPanel.showHeader
        height: visible ? units.gu(5) : 0
        title: Session.currentChannelName
        subtitle: Session.currentChannelTopic
        actionIcon: "info"
        onActionTriggered: chatPanel.pageStack.push(Qt.resolvedUrl("ChannelInfoPage.qml"),
                                                    { "channelId": Session.currentChannelId })
        secondActionIcon: !(Session.connection.connected && Session.currentChannelId !== ""
                            && Session.call.canCall(Session.currentChannelId)) ? ""
                          : Session.currentChannelHasCall ? "active-call" : "call-start"
        secondActionColor: Session.currentChannelHasCall ? theme.palette.normal.positive
                                                         : theme.palette.normal.backgroundText
        onSecondActionTriggered: Session.call.start(Session.currentChannelId)
    }

    CallBar {
        id: callBar
        anchors { top: header.bottom; left: parent.left; right: parent.right }
    }

    MessageList {
        id: messageList
        anchors {
            top: callBar.bottom
            left: parent.left
            right: parent.right
            bottom: typingLabel.top
        }
        onReplyRequested: function(messageId, author, text) {
            chatPanel.closeEmoji()
            composer.startReply(messageId, author, text)
        }
        onReactRequested: function(messageId, caller) {
            chatPanel.closeEmoji()
            PopupUtils.open(reactionPopover, caller, { "messageId": messageId })
        }
        onEditRequested: function(messageId, text) {
            chatPanel.closeEmoji()
            composer.startEditing(messageId, text)
        }
        onDeleteRequested: function(messageId) {
            PopupUtils.open(deleteDialog, chatPanel, { "messageId": messageId })
        }
        onMediaOpened: function(media) { chatPanel.openMedia(media) }
        onProfileRequested: function(userId) {
            chatPanel.pageStack.push(Qt.resolvedUrl("ProfilePage.qml"), { "userId": userId })
        }
    }

    ScrollDownButton {
        anchors { right: messageList.right; bottom: messageList.bottom; bottomMargin: width / 2 }
        z: 1
        shown: messageList.count > 0 && !messageList.followNewest
        onClicked: messageList.scrollToNewest()
    }

    Label {
        id: typingLabel
        anchors {
            left: parent.left
            right: parent.right
            bottom: composer.top
            leftMargin: units.gu(2)
        }
        height: text !== "" ? units.gu(2.5) : 0
        text: Session.typing.text
        font.pixelSize: units.gu(1.3)
        font.italic: true
        color: theme.palette.normal.backgroundSecondaryText
    }

    Composer {
        id: composer
        anchors { left: parent.left; right: parent.right; bottom: emojiPanel.top }
        emojiOpen: chatPanel.emojiOpen
        onAttachRequested: chatPanel.pickAttachment()
        onEmojiButtonClicked: {
            if (chatPanel.emojiOpen) {
                chatPanel.closeEmoji()
                focusInput()
            } else {
                chatPanel.openEmoji()
            }
        }
        onInputFocused: chatPanel.closeEmoji()
        onSent: messageList.scrollToNewest()
    }

    // In place of the keyboard.
    Item {
        id: emojiPanel
        anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
        height: chatPanel.emojiOpen ? Math.min(units.gu(32), chatPanel.height * 0.5) : 0
        visible: height > 0
        clip: true

        Behavior on height {
            LomiriNumberAnimation {}
        }

        // Hundreds of emoji: built the first time it opens, then kept.
        Loader {
            id: emojiLoader
            anchors.fill: parent
            active: false
            sourceComponent: EmojiPicker {
                onPicked: function(emoji) { composer.insertText(emoji.insertText) }
            }
        }
    }

    Component {
        id: reactionPopover

        Popover {
            id: popover

            property string messageId: ""

            contentWidth: Math.min(units.gu(42), chatPanel.width - units.gu(4))

            Item {
                width: popover.contentWidth
                height: Math.min(units.gu(40), chatPanel.height * 0.6)

                EmojiPicker {
                    anchors.fill: parent
                    color: "transparent"
                    Component.onCompleted: reset()
                    onPicked: function(emoji) {
                        Session.addReaction(popover.messageId, emoji.reaction)
                        PopupUtils.close(popover)
                    }
                }
            }
        }
    }

    Component {
        id: deleteDialog

        Dialog {
            id: dialog

            property string messageId: ""

            title: i18n.tr("Delete message")
            text: i18n.tr("Are you sure you want to permanently delete this message?")

            Button {
                text: i18n.tr("Cancel")
                onClicked: PopupUtils.close(dialog)
            }

            Button {
                text: i18n.tr("Delete")
                color: theme.palette.normal.negative
                onClicked: {
                    Session.deleteMessage(dialog.messageId)
                    PopupUtils.close(dialog)
                }
            }
        }
    }
}
