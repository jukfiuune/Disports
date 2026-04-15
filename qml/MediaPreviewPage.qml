import QtQuick 2.7
import QtMultimedia 5.0
import Lomiri.Components 1.3

Page {
    id: previewPage
    title: i18n.tr("Media Preview")
    
    // Properties filled by page caller
    property string mediaUrl: ""
    property string mediaType: "" // "image" or "video"

    header: PageHeader {
        title: previewPage.title
        trailingActionBar.actions: [
            Action {
                iconName: "external-link"
                text: i18n.tr("Open Externally")
                onTriggered: Qt.openUrlExternally(previewPage.mediaUrl)
            }
        ]
    }

    Rectangle {
        anchors.fill: parent
        color: "black"

        function zoomIn(centerX, centerY, factor) {
            flickable.scaleCenterX = centerX / (flickable.sizeScale * flickable.width);
            flickable.scaleCenterY = centerY / (flickable.sizeScale * flickable.height);
            flickable.sizeScale = factor;
        }

        function zoomOut() {
            if (flickable.sizeScale != 1.0) {
                flickable.scaleCenterX = flickable.contentX / flickable.width / (flickable.sizeScale - 1);
                flickable.scaleCenterY = flickable.contentY / flickable.height / (flickable.sizeScale - 1);
                flickable.sizeScale = 1.0;
            }
        }

        // Image viewer
        PinchArea {
            id: pinchArea
            anchors.fill: parent
            visible: previewPage.mediaType === "image"

            property real initialZoom: 1.0
            property real minimumZoom: 1.0
            property real maximumZoom: 4.0
            property var center

            onPinchStarted: {
                initialZoom = flickable.sizeScale
                center = pinchArea.mapToItem(mediaContainer, pinch.startCenter.x, pinch.startCenter.y);
                zoomIn(center.x, center.y, initialZoom);
            }

            onPinchUpdated: {
                var zoomFactor = initialZoom * pinch.scale
                if (zoomFactor < minimumZoom) zoomFactor = minimumZoom
                if (zoomFactor > maximumZoom) zoomFactor = maximumZoom
                
                if(zoomFactor > flickable.sizeScale + 0.1 || zoomFactor < flickable.sizeScale - 0.1) {
                    flickable.sizeScale = zoomFactor;
                }
            }

            Flickable {
                id: flickable
                anchors.fill: parent
                contentWidth: mediaContainer.width
                contentHeight: mediaContainer.height
                contentX: (sizeScale - 1) * scaleCenterX * width
                contentY: (sizeScale - 1) * scaleCenterY * height
                interactive: sizeScale > 1.0

                property real sizeScale: 1.0
                property real scaleCenterX: 0.0
                property real scaleCenterY: 0.0

                Behavior on sizeScale { LomiriNumberAnimation { duration: LomiriAnimation.FastDuration } }
                Behavior on scaleCenterX { LomiriNumberAnimation { duration: LomiriAnimation.FastDuration } }
                Behavior on scaleCenterY { LomiriNumberAnimation { duration: LomiriAnimation.FastDuration } }

                Item {
                    id: mediaContainer
                    width: flickable.width * flickable.sizeScale
                    height: flickable.height * flickable.sizeScale

                    Image {
                        id: image
                        anchors.fill: parent
                        source: previewPage.mediaType === "image" && !previewPage.mediaUrl.toLowerCase().split('?')[0].endsWith(".gif") ? previewPage.mediaUrl : ""
                        fillMode: Image.PreserveAspectFit
                        asynchronous: true
                        visible: !previewPage.mediaUrl.toLowerCase().split('?')[0].endsWith(".gif")
                    }

                    AnimatedImage {
                        id: animatedImage
                        anchors.fill: parent
                        source: previewPage.mediaType === "image" && previewPage.mediaUrl.toLowerCase().split('?')[0].endsWith(".gif") ? previewPage.mediaUrl : ""
                        fillMode: Image.PreserveAspectFit
                        asynchronous: true
                        visible: previewPage.mediaUrl.toLowerCase().split('?')[0].endsWith(".gif")
                        playing: visible
                    }
                }
            }

            MouseArea {
                anchors.fill: parent
                onDoubleClicked: {
                    if (flickable.sizeScale < maximumZoom) {
                        zoomIn(mouse.x, mouse.y, maximumZoom);
                    } else {
                        zoomOut();
                    }
                }
            }
        }

        // Video viewer
        Item {
            anchors.fill: parent
            visible: previewPage.mediaType === "video"



            MediaPlayer {
                id: videoPlayer
                source: previewPage.mediaType === "video" ? previewPage.mediaUrl : ""
                property bool isPlaying: playbackState === MediaPlayer.PlayingState
            }

            VideoOutput {
                id: videoOutput
                anchors.fill: parent
                source: videoPlayer
            }

            MouseArea {
                anchors.fill: parent
                onClicked: {
                    if (videoPlayer.isPlaying) {
                        videoPlayer.pause()
                    } else {
                        videoPlayer.play()
                    }
                }
            }

            Icon {
                id: playIcon
                width: units.gu(5)
                height: units.gu(5)
                anchors.centerIn: parent
                name: "media-playback-start"
                color: theme.palette.selected.backgroundText
                visible: !videoPlayer.isPlaying
                opacity: 0.8
            }

            ProgressBar {
                anchors {
                    left: parent.left
                    right: parent.right
                    bottom: parent.bottom
                    margins: units.gu(1)
                }
                value: videoPlayer.duration > 0 ? (videoPlayer.position / videoPlayer.duration) : 0
                visible: videoPlayer.isPlaying || videoPlayer.duration > 0
            }
        }
    }

    Component.onDestruction: {
        if (videoPlayer) {
            videoPlayer.stop()
        }
    }
}
