/*
 * SidebarIcon.qml
 *
 * One tappable slot in the Sidebar. Three display modes, checked in order:
 *   1. imageSource is set  →  show the image (server has a custom icon)
 *   2. iconName is set     →  show a Suru system icon (e.g. the DM button)
 *   3. fallback            →  show the two-letter abbr label
 *
 * Properties:
 *   imageSource  url     Path or URL to a server icon image. Can be a local
 *                        file:// path (downloaded to app's data dir by Python)
 *                        or an https:// URL if networking is allowed.
 *   iconName     string  Suru icon name, e.g. "contact". Used for DM button.
 *   label        string  Two-letter abbreviation shown when no image/icon.
 */

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

    ShaderEffectSource {
        id: effectSource
        anchors.centerIn: parent
        width: 0
        height: 0
        sourceItem: imageContent
    }

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
            onStatusChanged: if (status === Image.Error) source = ""
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
