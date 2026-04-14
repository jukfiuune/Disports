/*
 * DmPanel.qml
 *
 * Discord-like DM list with a fixed header and a single mixed conversation list.
 * The channel model has:
 * { channelId, name, unread, itemType, status, iconName }
 *
 * Signal:
 *   channelOpened(string channelId, string name)
 */

import QtQuick 2.7
import Lomiri.Components 1.3

Item {
    id: dmPanel

    property alias channels: channelList.model

    signal channelOpened(string channelId, string name)

    PanelHeader {
        id: dmHeader
        anchors {
            top: parent.top
            left: parent.left
            right: parent.right
        }
        title: i18n.tr("Direct Messages")
    }

    ListView {
        id: channelList
        anchors {
            top: dmHeader.bottom
            left: parent.left
            right: parent.right
            bottom: parent.bottom
        }
        clip: true

        delegate: ListItem {
            width: channelList.width
            height: units.gu(5.5)

            Row {
                anchors {
                    left: parent.left
                    right: parent.right
                    leftMargin: units.gu(2)
                    rightMargin: units.gu(2)
                    verticalCenter: parent.verticalCenter
                }
                spacing: units.gu(1.25)

                StatusDot {
                    status: model.status || "offline"
                    visible: (model.itemType || "contact") === "contact"
                    anchors.verticalCenter: parent.verticalCenter
                }

                Icon {
                    name: model.iconName || "contact-group"
                    width: units.gu(2)
                    height: width
                    visible: (model.itemType || "contact") !== "contact"
                    color: theme.palette.normal.backgroundSecondaryText
                    anchors.verticalCenter: parent.verticalCenter
                }

                Label {
                    text: model.name || ""
                    font.pixelSize: units.gu(1.7)
                    elide: Text.ElideRight
                    width: parent.width - units.gu(8)
                    anchors.verticalCenter: parent.verticalCenter
                }

                UnreadBadge {
                    count: model.unread || 0
                    anchors.verticalCenter: parent.verticalCenter
                }
            }

            onClicked: dmPanel.channelOpened(model.channelId, model.name)
        }
    }
}
