import QtQuick
import Lomiri.Components
import Disports.Core

// A link preview or bot embed: a Lomiri card with the embed's colour on the
// left, then provider, author, title, description, fields, picture and
// footer, each shown when present.
LomiriShape {
    id: card

    // For its spoilers (MessageListModel.revealSpoiler()).
    property string messageId

    // An entry of a message's `embeds`, see MessageContent::embeds().
    property var embed: ({})
    property bool playing: false

    signal mediaOpened(var media)

    readonly property real padding: units.gu(1.25)
    readonly property bool hasThumbnail: (embed.thumbnailUrl || "") !== ""
    readonly property real textWidth: width - padding * 2 - units.dp(4)
                                      - (hasThumbnail ? units.gu(8) + padding : 0)

    height: content.height + padding * 2
    aspect: LomiriShape.Flat
    radius: "small"
    backgroundColor: theme.palette.normal.foreground

    // Rich text ignores linkColor; its links take their colour from CSS.
    readonly property string linkStyle: "<style>a { color: " + theme.palette.normal.activity + "; }</style>"

    function openLink(link) {
        if (link && link.indexOf("spoiler:") === 0) {
            Session.messages.revealSpoiler(card.messageId, parseInt(link.substring(8)))
            return
        }
        if (link && !Session.openChannelLink(link))
            Qt.openUrlExternally(link)
    }

    // Colour bar
    Rectangle {
        anchors { left: parent.left; top: parent.top; bottom: parent.bottom; topMargin: units.dp(2); bottomMargin: units.dp(2) }
        width: units.dp(4)
        radius: width / 2
        color: card.embed.color || theme.palette.normal.base
    }

    Column {
        id: content
        x: card.padding + units.dp(4)
        y: card.padding
        width: card.width - card.padding * 2 - units.dp(4)
        spacing: units.gu(0.6)

        Item {
            width: parent.width
            height: Math.max(textColumn.height, card.hasThumbnail ? thumbnail.height : 0)
            visible: height > 0

            Column {
                id: textColumn
                width: card.textWidth
                spacing: units.gu(0.6)

                Label {
                    width: parent.width
                    visible: text !== ""
                    text: card.embed.provider || ""
                    textSize: Label.XSmall
                    color: theme.palette.normal.backgroundSecondaryText
                    elide: Text.ElideRight
                }

                Row {
                    visible: (card.embed.author || "") !== ""
                    width: parent.width
                    spacing: units.gu(0.75)

                    LomiriShape {
                        id: authorIcon
                        visible: (card.embed.authorIcon || "") !== ""
                        width: units.gu(2.5)
                        height: width
                        aspect: LomiriShape.Flat
                        radius: "small"
                        sourceFillMode: LomiriShape.PreserveAspectCrop
                        source: Image {
                            source: card.embed.authorIcon || ""
                            asynchronous: true
                            sourceSize.width: units.gu(5)
                        }
                    }

                    Label {
                        anchors.verticalCenter: parent.verticalCenter
                        width: parent.width - (authorIcon.visible ? authorIcon.width + parent.spacing : 0)
                        text: card.embed.author || ""
                        textSize: Label.Small
                        font.bold: true
                        elide: Text.ElideRight

                        MouseArea {
                            anchors.fill: parent
                            enabled: (card.embed.authorUrl || "") !== ""
                            onClicked: card.openLink(card.embed.authorUrl)
                        }
                    }
                }

                Label {
                    width: parent.width
                    visible: text !== ""
                    text: card.embed.title || ""
                    textFormat: Text.StyledText
                    font.bold: true
                    wrapMode: Text.Wrap
                    color: (card.embed.url || "") !== "" ? theme.palette.normal.activity
                                                        : theme.palette.normal.backgroundText

                    MouseArea {
                        anchors.fill: parent
                        enabled: (card.embed.url || "") !== ""
                        onClicked: card.openLink(card.embed.url)
                    }
                }

                Label {
                    width: parent.width
                    visible: text !== ""
                    text: card.embed.description ? card.linkStyle + card.embed.description : ""
                    textFormat: Text.RichText
                    textSize: Label.Small
                    wrapMode: Text.Wrap
                    onLinkActivated: function(link) { card.openLink(link) }
                }
            }

            LomiriShape {
                id: thumbnail
                visible: card.hasThumbnail
                anchors.right: parent.right
                width: units.gu(8)
                height: width
                aspect: LomiriShape.Flat
                radius: "small"
                backgroundColor: theme.palette.normal.base
                sourceFillMode: LomiriShape.PreserveAspectCrop
                source: Image {
                    source: card.embed.thumbnailUrl || ""
                    asynchronous: true
                    sourceSize.width: units.gu(16)
                }
            }
        }

        // Fields: inline ones two to a row, the others full width.
        Flow {
            width: parent.width
            visible: (card.embed.fields || []).length > 0
            spacing: units.gu(1)

            Repeater {
                model: card.embed.fields || []

                delegate: Column {
                    required property var modelData
                    width: modelData.inline ? (content.width - units.gu(1)) / 2 : content.width
                    spacing: units.gu(0.2)

                    Label {
                        width: parent.width
                        text: modelData.name
                        textFormat: Text.RichText
                        textSize: Label.Small
                        font.bold: true
                        wrapMode: Text.Wrap
                    }

                    Label {
                        width: parent.width
                        text: card.linkStyle + modelData.value
                        textFormat: Text.RichText
                        textSize: Label.Small
                        wrapMode: Text.Wrap
                            onLinkActivated: function(link) { card.openLink(link) }
                    }
                }
            }
        }

        MediaPreview {
            visible: !!card.embed.image
            media: card.embed.image || ({})
            maxWidth: content.width
            playing: card.playing
            onOpened: function(media) { card.mediaOpened(media) }
        }

        Row {
            visible: (card.embed.footer || "") !== ""
            width: parent.width
            spacing: units.gu(0.75)

            LomiriShape {
                id: footerIcon
                visible: (card.embed.footerIcon || "") !== ""
                width: units.gu(2)
                height: width
                aspect: LomiriShape.Flat
                radius: "small"
                sourceFillMode: LomiriShape.PreserveAspectCrop
                source: Image {
                    source: card.embed.footerIcon || ""
                    asynchronous: true
                    sourceSize.width: units.gu(4)
                }
            }

            Label {
                anchors.verticalCenter: parent.verticalCenter
                width: parent.width - (footerIcon.visible ? footerIcon.width + parent.spacing : 0)
                text: card.embed.footer || ""
                textSize: Label.XSmall
                color: theme.palette.normal.backgroundSecondaryText
                elide: Text.ElideRight
            }
        }
    }
}
