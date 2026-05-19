import QtQuick 2.7
import Lomiri.Components 1.3

Item {
    id: dmPanel

    property alias channels: channelList.model
    property var activeCall: null

    signal channelOpened(string channelId, string name)
    signal callRequested(string channelId, string name)

    function rowHasActiveCall(channelId) {
        if (!activeCall || !channelId)
            return false
        var participants = activeCall.participants || []
        return (activeCall.channelId || "") === channelId && participants.length > 0
    }

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
                    right: callBtn.visible ? callBtn.left : parent.right
                    leftMargin: units.gu(2)
                    rightMargin: units.gu(1)
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
                    width: parent.width - units.gu(6)
                    anchors.verticalCenter: parent.verticalCenter
                }

                UnreadBadge {
                    count: model.unread || 0
                    kind: model.unreadKind || ((model.unread || 0) > 0 ? "count" : "none")
                    anchors.verticalCenter: parent.verticalCenter
                }
            }

            LomiriShape {
                id: callBtn
                width: units.gu(4)
                height: units.gu(4)
                visible: dmPanel.rowHasActiveCall(model.channelId || "")
                radius: "medium"
                color: "transparent"
                anchors {
                    right: parent.right
                    rightMargin: units.gu(1.5)
                    verticalCenter: parent.verticalCenter
                }

                Icon {
                    anchors.centerIn: parent
                    width: units.gu(2.5)
                    height: units.gu(2.5)
                    name: "call-start"
                    color: theme.palette.normal.backgroundSecondaryText
                }

                MouseArea {
                    anchors.fill: parent
                    onClicked: dmPanel.callRequested(model.channelId, model.name || "")
                }
            }

            onClicked: dmPanel.channelOpened(model.channelId, model.name)
        }
    }
}
