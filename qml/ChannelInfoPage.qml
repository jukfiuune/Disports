import QtQuick 2.7
import Lomiri.Components 1.3
import "./"

Page {
    id: infoPage
    property var stack
    property var python
    property string channelId: ""
    property string fallbackName: ""
    property var details: ({})
    property bool loading: true
    property bool cached: false
    property string errorText: ""

    readonly property string kind: details.kind || "channel"

    function loadDetails() {
        if (!python || channelId === "") {
            loading = false
            errorText = i18n.tr("Channel information is unavailable.")
            return
        }
        python.call("discord_client.channel_info", [channelId], function(result) {
            loading = false
            if (!result || !result.ok || !result.info) {
                errorText = result && result.error
                            ? result.error
                            : i18n.tr("Channel information is unavailable.")
                return
            }
            details = result.info
            cached = !!result.cached
        })
    }

    header: PageHeader {
        title: infoPage.kind === "user"
               ? i18n.tr("User info")
               : (infoPage.kind === "group" ? i18n.tr("Group info") : i18n.tr("Channel info"))
        leadingActionBar.actions: [
            Action {
                iconName: "back"
                text: i18n.tr("Back")
                onTriggered: infoPage.stack.pop()
            }
        ]
    }

    Flickable {
        anchors { top: infoPage.header.bottom; left: parent.left; right: parent.right; bottom: parent.bottom }
        contentWidth: width
        contentHeight: contentColumn.height + units.gu(4)
        clip: true

        Column {
            id: contentColumn
            anchors { top: parent.top; left: parent.left; right: parent.right; margins: units.gu(2) }
            spacing: units.gu(1.5)

            ActivityIndicator {
                anchors.horizontalCenter: parent.horizontalCenter
                running: infoPage.loading
                visible: running
            }

            Label {
                width: parent.width
                visible: infoPage.errorText !== ""
                text: infoPage.errorText
                color: theme.palette.normal.negative
                wrapMode: Text.WordWrap
                horizontalAlignment: Text.AlignHCenter
            }

            Item {
                width: parent.width
                height: units.gu(10)
                visible: !infoPage.loading && infoPage.errorText === ""

                Rectangle {
                    anchors.centerIn: parent
                    width: units.gu(9)
                    height: width
                    radius: width / 2
                    color: theme.palette.normal.base
                    clip: true

                    Image {
                        id: avatarImage
                        anchors.fill: parent
                        source: infoPage.details.iconUrl || ""
                        fillMode: Image.PreserveAspectCrop
                        asynchronous: true
                        visible: source !== ""
                    }
                    Icon {
                        anchors.centerIn: parent
                        width: units.gu(4.5)
                        height: width
                        name: infoPage.kind === "user" ? "contact" : (infoPage.kind === "group" ? "contact-group" : "message")
                        color: theme.palette.normal.backgroundSecondaryText
                        visible: !avatarImage.visible
                    }
                }
            }

            Label {
                width: parent.width
                visible: !infoPage.loading && infoPage.errorText === ""
                text: infoPage.details.name || infoPage.fallbackName
                font.pixelSize: units.gu(2.2)
                font.bold: true
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
            }

            Label {
                width: parent.width
                visible: infoPage.cached
                text: i18n.tr("Showing saved information")
                color: theme.palette.normal.backgroundSecondaryText
                horizontalAlignment: Text.AlignHCenter
            }

            Label {
                width: parent.width
                visible: infoPage.kind === "user" && !infoPage.loading
                text: infoPage.details.blocked
                      ? i18n.tr("Blocked user")
                      : i18n.tr("Status: %1").arg(infoPage.details.status || i18n.tr("offline"))
                color: theme.palette.normal.backgroundSecondaryText
                horizontalAlignment: Text.AlignHCenter
            }

            Label {
                width: parent.width
                visible: infoPage.kind === "channel" && (infoPage.details.guildName || "") !== ""
                text: i18n.tr("Server: %1").arg(infoPage.details.guildName)
                wrapMode: Text.WordWrap
            }
            Label {
                width: parent.width
                visible: infoPage.kind === "channel" && (infoPage.details.category || "") !== ""
                text: i18n.tr("Category: %1").arg(infoPage.details.category)
                wrapMode: Text.WordWrap
            }
            Label {
                width: parent.width
                visible: infoPage.kind === "channel"
                text: i18n.tr("Type: %1").arg(String(infoPage.details.channelType || "unknown").replace(/_/g, " "))
                wrapMode: Text.WordWrap
            }
            Label {
                width: parent.width
                visible: infoPage.kind === "channel" && (infoPage.details.topic || "") !== ""
                text: infoPage.details.topic || ""
                wrapMode: Text.WordWrap
            }
            Label {
                width: parent.width
                visible: infoPage.kind === "channel" && !!infoPage.details.nsfw
                text: i18n.tr("Age-restricted channel")
                color: theme.palette.normal.negative
            }

            Label {
                visible: infoPage.kind === "group" && (infoPage.details.members || []).length > 0
                text: i18n.tr("Members (%1)").arg((infoPage.details.members || []).length)
                font.bold: true
                font.pixelSize: units.gu(1.8)
            }

            Repeater {
                model: infoPage.kind === "group" ? (infoPage.details.members || []) : []
                delegate: ListItem {
                    width: contentColumn.width
                    height: units.gu(6)
                    divider.visible: index < (infoPage.details.members || []).length - 1

                    Row {
                        anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter }
                        spacing: units.gu(1)
                        StatusDot {
                            status: modelData.status || "offline"
                            anchors.verticalCenter: parent.verticalCenter
                        }
                        Label {
                            width: parent.width - units.gu(4)
                            text: modelData.name || i18n.tr("Unknown user")
                            font.strikeout: !!modelData.blocked
                            elide: Text.ElideRight
                            anchors.verticalCenter: parent.verticalCenter
                        }
                    }
                }
            }

            Label {
                width: parent.width
                visible: !infoPage.loading && infoPage.channelId !== ""
                text: i18n.tr("ID: %1").arg(infoPage.kind === "user"
                                                  ? (infoPage.details.userId || infoPage.channelId)
                                                  : infoPage.channelId)
                color: theme.palette.normal.backgroundSecondaryText
                font.pixelSize: units.gu(1.2)
                wrapMode: Text.WrapAnywhere
            }
        }
    }

    Component.onCompleted: loadDetails()
}
