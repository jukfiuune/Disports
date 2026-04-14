/*
 * Sidebar.qml
 *
 * Narrow vertical rail on the left of the main page.
 *
 *  ┌────────┐
 *  │  DMs   │  ← pinned, always visible
 *  ├────────┤
 *  │  UT   │
 *  │  PY   │  ← scrollable ListView; folders (collapsible) + servers
 *  │  LM   │
 *  │  ...  │
 *  └────────┘
 *
 * Signals:
 *   dmSelected()
 *   serverSelected(string id, string name)
 */

import QtQuick 2.7
import Lomiri.Components 1.3

Item {
    id: sidebar
    width: units.gu(7)

    property alias servers: serverList.model
    property string activeMode: "dm"
    property string activeServerId: ""
    property int dmUnreadCount: 0

    // folderKey -> expanded (true) / collapsed (false or missing)
    property var folderExpanded: ({})

    signal dmSelected()
    signal serverSelected(string id, string name)

    function isFolderOpen(key) {
        if (!key || key === "")
            return true
        return sidebar.folderExpanded[key] === true
    }

    function toggleFolder(key) {
        if (!key || key === "")
            return
        var o = {}
        var k
        for (k in sidebar.folderExpanded)
            o[k] = sidebar.folderExpanded[k]
        o[key] = !sidebar.isFolderOpen(key)
        sidebar.folderExpanded = o
    }

    // Thin right border
    Rectangle {
        anchors { top: parent.top; bottom: parent.bottom; right: parent.right }
        width: units.dp(1)
        color: theme.palette.normal.base
    }

    // ── DM button + divider — pinned to top, never scrolls ───────────────
    Column {
        id: topSection
        anchors {
            top: parent.top
            left: parent.left
            right: parent.right
            topMargin: units.gu(1)
        }
        spacing: units.gu(0.5)

        Item {
            width: parent.width
            height: sidebar.width

            Rectangle {
                anchors.fill: parent
                color: dmMouse.pressed || sidebar.activeMode === "dm"
                       ? theme.palette.highlighted.base
                       : "transparent"
            }

            SidebarIcon {
                anchors.centerIn: parent
                iconName: "contact"
                label: i18n.tr("DMs")
                showTileBackground: true
            }

            UnreadBadge {
                count: sidebar.dmUnreadCount
                anchors {
                    bottom: parent.bottom
                    right: parent.right
                    bottomMargin: units.gu(0.5)
                    rightMargin: units.gu(0.5)
                }
            }

            MouseArea {
                id: dmMouse
                anchors.fill: parent
                onClicked: sidebar.dmSelected()
            }
        }

        Rectangle {
            width: units.gu(4)
            height: units.dp(1)
            anchors.horizontalCenter: parent.horizontalCenter
            color: theme.palette.normal.base
            visible: true
        }
    }

    // ── Server icons — scrollable ListView ───────────────────────────────
    ListView {
        id: serverList
        anchors {
            top: topSection.bottom
            bottom: parent.bottom
            left: parent.left
            right: parent.right
            topMargin: units.gu(1)
        }
        spacing: 0
        clip: true

        delegate: Item {
            id: del
            width: serverList.width
            readonly property bool isFH: model.itemType === "folderHeader"
            readonly property bool isSrv: model.itemType === "server"
            readonly property string fk: model.folderKey || ""
            readonly property bool srvInFolder: isSrv && fk !== ""
            readonly property bool srvVisible: isSrv && (!srvInFolder || sidebar.isFolderOpen(fk))
            // PyOtherSide cannot pass nested lists through ListModel roles.
            // Python sends these as newline-delimited strings; split here.
            readonly property var previewUrls: {
                var s = model.previewIconUrls || ""
                return s !== "" ? s.split("\n") : []
            }
            readonly property var previewAbbrs: {
                var s = model.previewAbbrs || ""
                return s !== "" ? s.split("\n") : []
            }
            readonly property int previewN: {
                var n = Math.min(4, Math.max(previewUrls.length, previewAbbrs.length))
                return (n > 0) ? n : 0
            }


            height: {
                if (isFH) {
                    if (sidebar.isFolderOpen(model.folderKey))
                        return units.gu(2.2)
                    return sidebar.width
                }
                if (isSrv && !srvVisible)
                    return 0
                return sidebar.width
            }
            visible: height > 0

            readonly property bool hasFolderColor: (model.folderColorHex && String(model.folderColorHex).length > 1)

            // ── Folder header (collapsed = 2×2 preview; expanded = thin title bar) ──
            Item {
                anchors.fill: parent
                visible: isFH

                Rectangle {
                    id: fhStripe
                    width: units.dp(3)
                    anchors.left: parent.left
                    anchors.top: parent.top
                    anchors.bottom: parent.bottom
                    color: del.hasFolderColor ? model.folderColorHex : theme.palette.normal.base
                    opacity: del.hasFolderColor ? 1 : 0.4
                }

                MouseArea {
                    anchors.fill: parent
                    onClicked: sidebar.toggleFolder(model.folderKey)
                }

                // Collapsed: up to four small server previews
                Item {
                    anchors.fill: parent
                    anchors.leftMargin: fhStripe.width
                    visible: isFH && !sidebar.isFolderOpen(model.folderKey)

                    Grid {
                        id: previewGrid
                        anchors.centerIn: parent
                        width: Math.min(parent.width, parent.height) - units.gu(0.5)
                        height: width
                        spacing: units.dp(2)
                        columns: 2

                        Repeater {
                            model: del.previewN
                            delegate: Item {
                                width: (previewGrid.width - previewGrid.spacing) / 2
                                height: (previewGrid.height - previewGrid.spacing) / 2
                                SidebarIcon {
                                    anchors.centerIn: parent
                                    width: Math.min(parent.width, parent.height) * 0.9
                                    height: width
                                    imageSource: (index < del.previewUrls.length) ? (del.previewUrls[index] || "") : ""
                                    label: (index < del.previewAbbrs.length) ? (del.previewAbbrs[index] || "") : ""
                                }
                            }
                        }
                    }

                    UnreadBadge {
                        count: model.folderUnread || 0
                        anchors {
                            bottom: parent.bottom
                            right: parent.right
                            bottomMargin: units.gu(0.25)
                            rightMargin: units.gu(0.25)
                        }
                    }
                }

                // Expanded: compact bar (stripe + title); servers below keep their own stripes
                Rectangle {
                    anchors.fill: parent
                    anchors.leftMargin: fhStripe.width
                    visible: isFH && sidebar.isFolderOpen(model.folderKey)
                    color: theme.palette.normal.base
                    opacity: 0.35

                    Label {
                        anchors {
                            left: parent.left
                            right: chevron.left
                            verticalCenter: parent.verticalCenter
                            leftMargin: units.gu(0.25)
                            rightMargin: units.gu(0.25)
                        }
                        text: model.folderName || ""
                        font.pixelSize: units.gu(1.05)
                        font.bold: true
                        elide: Text.ElideRight
                        horizontalAlignment: Text.AlignHCenter
                        color: theme.palette.normal.backgroundSecondaryText
                    }

                    Icon {
                        id: chevron
                        anchors {
                            right: parent.right
                            verticalCenter: parent.verticalCenter
                            rightMargin: units.gu(0.25)
                        }
                        width: units.gu(1.6)
                        height: width
                        name: "go-up"
                        color: theme.palette.normal.backgroundSecondaryText
                    }
                }
            }

            // ── Server row (full icon; colored rail when inside a folder) ──
            Item {
                id: serverRow
                anchors.fill: parent
                visible: isSrv && srvVisible

                readonly property bool selected: sidebar.activeMode === "server" && model.serverId === sidebar.activeServerId

                Rectangle {
                    id: srvStripe
                    width: srvInFolder ? units.dp(3) : 0
                    anchors.left: parent.left
                    anchors.top: parent.top
                    anchors.bottom: parent.bottom
                    color: del.hasFolderColor ? model.folderColorHex : theme.palette.normal.base
                    opacity: del.hasFolderColor ? 1 : 0.4
                    visible: srvInFolder
                }

                Rectangle {
                    anchors.fill: parent
                    anchors.leftMargin: srvInFolder ? srvStripe.width : 0
                    color: theme.palette.highlighted.base
                    visible: serverMouse.pressed || serverRow.selected
                }

                Item {
                    anchors.fill: parent
                    anchors.leftMargin: srvInFolder ? srvStripe.width : 0
                    SidebarIcon {
                        anchors.centerIn: parent
                        width: units.gu(5)
                        height: width
                        label: model.abbr
                        imageSource: model.iconUrl || ""
                    }
                }

                UnreadBadge {
                    count: model.unread || 0
                    anchors {
                        bottom: parent.bottom
                        right: parent.right
                        bottomMargin: units.gu(0.5)
                        rightMargin: units.gu(0.5)
                    }
                }

                MouseArea {
                    id: serverMouse
                    anchors.fill: parent
                    onClicked: {
                        if (model.serverId && model.serverId !== "")
                            sidebar.serverSelected(model.serverId, model.name)
                    }
                }
            }
        }

        Rectangle {
            anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
            height: units.gu(3)
            visible: serverList.contentHeight > serverList.height
            gradient: Gradient {
                GradientStop { position: 0.0; color: "transparent" }
                GradientStop { position: 1.0; color: theme.palette.normal.background }
            }
        }
    }
}
