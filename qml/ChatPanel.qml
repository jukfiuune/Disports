/*
 * ChatPanel.qml
 *
 * Reusable chat surface for both stacked and wide/convergent layouts.
 */

import QtQuick 2.7
import QtQuick.Layouts 1.3
import QtGraphicalEffects 1.0
import Lomiri.Components 1.3
import "./"
import "./components"

Item {
    id: chatPanel

    property string channelId: ""
    property string channelName: ""
    property var messagesModel
    property string myUserId: ""
    property string typingNotice: ""
    property string draftText: ""
    property string replyMessageId: ""
    property string replyAuthor: ""
    property string replyBody: ""
    // Edit mode
    property string editMessageId: ""
    property string editOriginalBody: ""
    property bool showHeader: true
    property bool initialScrollPending: channelId !== ""
    property bool anchoredToBottom: true
    property int lastMessageCount: 0
    property string highlightedMessageId: ""
    property real composerPadding: units.gu(1)
    property real composerMinHeight: units.gu(5)
    property real composerMaxHeight: units.gu(11)
    readonly property real keyboardInset: Qt.inputMethod.visible ? Qt.inputMethod.keyboardRectangle.height : 0
    readonly property real composerButtonSize: composerMinHeight
    readonly property real replyBarHeight: replyMessageId !== "" ? units.gu(4.5) : 0
    readonly property real editBarHeight: editMessageId !== "" ? units.gu(4.5) : 0
    readonly property real composerFieldHeight: Math.max(
                                                    composerMinHeight,
                                                    Math.min(
                                                        composerMaxHeight,
                                                        Math.max(msgInput.implicitHeight, msgInput.contentHeight + units.gu(2))
                                                    )
                                                )
    property bool loadingOlder: false
    property bool isOnline: true

    signal loadOlderRequested()
    signal sendRequested(string content, string replyMessageId)
    signal replyRequested(string messageId)
    signal clearReplyRequested()
    signal draftEdited(string text)
    signal editRequested(string messageId, string newContent)
    signal deleteRequested(string messageId)
    signal mediaPreviewRequested(string url, string type)

    onChannelIdChanged: {
        initialScrollPending = channelId !== ""
        anchoredToBottom = true
        lastMessageCount = messageList.count
        highlightedMessageId = ""
        // cancel any in-progress edit/reply when switching channels
        chatPanel.editMessageId = ""
        chatPanel.editOriginalBody = ""
    }

    Rectangle {
        anchors.fill: parent
        color: theme.palette.normal.background
    }

    PanelHeader {
        id: headerBackground
        anchors {
            top: parent.top
            left: parent.left
            right: parent.right
        }
        shown: showHeader
        title: chatPanel.channelName !== "" ? chatPanel.channelName : i18n.tr("Chat")
    }

    ListView {
        id: messageList
        anchors {
            top: headerBackground.bottom
            left: parent.left
            right: parent.right
            bottom: typingLabel.visible ? typingLabel.top : inputRow.top
        }
        model: chatPanel.messagesModel
        clip: true
        topMargin: units.gu(1)
        bottomMargin: typingLabel.visible ? units.gu(3.5) : units.gu(0.5)
        verticalLayoutDirection: ListView.BottomToTop
        highlightRangeMode: ListView.ApplyRange
        
        // Prevents fast-scrolling from asynchronous height jiggle
        cacheBuffer: units.gu(100)
        displayMarginBeginning: units.gu(40)
        displayMarginEnd: units.gu(40)
        
        footer: Item {
            width: messageList.width
            height: units.gu(6)
            visible: chatPanel.messagesModel && chatPanel.messagesModel.count > 0

            Button {
                anchors.centerIn: parent
                text: chatPanel.loadingOlder ? i18n.tr("Loading…") : i18n.tr("Load older messages")
                enabled: !chatPanel.loadingOlder
                onClicked: chatPanel.loadOlderRequested()
            }
        }
        
        onCountChanged: {
            var countIncreased = count > chatPanel.lastMessageCount
            var shouldScroll = countIncreased && (chatPanel.initialScrollPending || chatPanel.anchoredToBottom)
            chatPanel.lastMessageCount = count

            if (shouldScroll)
                Qt.callLater(chatPanel.scrollToBottom)
        }
        onHeightChanged: if (chatPanel.anchoredToBottom || chatPanel.initialScrollPending) Qt.callLater(chatPanel.scrollToBottom)
        onWidthChanged: if (chatPanel.anchoredToBottom || chatPanel.initialScrollPending) Qt.callLater(chatPanel.scrollToBottom)
        onContentHeightChanged: {
            if (chatPanel.anchoredToBottom || chatPanel.initialScrollPending)
                Qt.callLater(chatPanel.scrollToBottom)
            else
                Qt.callLater(chatPanel.rememberScrollPosition)
        }
        onContentYChanged: Qt.callLater(chatPanel.rememberScrollPosition)
        onMovementEnded: Qt.callLater(chatPanel.rememberScrollPosition)
        onDraggingChanged: if (!dragging) Qt.callLater(chatPanel.rememberScrollPosition)
        onFlickingChanged: if (!flicking) Qt.callLater(chatPanel.rememberScrollPosition)

        delegate: MessageBubble {
            width: messageList.width
            messageId: model.messageId || ""
            authorId: model.authorId || ""
            isOwn: chatPanel.myUserId !== "" && (model.authorId || "") === chatPanel.myUserId
            author: model.author
            timestamp: model.timestamp
            body: model.body
            displayKind: model.displayKind || "default"
            discordMessageType: model.discordMessageType || "Default"
            medias: model.medias || []
            hasReply: !!model.hasReply
            replyMessageId: model.replyMessageId || ""
            replyAuthor: model.replyAuthor || ""
            replyBody: model.replyBody || ""
            hasForwarded: !!model.hasForwarded
            forwardedLabel: model.forwardedLabel || ""
            forwardedAuthor: model.forwardedAuthor || ""
            forwardedBody: model.forwardedBody || ""
            highlighted: chatPanel.highlightedMessageId !== "" && chatPanel.highlightedMessageId === (model.messageId || "")
            onReplyRequested: function(messageId) { chatPanel.replyRequested(messageId) }
            onJumpRequested: function(messageId) { chatPanel.jumpToMessage(messageId) }
            onEditRequested: function(messageId, currentBody) {
                chatPanel.editMessageId = messageId
                chatPanel.editOriginalBody = currentBody
                msgInput.text = currentBody
                chatPanel.draftEdited(currentBody)
                msgInput.forceActiveFocus()
            }
            onDeleteRequested: function(messageId) { chatPanel.deleteRequested(messageId) }
            onMediaClicked: function(url, type) {
                if (type === "video" || type === "image") {
                    chatPanel.mediaPreviewRequested(url, type)
                } else {
                    Qt.openUrlExternally(url);
                }
            }
        }
    }

    Label {
        id: typingLabel
        anchors {
            left: parent.left
            right: parent.right
            bottom: inputRow.top
            leftMargin: units.gu(2)
            rightMargin: units.gu(2)
            bottomMargin: units.gu(0.5)
        }
        visible: chatPanel.typingNotice !== ""
        text: chatPanel.typingNotice
        color: theme.palette.normal.backgroundSecondaryText
        font.pixelSize: units.gu(1.3)
        elide: Text.ElideRight
    }

    Rectangle {
        id: inputRow
        anchors {
            left: parent.left
            right: parent.right
            bottom: parent.bottom
            leftMargin: units.gu(1)
            rightMargin: units.gu(1)
            bottomMargin: units.gu(1) + keyboardInset
        }
        height: composerPadding * 2 + composerFieldHeight + replyBarHeight + (replyBarHeight > 0 ? units.gu(0.5) : 0) + editBarHeight + (editBarHeight > 0 ? units.gu(0.5) : 0)
        color: theme.palette.normal.background

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: composerPadding
            spacing: units.gu(0.5)

            // Reply bar
            ComposerActionBar {
                id: replyBar
                accentColor: "#335280"
                title: i18n.tr("Replying to %1").arg(chatPanel.replyAuthor !== "" ? chatPanel.replyAuthor : i18n.tr("message"))
                subtitle: chatPanel.replyBody
                visible: chatPanel.replyMessageId !== ""
                onDismissed: chatPanel.clearReplyRequested()
            }

            // Edit bar
            ComposerActionBar {
                id: editBar
                accentColor: "#F0B232"
                title: i18n.tr("Editing message")
                visible: chatPanel.editMessageId !== ""
                onDismissed: {
                    chatPanel.editMessageId = ""
                    chatPanel.editOriginalBody = ""
                    msgInput.text = ""
                    chatPanel.draftEdited("")
                }
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.preferredHeight: composerFieldHeight
                spacing: units.gu(1)

                Item {
                    Layout.preferredWidth: composerButtonSize
                    Layout.preferredHeight: composerButtonSize
                    Layout.alignment: Qt.AlignBottom

                    Icon {
                        anchors.fill: parent
                        name: "attachment"
                        color: theme.palette.normal.backgroundSecondaryText
                    }
                }

                TextArea {
                    id: msgInput
                    Layout.fillWidth: true
                    Layout.preferredHeight: composerFieldHeight
                    activeFocusOnPress: true
                    autoSize: true
                    selectByMouse: true
                    mouseSelectionMode: TextEdit.SelectWords
                    wrapMode: TextEdit.WrapAtWordBoundaryOrAnywhere
                    placeholderText: !chatPanel.isOnline
                                     ? i18n.tr("Waiting for network...")
                                     : (chatPanel.replyMessageId !== ""
                                         ? i18n.tr("Reply to %1...").arg(chatPanel.replyAuthor !== "" ? chatPanel.replyAuthor : i18n.tr("message"))
                                         : i18n.tr("Type a message..."))
                    readOnly: !chatPanel.isOnline
                    textFormat: TextEdit.PlainText
                    Component.onCompleted: {
                        if (text !== chatPanel.draftText)
                            text = chatPanel.draftText
                    }
                    onTextChanged: {
                        if (text !== chatPanel.draftText)
                            chatPanel.draftEdited(text)
                    }

                    Keys.onEnterPressed: handleReturn(event)
                    Keys.onReturnPressed: handleReturn(event)

                    function handleReturn(event) {
                        if (Qt.inputMethod.visible) {
                            event.accepted = false
                            return
                        }
                        if (event.modifiers & Qt.ShiftModifier) {
                            event.accepted = false
                            return
                        }
                        chatPanel.submit()
                        event.accepted = true
                    }
                }

                Item {
                    id: sendBtn
                    Layout.preferredWidth: composerButtonSize
                    Layout.preferredHeight: composerButtonSize
                    Layout.alignment: Qt.AlignBottom
                    visible: msgInput.displayText.trim() !== "" || !chatPanel.isOnline
                    opacity: chatPanel.isOnline ? 1.0 : 0.4

                    Image {
                        id: sendIconSource
                        anchors.fill: parent
                        source: chatPanel.isOnline ? Qt.resolvedUrl("../assets/send.svg") : "image://theme/sync-updating"
                        fillMode: Image.PreserveAspectFit
                        smooth: true
                        sourceSize.width: width * 2
                        sourceSize.height: height * 2
                        visible: false
                    }

                    ColorOverlay {
                        anchors.fill: sendIconSource
                        source: sendIconSource
                        color: chatPanel.isOnline ? theme.palette.normal.backgroundText : theme.palette.normal.backgroundSecondaryText
                    }

                    MouseArea {
                        anchors.fill: parent
                        enabled: chatPanel.isOnline
                        onClicked: chatPanel.submit()
                    }
                }
            }
        }

        Rectangle {
            anchors.top: parent.top
            anchors.left: parent.left
            anchors.right: parent.right
            height: units.dp(1)
            color: theme.palette.normal.base
            opacity: 0.6
        }
    }

    function submit() {
        if (msgInput.text.trim() === "")
            return
        if (chatPanel.editMessageId !== "") {
            // Editing an existing message
            chatPanel.editRequested(chatPanel.editMessageId, msgInput.text)
            chatPanel.editMessageId = ""
            chatPanel.editOriginalBody = ""
        } else {
            chatPanel.sendRequested(msgInput.text, chatPanel.replyMessageId)
        }
        msgInput.text = ""
        chatPanel.draftEdited("")
    }

    onDraftTextChanged: {
        if (msgInput.text !== draftText)
            msgInput.text = draftText
    }

    function bottomGap() {
        return Math.abs(messageList.visibleArea.yPosition - (1 - messageList.visibleArea.heightRatio))
    }

    function rememberScrollPosition() {
        anchoredToBottom = bottomGap() <= 0.02
    }

    function scrollToBottom() {
        if (messageList.count > 0)
            messageList.positionViewAtBeginning()
        initialScrollPending = false
        anchoredToBottom = true
    }

    function jumpToMessage(messageId) {
        if (!messageId)
            return

        for (var i = 0; i < messageList.count; i++) {
            var item = messageList.model.get(i)
            if (item.messageId !== messageId)
                continue

            highlightedMessageId = messageId
            messageList.positionViewAtIndex(i, ListView.Center)
            highlightReset.restart()
            return
        }
    }

    Timer {
        id: highlightReset
        interval: 1400
        repeat: false
        onTriggered: chatPanel.highlightedMessageId = ""
    }
}
