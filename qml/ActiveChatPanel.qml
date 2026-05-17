import QtQuick 2.7
import Lomiri.Components 1.3
import "./"

ChatPanel {
    id: activeChatPanel

    // Bind to shared models and settings
    messagesModel: chatMessageModel
    unicodeEmojis: appState.unicodeEmojis
    inlineGifPlayback: appSettings.inlineGifPlayback
    composerMaxLines: appSettings.maxComposerLines
    myUserId: appState.myUserId

    // Bind to transient appState
    channelId: appState.activeChannelId
    channelName: appState.activeChannelName
    serverName: appState.mode === "server" ? appState.activeServerName : ""
    activeServerId: appState.mode === "server" ? appState.activeServerId : ""
    activeServerIcon: appState.mode === "server" ? appState.activeServerIcon : ""
    serverEmojis: appState.mode === "server" ? appState.activeServerEmojis : []
    typingNotice: appState.typingNotice
    draftText: appState.draftText
    replyMessageId: appState.replyMessageId
    replyAuthor: appState.replyAuthor
    replyBody: appState.replyBody
    loadingOlder: appState.loadingOlderMessages

    // Wire up chatLogic signals
    onSendRequested: function(content, replyId) { chatLogic.postMessage(content, replyId) }
    onReplyRequested: function(mId) { chatLogic.setReplyTarget(mId) }
    onClearReplyRequested: chatLogic.clearReplyTarget()
    onDraftEdited: function(text) { appState.draftText = text }
    onEditRequested: function(mId, content) { chatLogic.editMessage(mId, content) }
    onDeleteRequested: function(mId) { chatLogic.confirmDeleteMessage(mId) }
    onChannelMentionRequested: function(channelId) { chatLogic.openChannelById(channelId) }
    onLoadOlderRequested: chatLogic.fetchOlderMessages()
    onReactionToggleRequested: function(mId, apiStr, already) { chatLogic.toggleReaction(mId, apiStr, already) }

    // Navigation
    onMediaPreviewRequested: function(url, type) {
        pageStack.push(Qt.resolvedUrl("MediaPreviewPage.qml"), {mediaUrl: url, mediaType: type})
    }
}
