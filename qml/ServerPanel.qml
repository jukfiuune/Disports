import QtQuick 2.7
import Lomiri.Components 1.3

Item {
    id: serverPanel

    property string serverName: ""
    property alias channels: channelList.model

    signal channelOpened(string channelId, string name)

    // Server name header
    // Sits above the channel list, styled like a sub-header inside the panel.
    PanelHeader {
        id: serverHeader
        anchors { top: parent.top; left: parent.left; right: parent.right }
        title: serverPanel.serverName
    }

    // Channel list, grouped by category
    // We use a plain ListView and detect category boundaries in the delegate.
    ListView {
        id: channelList
        anchors {
            top: serverHeader.bottom
            left: parent.left; right: parent.right; bottom: parent.bottom
        }
        clip: true

        // Show a category label whenever this row's category differs from
        // the previous row's category.
        delegate: Column {
            width: channelList.width

            // Category header (only rendered when it changes)
            SectionHeader {
                text: model.category
                visible: {
                    if (index === 0 || !channelList.model)
                        return true
                    var previous = channelList.model.get(index - 1)
                    return !previous || previous.categoryId !== model.categoryId
                }
            }

            // Channel row
            ListItem {
                height: units.gu(5.5)
                width: parent.width
                enabled: model.openable !== false
                opacity: model.openable === false ? 0.72 : 1.0

                Row {
                    anchors {
                        left: parent.left; right: parent.right
                        leftMargin: units.gu(2) + units.gu(model.indentLevel || 0) * 1.5
                        rightMargin: units.gu(2)
                        verticalCenter: parent.verticalCenter
                    }
                    spacing: units.gu(0.75)

                    Icon {
                        width: units.gu(2)
                        height: width
                        name: model.channelIconName || ""
                        visible: model.channelIconName && model.channelIconName !== ""
                        color: theme.palette.normal.backgroundSecondaryText
                        anchors.verticalCenter: parent.verticalCenter
                    }

                    Label {
                        text: model.channelGlyph || "#"
                        font.pixelSize: units.gu(1.8)
                        font.bold: true
                        visible: !model.channelIconName || model.channelIconName === ""
                        color: theme.palette.normal.backgroundSecondaryText
                        anchors.verticalCenter: parent.verticalCenter
                    }

                    Label {
                        text: model.name
                        font.pixelSize: units.gu(1.7)
                        font.bold: (model.indentLevel || 0) > 0
                        elide: Text.ElideRight
                        width: parent.width - units.gu(10)
                        anchors.verticalCenter: parent.verticalCenter
                    }

                    UnreadBadge {
                        count: model.unread
                        kind: model.unreadKind || "none"
                        anchors.verticalCenter: parent.verticalCenter
                    }
                }

                onClicked: {
                    if (model.openable === false)
                        return
                    serverPanel.channelOpened(model.channelId, model.name)
                }
            }
        }
    }
}
