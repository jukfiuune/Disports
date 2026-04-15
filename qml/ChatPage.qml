/*
 * ChatPage.qml
 *
 * Full-screen conversation view, pushed when the user opens any
 * contact, group, or channel from the panels.
 *
 * The back button (auto-provided by PageStack) returns to the main page.
 */

import QtQuick 2.7
import Lomiri.Components 1.3
import "./"

Page {
    id: chatPage
    objectName: "chatPage"
    property var stack
    property string channelId: ""
    property string channelName: ""
    property bool inlineGifPlayback: false
    property var messagesModel
    property string myUserId: ""
    property string typingNotice: ""
    property string draftText: ""
    property string replyMessageId: ""
    property string replyAuthor: ""
    property string replyBody: ""
    property bool loadingOlder: false
    property bool isOnline: true

    signal loadOlderRequested()
    signal sendRequested(string content, string replyMessageId)
    signal replyRequested(string messageId)
    signal clearReplyRequested()
    signal draftEdited(string text)
    signal editRequested(string messageId, string newContent)
    signal deleteRequested(string messageId)

    header: PageHeader {
        title: chatPage.channelName !== "" ? chatPage.channelName : i18n.tr("Chat")

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

    ChatPanel {
        anchors {
            top: chatPage.header.bottom
            left: parent.left
            right: parent.right
            bottom: parent.bottom
        }
        showHeader: false
        channelId: chatPage.channelId
        channelName: chatPage.channelName
        inlineGifPlayback: chatPage.inlineGifPlayback
        messagesModel: chatPage.messagesModel
        myUserId: chatPage.myUserId
        typingNotice: chatPage.typingNotice
        draftText: chatPage.draftText
        replyMessageId: chatPage.replyMessageId
        replyAuthor: chatPage.replyAuthor
        replyBody: chatPage.replyBody
        onSendRequested: function(content, replyMessageId) { chatPage.sendRequested(content, replyMessageId) }
        onReplyRequested: function(messageId) { chatPage.replyRequested(messageId) }
        onClearReplyRequested: chatPage.clearReplyRequested()
        onDraftEdited: function(text) { chatPage.draftEdited(text) }
        onEditRequested: function(messageId, newContent) { chatPage.editRequested(messageId, newContent) }
        onDeleteRequested: function(messageId) { chatPage.deleteRequested(messageId) }
        loadingOlder: chatPage.loadingOlder
        onLoadOlderRequested: chatPage.loadOlderRequested()
        isOnline: chatPage.isOnline
        onMediaPreviewRequested: function(url, type) {
            chatPage.stack.push(Qt.resolvedUrl("MediaPreviewPage.qml"), {mediaUrl: url, mediaType: type})
        }
    }
}
