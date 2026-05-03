import QtQuick 2.7
import Lomiri.Components 1.3

Item {
    id: folderPreview

    property var previewUrls: []
    property var previewAbbrs: []
    property int previewCount: 0

    function refresh() {
        previewSource.scheduleUpdate()
    }

    onPreviewUrlsChanged: Qt.callLater(refresh)
    onPreviewAbbrsChanged: Qt.callLater(refresh)
    onPreviewCountChanged: Qt.callLater(refresh)
    Component.onCompleted: previewSource.scheduleUpdate()

    ShaderEffectSource {
        id: previewSource
        anchors.centerIn: parent
        width: 0
        height: 0
        sourceItem: previewContent
        live: false
    }

    Item {
        id: previewContent
        anchors.fill: parent
        visible: false

        Rectangle {
            anchors.fill: parent
            color: theme.palette.normal.base
        }

        Grid {
            id: previewGrid
            anchors.fill: parent
            spacing: units.dp(2)
            columns: 2

            Repeater {
                model: folderPreview.previewCount
                delegate: Item {
                    width: (previewGrid.width - previewGrid.spacing) / 2
                    height: (previewGrid.height - previewGrid.spacing) / 2

                    readonly property string previewUrl: (index < folderPreview.previewUrls.length)
                                                         ? (folderPreview.previewUrls[index] || "")
                                                         : ""
                    readonly property string previewAbbr: (index < folderPreview.previewAbbrs.length)
                                                          ? (folderPreview.previewAbbrs[index] || "")
                                                          : ""

                    Image {
                        anchors.fill: parent
                        source: parent.previewUrl
                        fillMode: Image.PreserveAspectCrop
                        visible: parent.previewUrl !== ""
                        cache: true
                        asynchronous: true
                        clip: true
                        onStatusChanged: {
                            if (status === Image.Ready || status === Image.Error)
                                folderPreview.refresh()
                        }
                        onSourceChanged: folderPreview.refresh()
                    }

                    Rectangle {
                        anchors.fill: parent
                        color: theme.palette.highlighted.base
                        visible: parent.previewUrl === ""
                        Label {
                            anchors.centerIn: parent
                            text: parent.parent.previewAbbr
                            font.pixelSize: Math.round(parent.height * 0.45)
                            font.bold: true
                            color: "white"
                        }
                    }
                }
            }
        }
    }

    Shape {
        anchors.fill: parent
        image: previewSource
        aspect: LomiriShape.DropShadow
        radius: "medium"
    }
}
