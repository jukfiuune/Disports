import QtQuick 2.7
import QtGraphicalEffects 1.0
import Lomiri.Components 1.3

Item {
    id: iconItem
    width:  units.gu(5)
    height: units.gu(5)

    property url    imageSource: ""
    property string iconName:    ""
    property string label:       ""
    property bool   showTileBackground: false

    // Re-render the FBO when any visible property changes.
    // Using callLater to coalesce rapid successive changes (e.g. image load sequence).
    onImageSourceChanged:     Qt.callLater(function() { effectSource.scheduleUpdate() })
    onIconNameChanged:        Qt.callLater(function() { effectSource.scheduleUpdate() })
    onLabelChanged:           Qt.callLater(function() { effectSource.scheduleUpdate() })
    onShowTileBackgroundChanged: Qt.callLater(function() { effectSource.scheduleUpdate() })

    ShaderEffectSource {
        id: effectSource
        anchors.centerIn: parent
        width: 0
        height: 0
        sourceItem: imageContent
        // Don't re-render the FBO every frame — only when content actually changes.
        // This eliminates N × (FBO render + DropShadow blur) per frame for static icons.
        live: false
    }

    Component.onCompleted: effectSource.scheduleUpdate()

    Item {
        id: imageContent
        anchors.fill: parent
        visible: false

        Rectangle {
            id: tileBackground
            anchors.fill: parent
            color: iconItem.showTileBackground || (iconItem.imageSource == "" && iconItem.label !== "")
                   ? theme.palette.highlighted.base
                   : "transparent"
        }

        // 1. Custom server image
        Image {
            anchors.fill: parent
            source: iconItem.imageSource
            fillMode: Image.PreserveAspectCrop
            visible: iconItem.imageSource != ""
            asynchronous: true
            // Re-render FBO when image finishes loading (or fails)
            onStatusChanged: {
                if (status === Image.Ready || status === Image.Error)
                    effectSource.scheduleUpdate()
            }
            onSourceChanged: effectSource.scheduleUpdate()
        }

        // 2. Suru system icon (used for DM button)
        Icon {
            anchors.centerIn: parent
            width:  units.gu(2.5)
            height: units.gu(2.5)
            name: iconItem.iconName
            visible: iconItem.imageSource == "" && iconItem.iconName !== ""
            color: iconItem.showTileBackground ? "white" : theme.palette.normal.backgroundText
        }

        // 3. Abbreviation text fallback
        Label {
            anchors.centerIn: parent
            text: iconItem.label
            font.pixelSize: units.gu(1.6)
            font.bold: true
            visible: iconItem.imageSource == "" && iconItem.iconName === ""
            color: "white"
        }
    }

    Shape {
        id: imgShape
        image: effectSource
        anchors.fill: parent
        aspect: LomiriShape.DropShadow
        radius: width > units.gu(3) ? "medium" : "small"
    }
}
