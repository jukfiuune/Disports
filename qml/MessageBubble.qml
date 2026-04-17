/*
 * MessageBubble.qml
 * One message row: bold author + muted timestamp, then body below.
 */

import QtQuick 2.7
import Lomiri.Components 1.3

ListItem {
    id: bubble
    property string messageId: ""
    property string authorId: ""
    property bool isOwn: false
    property string author
    property string timestamp
    property string body
    property string rawBody: ""
    property bool inlineGifPlayback: false
    property string displayKind: "default"
    property string discordMessageType: "Default"
    property var medias: []
    property bool hasReply: false
    property string replyMessageId: ""
    property string replyAuthor: ""
    property string replyBody: ""
    property bool hasForwarded: false
    property string forwardedLabel: ""
    property string forwardedAuthor: ""
    property string forwardedBody: ""
    property bool highlighted: false

    signal replyRequested(string messageId)
    signal jumpRequested(string messageId)
    signal editRequested(string messageId, string currentBody)
    signal deleteRequested(string messageId)
    signal mediaClicked(string url, string type)
    signal channelMentionRequested(string channelId)

    divider.visible: false
    height: inner.height + units.gu(displayKind === "system" ? 1 : 1.5)

    // Leading actions (swipe right): edit + delete — own messages only.
    // We assign via a Loader so that the swipe zone is completely absent
    // for messages we didn't send (disabled Actions still show as greyed icons).
    leadingActions: ownActionsLoader.item

    Loader {
        id: ownActionsLoader
        active: bubble.isOwn
        sourceComponent: ListItemActions {
            actions: [
                Action {
                    iconName: "delete"
                    text: i18n.tr("Delete")
                    onTriggered: bubble.deleteRequested(bubble.messageId)
                }
            ]
        }
    }

    // Trailing actions (swipe left): reply + edit (if own)
    
    Action {
        id: replyAction
        iconName: "mail-reply"
        text: i18n.tr("Reply")
        onTriggered: bubble.replyRequested(bubble.messageId)
    }
    
    Action {
        id: editAction
        iconName: "edit"
        text: i18n.tr("Edit")
        onTriggered: bubble.editRequested(bubble.messageId, bubble.rawBody !== "" ? bubble.rawBody : bubble.body)
    }

    Action {
        id: copyAction
        iconName: "edit-copy"
        text: i18n.tr("Copy")
        onTriggered: {
            var mimeData = Clipboard.newData();
            mimeData.text = bubble.rawBody !== "" ? bubble.rawBody : bubble.body;
            Clipboard.push(mimeData);
        }
    }

    trailingActions: ListItemActions {
        actions: {
            var arr = [];
            if (bubble.body !== "") arr.push(copyAction);
            if (bubble.isOwn) arr.push(editAction);
            arr.push(replyAction);
            return arr;
        }
    }

    Column {
        id: inner
        anchors {
            top: parent.top; left: parent.left; right: parent.right
            topMargin: units.gu(displayKind === "system" ? 0.5 : 0.75)
            leftMargin: units.gu(2); rightMargin: units.gu(2)
        }
        spacing: units.gu(0.3)

        Row {
            visible: bubble.displayKind !== "system"
            spacing: units.gu(1)
            Label {
                text: bubble.author
                font.pixelSize: units.gu(1.6)
                font.bold: true
            }
            Label {
                text: bubble.timestamp
                font.pixelSize: units.gu(1.3)
                color: theme.palette.normal.backgroundSecondaryText
                anchors.verticalCenter: parent.verticalCenter
            }
        }

        MessageCitation {
            width: parent.width
            visible: bubble.displayKind !== "system" && (bubble.hasReply || bubble.hasForwarded)
            author: bubble.previewAuthor()
            body: bubble.previewBody()
            onClicked: {
                if (bubble.hasReply && bubble.replyMessageId !== "")
                    bubble.jumpRequested(bubble.replyMessageId)
            }
        }

        Label {
            text: bubble.body
            width: parent.width
            wrapMode: Text.WordWrap
            font.pixelSize: units.gu(1.6)
            lineHeight: 1.3
            horizontalAlignment: bubble.displayKind === "system" ? Text.AlignHCenter : Text.AlignLeft
            color: bubble.displayKind === "system"
                   ? theme.palette.normal.backgroundSecondaryText
                   : theme.palette.normal.backgroundText
            font.italic: bubble.displayKind === "system"
            visible: bubble.body !== "" || bubble.displayKind === "system"
            textFormat: Text.RichText
            onLinkActivated: {
                var prefix = "disports://channel/"
                if (link.indexOf(prefix) === 0) {
                    bubble.channelMentionRequested(link.substring(prefix.length))
                    return
                }
                Qt.openUrlExternally(link)
            }
        }

        Repeater {
            model: bubble.medias || []
            delegate: MessageMedia {
                messageType: model.messageType || "text"
                mediaIsGifLike: !!model.mediaIsGifLike
                mediaContentType: model.mediaContentType || ""
                mediaUrl: model.mediaUrl || ""
                mediaPreviewUrl: model.mediaPreviewUrl || ""
                mediaWidth: model.mediaWidth || 0
                mediaHeight: model.mediaHeight || 0
                mediaFileName: model.mediaFileName || ""
                inlineGifPlayback: bubble.inlineGifPlayback
                body: ""
                onMediaClicked: function(url, type) {
                    bubble.mediaClicked(url, type)
                }
            }
        }
    }

    Rectangle {
        anchors.fill: parent
        color: theme.palette.normal.focus
        opacity: bubble.highlighted ? 0.12 : 0
        visible: bubble.highlighted
        z: -1
    }

    Rectangle {
        anchors.bottom: parent.bottom
        width: parent.width; height: units.dp(1)
        color: theme.palette.normal.base
        opacity: 0.4
    }

    function previewAuthor() {
        if (bubble.hasForwarded) {
            if (bubble.forwardedAuthor !== "")
                return bubble.forwardedLabel + " from " + bubble.forwardedAuthor
            return bubble.forwardedLabel
        }
        if (bubble.hasReply)
            return bubble.replyAuthor
        return ""
    }

    function previewBody() {
        if (bubble.hasForwarded)
            return bubble.forwardedBody
        if (bubble.hasReply)
            return bubble.replyBody
        return ""
    }
}
