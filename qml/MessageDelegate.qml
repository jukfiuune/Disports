import QtQuick
import Lomiri.Components
import Disports.Core
import "MediaSize.js" as MediaSize

ListItem {
    id: bubble

    required property int index
    required property string messageId
    required property string authorId
    required property string author
    required property string avatarUrl
    // Rich text in blocks: [{text, quote}] (MessageListModel).
    required property var body
    required property string plainBody
    required property string timestamp
    required property bool edited
    required property bool isPending
    required property bool isOwn
    required property bool isSystem
    required property bool grouped
    required property bool hasReply
    required property string replyAuthor
    required property string replyBody
    required property var media
    required property var reactions
    required property var embeds
    required property string systemIcon
    required property string interaction
    required property bool forwarded
    required property var stickers
    required property var poll
    required property bool jumbo
    required property bool separated
    required property bool blocked
    required property string replyId
    required property bool firstNew

    signal replyRequested(string messageId, string author, string text)
    // Tapped the message this one replies to.
    signal jumpRequested(string messageId)
    // Tapped the author's picture or name.
    signal profileRequested(string userId)
    signal editRequested(string messageId, string text)
    signal deleteRequested(string messageId)
    // caller: the item the reaction picker points at
    signal reactRequested(string messageId, Item caller)
    signal mediaOpened(var media)

    // GIFs only play while on screen and the app is in front. Uses the
    // list's visible range (MessageList), which updates a few times a
    // second rather than every frame.
    readonly property bool onScreen: {
        const view = ListView.view
        return view !== null && visible
               && Qt.application.state !== Qt.ApplicationHidden
               && Qt.application.state !== Qt.ApplicationSuspended
               && y + height > view.visibleTop && y < view.visibleBottom
    }

    readonly property bool showAvatar: Session.preferences.chatProfilePictures
    readonly property real avatarSize: units.gu(4.5)
    // Without pictures, system messages still keep room for their icon.
    readonly property real contentLeft: showAvatar ? units.gu(2) + avatarSize + units.gu(1.5)
                                        : (isSystem || placeholder) ? units.gu(5.5) : units.gu(2)

    // Messages from blocked users (Settings > Blocked messages): hidden, a
    // placeholder to tap, or shown.
    property bool revealed: false
    readonly property string blockedMode: blocked && !revealed ? Session.preferences.blockedMessages : "show"
    readonly property bool hiddenBlocked: blockedMode === "hide"
    readonly property bool placeholder: blockedMode === "reveal"

    // System lines get even room above and below; messages a bit more
    // above, where a new author starts.
    height: hiddenBlocked ? 0
          : newBar.height + (placeholder ? placeholderLabel.height + units.gu(1.2)
          : isSystem ? content.height + units.gu(1.2)
          : grouped ? content.height + units.gu(0.3)
          // At least as tall as the avatar, so it never runs into the next row.
          : Math.max(content.height, avatar.visible ? avatar.height : 0) + units.gu(1.2))
    visible: !hiddenBlocked

    divider.visible: false
    opacity: isPending ? 0.5 : 1

    trailingActions: ListItemActions {
        actions: [
            Action {
                iconName: "mail-reply"
                text: i18n.tr("Reply")
                visible: !bubble.isPending && !bubble.isSystem && Session.permissions.canSendMessages
                onTriggered: bubble.replyRequested(bubble.messageId, bubble.author, bubble.plainBody)
            },
            Action {
                iconName: "bot"
                text: i18n.tr("React")
                visible: !bubble.isPending && !bubble.isSystem && Session.permissions.canAddReactions
                onTriggered: bubble.reactRequested(bubble.messageId, bubble)
            },
            Action {
                iconName: "edit"
                text: i18n.tr("Edit")
                // Editing happens in the message box, there when sending is.
                visible: bubble.isOwn && !bubble.isPending && !bubble.isSystem && Session.permissions.canSendMessages
                onTriggered: bubble.editRequested(bubble.messageId, bubble.plainBody)
            },
            Action {
                iconName: "edit-copy"
                text: i18n.tr("Copy")
                onTriggered: Clipboard.push(bubble.plainBody)
            }
        ]
    }

    // Swiping the other way: delete, Lomiri's leading (destructive) action.
    // Own messages, or anyone's for moderators; not system messages (calls,
    // pins, joins).
    leadingActions: ListItemActions {
        actions: [
            Action {
                iconName: "delete"
                text: i18n.tr("Delete")
                visible: !bubble.isPending && !bubble.isSystem && (bubble.isOwn || Session.permissions.canManageMessages)
                onTriggered: bubble.deleteRequested(bubble.messageId)
            }
        ]
    }

    // Above the first message not seen yet, as in TELEports.
    Item {
        id: newBar
        anchors { top: parent.top; left: parent.left; right: parent.right }
        height: bubble.firstNew ? units.gu(4) : 0
        visible: bubble.firstNew

        Rectangle {
            anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter }
            height: units.gu(3)
            // Suru's information colour.
            color: theme.palette.normal.background.hslLightness < 0.5 ? "#19b6ee" : "#335280"
            opacity: 0.8
        }

        Label {
            anchors.centerIn: parent
            text: i18n.tr("Unread messages")
            color: "white"
        }
    }

    // A line above every message that is not grouped with the one above it
    // (another author, or the same one after a while).
    Rectangle {
        visible: bubble.separated && !bubble.firstNew
        anchors { top: parent.top; left: parent.left; right: parent.right; leftMargin: units.gu(2); rightMargin: units.gu(2) }
        height: units.dp(1)
        color: theme.palette.normal.base
    }

    // Rich text ignores linkColor; its links take their colour from CSS.
    readonly property string linkStyle: "<style>a { color: " + theme.palette.normal.activity + "; }</style>"

    // One-line rows: system messages and the placeholder of a blocked
    // user's message. An icon where the avatar goes, centred on the first
    // line of text.
    readonly property bool lineRow: isSystem || placeholder

    readonly property real bodyPixelSize: jumbo ? units.gu(4.2) : units.gu(1.6)
    // After the last block: a system line's time, or "(edited)".
    readonly property string bodySuffix: isSystem
        ? " <font size=\"1\" color=\"" + theme.palette.normal.backgroundSecondaryText + "\">" + timestamp + "</font>"
        : edited ? " <font size=\"1\" color=\"#888\">(edited)</font>" : ""

    // A link in the text: a spoiler to show, or a page to open.
    function openLink(link) {
        if (link.indexOf("spoiler:") === 0)
            Session.messages.revealSpoiler(messageId, parseInt(link.substring(8)))
        else if (!Session.openChannelLink(link))
            Qt.openUrlExternally(link)
    }

    FontMetrics {
        id: bodyMetrics
        font.pixelSize: bubble.bodyPixelSize
    }

    Icon {
        visible: bubble.lineRow
        x: bubble.contentLeft - units.gu(1.5) - width
        // One line: its real height (inline emoji make it taller than the
        // font's line); more lines: the first one.
        readonly property Item line: bubble.placeholder ? placeholderLabel : bodyColumn.firstLabel
        readonly property real lineHeight: line && line.lineCount === 1 ? line.height : bodyMetrics.height
        y: (bubble.placeholder ? placeholderLabel.y : content.y + bodyColumn.y) + (lineHeight - height) / 2
        width: units.gu(2)
        height: width
        name: bubble.placeholder ? "security-alert" : bubble.systemIcon
        color: theme.palette.normal.backgroundSecondaryText
    }

    Label {
        id: placeholderLabel
        visible: bubble.placeholder
        anchors {
            left: parent.left
            right: parent.right
            top: parent.top
            leftMargin: bubble.contentLeft
            rightMargin: units.gu(2)
            topMargin: newBar.height + units.gu(0.6)
        }
        text: bubble.linkStyle + i18n.tr("Message from a blocked user") + " · <a href=\"show\">" + i18n.tr("Show") + "</a>"
              + " <font size=\"1\" color=\"" + theme.palette.normal.backgroundSecondaryText + "\">" + bubble.timestamp + "</font>"
        textFormat: Text.RichText
        wrapMode: Text.Wrap
        font.pixelSize: bubble.bodyPixelSize
        color: theme.palette.normal.backgroundSecondaryText
        onLinkActivated: bubble.revealed = true
    }

    // Flashes when jumped to from a reply.
    Rectangle {
        anchors.fill: parent
        color: theme.palette.normal.activity
        opacity: bubble.ListView.view && bubble.ListView.view.highlightedId === bubble.messageId ? 0.2 : 0
        Behavior on opacity { NumberAnimation { duration: 400 } }
    }

    // Along a forwarded message, from "Forwarded" down to its content.
    Rectangle {
        visible: bubble.forwarded && !bubble.placeholder
        x: bubble.contentLeft - units.gu(1)
        y: content.y + forwardedRow.y
        width: units.dp(3)
        radius: units.dp(2)
        height: (reactionsLoader.visible ? reactionsLoader.y - units.gu(0.3) : content.height) - forwardedRow.y
        color: theme.palette.normal.activity
    }

    SidebarIcon {
        id: avatar
        visible: bubble.showAvatar && !bubble.grouped && !bubble.isSystem && !bubble.placeholder
        anchors {
            left: parent.left
            top: parent.top
            leftMargin: units.gu(2)
            topMargin: newBar.height + units.gu(0.8)
        }
        width: bubble.avatarSize
        height: bubble.avatarSize
        imageSource: bubble.avatarUrl

        MouseArea {
            anchors.fill: parent
            enabled: bubble.authorId !== ""
            onClicked: bubble.profileRequested(bubble.authorId)
        }
    }

    Column {
        id: content
        visible: !bubble.placeholder
        anchors {
            left: parent.left
            right: parent.right
            top: parent.top
            leftMargin: bubble.contentLeft
            rightMargin: units.gu(2)
            topMargin: newBar.height + (bubble.isSystem ? units.gu(0.6) : bubble.grouped ? units.gu(0.15) : units.gu(0.8))
        }
        spacing: units.gu(0.3)

        // The message this one replies to; tap to go to it.
        MessageCitation {
            visible: bubble.hasReply
            width: parent.width
            title: bubble.replyAuthor !== "" ? bubble.replyAuthor : i18n.tr("Original message was deleted")
            text: bubble.replyBody
            tappable: bubble.replyId !== "" && bubble.replyAuthor !== ""
            onClicked: bubble.jumpRequested(bubble.replyId)
        }

        // Who ran the command this message answers
        Row {
            visible: bubble.interaction !== ""
            width: parent.width
            spacing: units.gu(0.75)

            Icon {
                anchors.verticalCenter: parent.verticalCenter
                width: units.gu(1.6)
                height: width
                name: "stock_application"
                color: theme.palette.normal.backgroundSecondaryText
            }

            Label {
                width: parent.width - units.gu(2.5)
                text: bubble.interaction
                textFormat: Text.StyledText
                textSize: Label.Small
                color: theme.palette.normal.backgroundSecondaryText
                elide: Text.ElideRight
            }
        }

        // Author and time
        Row {
            visible: !bubble.grouped && !bubble.isSystem
            spacing: units.gu(1)

            Label {
                text: bubble.author
                font.pixelSize: units.gu(1.6)
                font.bold: true
                font.italic: bubble.isSystem

                MouseArea {
                    anchors.fill: parent
                    enabled: bubble.authorId !== "" && !bubble.isSystem
                    onClicked: bubble.profileRequested(bubble.authorId)
                }
            }

            Label {
                anchors.baseline: parent.children[0].baseline
                text: bubble.timestamp
                font.pixelSize: units.gu(1.2)
                color: theme.palette.normal.backgroundSecondaryText
            }
        }

        Row {
            id: forwardedRow
            visible: bubble.forwarded
            spacing: units.gu(0.75)

            Icon {
                anchors.verticalCenter: parent.verticalCenter
                width: units.gu(1.6)
                height: width
                name: "mail-forwarded"
                color: theme.palette.normal.activity
            }

            Label {
                text: i18n.tr("Forwarded")
                font.pixelSize: units.gu(1.4)
                font.bold: true
                color: theme.palette.normal.activity
            }
        }

        // The text, block by block: quotes with a bar on the left.
        Column {
            id: bodyColumn
            width: parent.width
            visible: bubble.body.length > 0
            readonly property Item firstLabel: bodyBlocks.count > 0 && bodyBlocks.itemAt(0) ? bodyBlocks.itemAt(0).label : null

            Repeater {
                id: bodyBlocks
                model: bubble.body

                delegate: Item {
                    required property var modelData
                    required property int index
                    readonly property alias label: blockLabel

                    width: bodyColumn.width
                    height: blockLabel.height

                    Rectangle {
                        visible: modelData.quote
                        width: units.dp(3)
                        height: parent.height
                        radius: width / 2
                        color: theme.palette.normal.base
                    }

                    Label {
                        id: blockLabel
                        x: modelData.quote ? units.gu(1.2) : 0
                        width: parent.width - x
                        text: bubble.linkStyle + modelData.text
                              + (index === bubble.body.length - 1 ? bubble.bodySuffix : "")
                        textFormat: Text.RichText
                        wrapMode: Text.Wrap
                        // Only 1-3 emoji: large, like Discord
                        font.pixelSize: bubble.bodyPixelSize
                        color: bubble.isSystem ? theme.palette.normal.backgroundSecondaryText
                                               : theme.palette.normal.backgroundText
                        onLinkActivated: function(link) { bubble.openLink(link) }
                    }
                }
            }
        }

        // Pictures and videos. Their room is reserved from the start
        // (MediaSize.js) so the row doesn't grow while scrolling.
        Item {
            width: parent.width
            height: MediaSize.totalHeight(bubble.media, mediaColumn.maxWidth, units.gu(30), units.gu(5),
                                          mediaColumn.spacing)
            visible: bubble.media.length > 0

            Column {
                id: mediaColumn
                // Before the row has its width (created on screen), the
                // widest a preview gets: its size on a phone anyway.
                readonly property real maxWidth: content.width > 0 ? Math.min(content.width, units.gu(30)) : units.gu(30)
                spacing: content.spacing

                Repeater {
                    model: bubble.media

                    delegate: MediaPreview {
                        required property var modelData
                        media: modelData
                        maxWidth: mediaColumn.maxWidth
                        playing: bubble.onScreen
                        onOpened: function(media) { bubble.mediaOpened(media) }
                    }
                }
            }
        }

        Repeater {
            model: bubble.embeds

            delegate: EmbedCard {
                required property var modelData
                embed: modelData
                messageId: bubble.messageId
                width: Math.min(content.width, units.gu(52))
                playing: bubble.onScreen
                onMediaOpened: function(media) { bubble.mediaOpened(media) }
            }
        }

        // Stickers: a fixed size each, room kept from the start too.
        Item {
            width: parent.width
            height: bubble.stickers.length * units.gu(16) + Math.max(0, bubble.stickers.length - 1) * stickerColumn.spacing
            visible: bubble.stickers.length > 0

            Column {
                id: stickerColumn
                spacing: content.spacing

                Repeater {
                    model: bubble.stickers

                    delegate: StickerView {
                        required property var modelData
                        sticker: modelData
                        playing: bubble.onScreen
                    }
                }
            }
        }

        Loader {
            active: !!bubble.poll
            visible: active
            width: Math.min(content.width, units.gu(52))
            sourceComponent: PollCard {
                messageId: bubble.messageId
                poll: bubble.poll
            }
        }

        // Only built for messages with reactions.
        Loader {
            id: reactionsLoader
            width: parent.width
            active: bubble.reactions.length > 0
            visible: active
            sourceComponent: ReactionBar {
                width: parent ? parent.width : 0
                messageId: bubble.messageId
                reactions: bubble.reactions
                // System messages' reactions are shown, not joined in on.
                canAdd: !bubble.isSystem && Session.permissions.canAddReactions
                canToggle: !bubble.isSystem && Session.permissions.canUseReactions
                onAddRequested: function(caller) { bubble.reactRequested(bubble.messageId, caller) }
            }
        }
    }
}
