import QtQuick 2.7
import Lomiri.Components 1.3

ListItem {
    id: bubble
    property string messageId: ""
    property string authorId: ""
    property bool isOwn: false
    property string author
    property string timestamp
    property string rawTimestamp: ""
    property string body
    property string rawBody: ""
    property bool inlineGifPlayback: false
    property string displayKind: "default"
    property string discordMessageType: "Default"
    property var medias: []
    property var richEmbeds: []
    property string reactionsJson: "[]"
    property var parsedReactions: []

    onReactionsJsonChanged: {
        try { parsedReactions = JSON.parse(reactionsJson) }
        catch(e) { parsedReactions = [] }
    }
    Component.onCompleted: {
        try { parsedReactions = JSON.parse(reactionsJson) }
        catch(e) { parsedReactions = [] }
    }

    property bool hasReply: false
    property string replyMessageId: ""
    property string replyAuthor: ""
    property string replyBody: ""
    property bool hasForwarded: false
    property string forwardedLabel: ""
    property string forwardedAuthor: ""
    property string forwardedBody: ""
    property bool highlighted: false
    property bool authorBlocked: false
    property string blockedVisibility: "show"  // "show" | "reveal" | "hide"
    property bool _revealedByUser: false
    property bool isPending: false
    property bool isGrouped: false
    property bool isGroupedWithNext: false

    // Effective visibility: if the user tapped "Show message", treat as show.
    readonly property string _effectiveVisibility:
        _revealedByUser ? "show" : blockedVisibility

    signal replyRequested(string messageId)
    signal jumpRequested(string messageId)
    signal editRequested(string messageId, string currentBody)
    signal deleteRequested(string messageId)
    signal mediaClicked(string url, string type)
    signal channelMentionRequested(string channelId)
    signal reactEmojiRequested(string messageId)
    signal reactionToggleRequested(string messageId, string apiString, bool alreadyReacted)

    opacity: isPending ? 0.5 : 1.0
    divider.visible: false
    // "hide" = fully collapsed with no height; "reveal" = placeholder only.
    height: {
        if (_effectiveVisibility === "hide") return 0;
        if (_effectiveVisibility === "reveal") return revealPlaceholder.implicitHeight + units.gu(1);
        
        var topPad = bubble.isGrouped ? 0.15 : (displayKind === "system" ? 0.5 : 0.75);
        var botPad = bubble.isGroupedWithNext ? 0.25 : (displayKind === "system" ? 0.5 : 0.75);
        return inner.height + units.gu(topPad + botPad);
    }
    visible: _effectiveVisibility !== "hide"

    // Leading actions (swipe right): delete - own messages only.
    leadingActions: ownActionsLoader.item

    Loader {
        id: ownActionsLoader
        active: bubble.isOwn && !bubble.isPending
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

    // Trailing actions (swipe left): copy, edit (if own), reply, add reaction
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

    Action {
        id: reactAction
        iconName: "bot"
        text: i18n.tr("React")
        onTriggered: bubble.reactEmojiRequested(bubble.messageId)
    }

    trailingActions: ListItemActions {
        actions: {
            var arr = [];
            if (bubble.isPending) return arr;
            if (bubble.body !== "") arr.push(copyAction);
            if (bubble.isOwn) arr.push(editAction);
            arr.push(replyAction);
            arr.push(reactAction);
            return arr;
        }
    }

    // Reveal placeholder — shown when blockedVisibility === "reveal" and user hasn't tapped yet.
    Item {
        id: revealPlaceholder
        anchors {
            left: parent.left; right: parent.right
            top: parent.top
            topMargin: units.gu(0.5)
            leftMargin: units.gu(2); rightMargin: units.gu(2)
        }
        visible: bubble._effectiveVisibility === "reveal"
        implicitHeight: revealRow.height + units.gu(0.5)

        Row {
            id: revealRow
            spacing: units.gu(1)
            anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter }

            Label {
                text: bubble.author
                font.pixelSize: units.gu(1.5)
                font.bold: true
                font.strikeout: true
                color: theme.palette.normal.backgroundSecondaryText
                anchors.verticalCenter: parent.verticalCenter
            }

            Label {
                text: i18n.tr("Message from blocked user")
                font.pixelSize: units.gu(1.4)
                font.italic: true
                color: theme.palette.normal.backgroundSecondaryText
                elide: Text.ElideRight
                anchors.verticalCenter: parent.verticalCenter
            }

            Label {
                text: i18n.tr("Show")
                font.pixelSize: units.gu(1.4)
                color: theme.palette.normal.focus
                anchors.verticalCenter: parent.verticalCenter
                MouseArea {
                    anchors.fill: parent
                    onClicked: bubble._revealedByUser = true
                }
            }
        }
    }

    // Main content — only rendered when visible to avoid layout cost.
    Column {
        id: inner
        visible: bubble._effectiveVisibility === "show"
        anchors {
            top: parent.top; left: parent.left; right: parent.right
            topMargin: bubble.isGrouped ? units.gu(0.15) : units.gu(displayKind === "system" ? 0.5 : 0.75)
            leftMargin: units.gu(2); rightMargin: units.gu(2)
        }
        spacing: units.gu(0.3)

        Row {
            visible: bubble.displayKind !== "system" && !bubble.isGrouped
            spacing: units.gu(1)
            Label {
                text: bubble.author
                font.pixelSize: units.gu(1.6)
                font.bold: true
                font.strikeout: bubble.authorBlocked
                color: bubble.authorBlocked
                       ? theme.palette.normal.backgroundSecondaryText
                       : theme.palette.normal.backgroundText
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

        Repeater {
            model: bubble.richEmbeds || []
            delegate: Item {
                width: parent.width
                implicitHeight: Math.max(embedCol.height, units.gu(2)) + units.gu(1)

                Rectangle {
                    id: embedBar
                    anchors {
                        left: parent.left
                        top: parent.top
                        bottom: parent.bottom
                        bottomMargin: units.gu(1)
                    }
                    width: units.dp(4)
                    color: model.color || theme.palette.normal.base
                    radius: units.dp(2)
                }

                Column {
                    id: embedCol
                    anchors {
                        left: embedBar.right
                        leftMargin: units.gu(1.5)
                        right: parent.right
                        top: parent.top
                    }

                    Label {
                        width: parent.width
                        text: model.html || ""
                        textFormat: Text.RichText
                        wrapMode: Text.WordWrap
                        font.pixelSize: units.gu(1.4)
                        color: theme.palette.normal.backgroundSecondaryText
                        lineHeight: 1.2
                        onLinkActivated: {
                            var prefix = "disports://channel/"
                            if (link.indexOf(prefix) === 0) {
                                bubble.channelMentionRequested(link.substring(prefix.length))
                                return
                            }
                            Qt.openUrlExternally(link)
                        }
                    }
                }
            }
        }

        // Reaction chips
        Flow {
            id: reactionsRow
            width: parent.width
            spacing: units.gu(0.5)
            topPadding: bubble.parsedReactions.length > 0 ? units.gu(0.4) : 0
            visible: bubble.parsedReactions.length > 0

            Repeater {
                model: bubble.parsedReactions.length
                delegate: Item {
                    id: chipRoot
                    readonly property var reaction: bubble.parsedReactions[index] || null
                    readonly property bool reacted: reaction ? !!reaction.me : false
                    readonly property bool isCustom: reaction ? !!reaction.isCustom : false

                    width: chipRow.width + units.gu(1.6)
                    height: units.gu(3)

                    Rectangle {
                        anchors.fill: parent
                        radius: height / 2
                        color: chipRoot.reacted
                               ? theme.palette.highlighted.base
                               : theme.palette.normal.base
                        opacity: chipRoot.reacted ? 0.28 : 0.55
                        border.width: chipRoot.reacted ? units.dp(1.2) : 0
                        border.color: theme.palette.highlighted.base
                    }

                    Row {
                        id: chipRow
                        anchors.centerIn: parent
                        spacing: units.gu(0.35)

                        // Unicode emoji label
                        Label {
                            visible: !chipRoot.isCustom
                            text: chipRoot.reaction ? (chipRoot.reaction.emojiName || "") : ""
                            font.pixelSize: units.gu(1.7)
                            anchors.verticalCenter: parent.verticalCenter
                        }

                        // Custom emoji image
                        Image {
                            visible: chipRoot.isCustom && chipRoot.reaction && (chipRoot.reaction.emojiUrl || "") !== ""
                            source: (chipRoot.reaction && chipRoot.reaction.emojiUrl) ? chipRoot.reaction.emojiUrl : ""
                            width: units.gu(2)
                            height: units.gu(2)
                            fillMode: Image.PreserveAspectFit
                            asynchronous: true
                            cache: true
                            anchors.verticalCenter: parent.verticalCenter
                        }

                        Label {
                            text: chipRoot.reaction ? String(chipRoot.reaction.count || 0) : "0"
                            font.pixelSize: units.gu(1.4)
                            font.bold: chipRoot.reacted
                            color: chipRoot.reacted
                                   ? theme.palette.highlighted.backgroundText
                                   : theme.palette.normal.backgroundSecondaryText
                            anchors.verticalCenter: parent.verticalCenter
                        }
                    }

                    MouseArea {
                        anchors.fill: parent
                        onClicked: {
                            if (!chipRoot.reaction) return
                            bubble.reactionToggleRequested(
                                bubble.messageId,
                                chipRoot.reaction.apiString || "",
                                chipRoot.reacted
                            )
                        }
                    }
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
        visible: !bubble.isGroupedWithNext
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
