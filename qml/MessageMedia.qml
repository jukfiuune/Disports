import QtQuick 2.7
import QtMultimedia 5.0
import Lomiri.Components 1.3

Item {
    id: mediaRoot

    property string messageType: "text"
    property bool mediaIsGifLike: false
    property string mediaUrl: ""
    property string mediaPreviewUrl: ""
    property int mediaWidth: 0
    property int mediaHeight: 0
    property string mediaFileName: ""
    property string mediaContentType: ""
    property string body: ""
    property bool inlineGifPlayback: false

    signal mediaClicked(string url, string type)

    readonly property real maxMediaWidth: units.gu(30)
    readonly property real maxMediaHeight: units.gu(24)
    readonly property real aspectRatio: mediaWidth > 0 && mediaHeight > 0 ? mediaWidth / mediaHeight : 1.0
    readonly property bool inlineGifMode: mediaRoot.messageType === "video"
                                          && mediaRoot.mediaIsGifLike
                                          && mediaRoot.inlineGifPlayback
    readonly property string previewPathLower: (mediaPreviewUrl || "").toLowerCase().split("?")[0]
    readonly property bool linkPreviewIsImage: previewPathLower.endsWith(".png")
                                               || previewPathLower.endsWith(".jpg")
                                               || previewPathLower.endsWith(".jpeg")
                                               || previewPathLower.endsWith(".gif")
                                               || previewPathLower.endsWith(".webp")
                                               || previewPathLower.endsWith(".bmp")
    readonly property real fittedWidth: {
        if (mediaWidth <= 0 || mediaHeight <= 0)
            return maxMediaWidth
        var width = Math.min(mediaWidth, maxMediaWidth)
        var height = width / aspectRatio
        if (height > maxMediaHeight) {
            height = maxMediaHeight
            width = height * aspectRatio
        }
        return Math.max(units.gu(12), width)
    }
    readonly property real fittedHeight: {
        if (mediaWidth <= 0 || mediaHeight <= 0)
            return units.gu(18)
        var height = fittedWidth / aspectRatio
        return Math.max(units.gu(10), Math.min(maxMediaHeight, height))
    }

    width: fittedWidth
    height: column.height

    Column {
        id: column
        width: mediaRoot.width
        spacing: units.gu(0.6)

        Item {
            id: mediaBox
            width: parent.width
            height: mediaRoot.fittedHeight
            visible: mediaRoot.messageType === "image" || mediaRoot.messageType === "video"

            Rectangle {
                anchors.fill: parent
                radius: units.gu(0.8)
                color: theme.palette.normal.base
            }

            Image {
                anchors.fill: parent
                anchors.margins: units.dp(1)
                source: mediaRoot.messageType === "image" && mediaRoot.mediaContentType !== "image/gif" && !mediaRoot.mediaUrl.toLowerCase().split('?')[0].endsWith(".gif") ? mediaRoot.mediaPreviewUrl : ""
                fillMode: Image.PreserveAspectFit
                asynchronous: true
                cache: true
                visible: mediaRoot.messageType === "image" && mediaRoot.mediaContentType !== "image/gif" && !mediaRoot.mediaUrl.toLowerCase().split('?')[0].endsWith(".gif")
            }

            AnimatedImage {
                anchors.fill: parent
                anchors.margins: units.dp(1)
                source: mediaRoot.messageType === "image" && (mediaRoot.mediaContentType === "image/gif" || mediaRoot.mediaUrl.toLowerCase().split('?')[0].endsWith(".gif")) ? mediaRoot.mediaPreviewUrl : ""
                fillMode: Image.PreserveAspectFit
                asynchronous: true
                cache: true
                visible: mediaRoot.messageType === "image" && (mediaRoot.mediaContentType === "image/gif" || mediaRoot.mediaUrl.toLowerCase().split('?')[0].endsWith(".gif"))
                playing: visible
            }

            Rectangle {
                anchors.fill: parent
                anchors.margins: units.dp(1)
                radius: units.gu(0.8)
                color: theme.palette.normal.background
                visible: mediaRoot.messageType === "video" && !mediaRoot.inlineGifMode
            }

            Column {
                anchors.fill: parent
                anchors.margins: units.gu(1)
                spacing: units.gu(1)
                visible: mediaRoot.messageType === "video" && !mediaRoot.inlineGifMode

                Icon {
                    anchors.horizontalCenter: parent.horizontalCenter
                    width: units.gu(4)
                    height: width
                    name: "media-playback-start"
                    color: theme.palette.normal.focus
                }

                Label {
                    width: parent.width
                    horizontalAlignment: Text.AlignHCenter
                    text: mediaRoot.mediaFileName !== "" ? mediaRoot.mediaFileName : i18n.tr("Video attachment")
                    elide: Text.ElideRight
                    font.bold: true
                }

                Label {
                    width: parent.width
                    horizontalAlignment: Text.AlignHCenter
                    text: i18n.tr("Tap to play video")
                    wrapMode: Text.WordWrap
                    color: theme.palette.normal.backgroundSecondaryText
                    font.pixelSize: units.gu(1.2)
                }
            }

            Loader {
                anchors.fill: parent
                active: mediaRoot.inlineGifMode
                sourceComponent: Component {
                    Item {
                        Rectangle {
                            anchors.fill: parent
                            anchors.margins: units.dp(1)
                            radius: units.gu(0.8)
                            color: theme.palette.normal.background
                        }

                        MediaPlayer {
                            id: inlineGifPlayer
                            autoPlay: true
                            muted: true
                            loops: MediaPlayer.Infinite
                            source: mediaRoot.mediaUrl
                        }

                        VideoOutput {
                            anchors.fill: parent
                            anchors.margins: units.dp(1)
                            source: inlineGifPlayer
                            fillMode: VideoOutput.PreserveAspectFit
                        }

                        Component.onDestruction: inlineGifPlayer.stop()
                    }
                }
            }

            MouseArea {
                anchors.fill: parent
                onClicked: mediaRoot.mediaClicked(mediaRoot.mediaUrl, mediaRoot.messageType)
            }
        }

        Rectangle {
            width: parent.width
            height: mediaRoot.fittedHeight
            radius: units.gu(0.8)
            color: theme.palette.normal.base
            visible: mediaRoot.messageType === "link"

            Image {
                anchors.fill: parent
                anchors.margins: units.dp(1)
                source: mediaRoot.linkPreviewIsImage ? mediaRoot.mediaPreviewUrl : ""
                fillMode: Image.PreserveAspectCrop
                asynchronous: true
                cache: true
                opacity: 0.8
                visible: mediaRoot.linkPreviewIsImage
            }

            Rectangle {
                anchors.fill: parent
                color: "black"
                opacity: 0.3
                radius: units.gu(0.8)
            }

            Column {
                anchors.centerIn: parent
                spacing: units.gu(1)
                width: parent.width - units.gu(2)

                Icon {
                    name: "external-link"
                    width: units.gu(4)
                    height: width
                    color: "white"
                    anchors.horizontalCenter: parent.horizontalCenter
                }

                Label {
                    width: parent.width
                    text: mediaRoot.mediaFileName
                    color: "white"
                    font.bold: true
                    horizontalAlignment: Text.AlignHCenter
                    elide: Text.ElideRight
                }

                Label {
                    width: parent.width
                    text: i18n.tr("Open in browser")
                    color: "white"
                    font.pixelSize: units.gu(1.2)
                    horizontalAlignment: Text.AlignHCenter
                }
            }

            MouseArea {
                anchors.fill: parent
                onClicked: Qt.openUrlExternally(mediaRoot.mediaUrl)
            }
        }

        Rectangle {
            width: parent.width
            height: units.gu(7)
            radius: units.gu(0.8)
            color: theme.palette.normal.base
            visible: mediaRoot.messageType === "file" || mediaRoot.messageType === "audio"

            Row {
                anchors.fill: parent
                anchors.margins: units.gu(1)
                spacing: units.gu(1)

                Icon {
                    width: units.gu(3)
                    height: width
                    anchors.verticalCenter: parent.verticalCenter
                    name: mediaRoot.messageType === "audio" ? "audio-speakers" : "document-open"
                    color: theme.palette.normal.backgroundSecondaryText
                }

                Column {
                    width: parent.width - units.gu(5)
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: units.dp(2)

                    Label {
                        width: parent.width
                        text: mediaRoot.mediaFileName !== ""
                              ? mediaRoot.mediaFileName
                              : (mediaRoot.messageType === "audio" ? i18n.tr("Audio attachment") : i18n.tr("Attachment"))
                        elide: Text.ElideRight
                        font.bold: true
                    }

                    Label {
                        width: parent.width
                        text: mediaRoot.mediaUrl
                        elide: Text.ElideRight
                        color: theme.palette.normal.backgroundSecondaryText
                        font.pixelSize: units.gu(1.2)
                    }
                }
            }

            MouseArea {
                anchors.fill: parent
                onClicked: mediaRoot.mediaClicked(mediaRoot.mediaUrl, mediaRoot.messageType)
            }
        }

        Label {
            width: parent.width
            text: mediaRoot.body
            wrapMode: Text.WordWrap
            font.pixelSize: units.gu(1.6)
            lineHeight: 1.3
            visible: mediaRoot.body !== ""
        }
    }
}
