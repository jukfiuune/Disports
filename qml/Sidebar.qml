/*
 * Sidebar.qml
 *
 * Single scrollable rail for:
 *   1. DM home button
 *   2. unread DM avatars/groups
 *   3. divider
 *   4. servers / folders
 */

import QtQuick 2.7
import Lomiri.Components 1.3

Item {
    id: sidebar
    width: units.gu(7)

    property var servers
    property var dmChannels
    property string activeMode: "dm"
    property string activeServerId: ""
    property string activeChannelId: ""
    property int dmUnreadCount: 0
    property int revision: 0
    property bool startupDone: false
    property int _savedHeaderHeight: 0

    // folderKey -> expanded (true) / collapsed (false or missing)
    property var folderExpanded: ({})
    property var unreadDmItems: []

    signal dmSelected()
    signal dmChannelSelected(string channelId, string name)
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

    function rebuildUnreadDmItems() {
        _savedHeaderHeight = railList.headerItem ? Math.round(railList.headerItem.height) : 0
        var items = []
        var i
        if (!dmChannels) {
            unreadDmItems = items
            return
        }
        for (i = 0; i < dmChannels.count; i++) {
            var row = dmChannels.get(i)
            var unread = Number(row.unread || 0)
            if (unread <= 0)
                continue
            items.push({
                "channelId": row.channelId || "",
                "name": row.name || "",
                "abbr": row.abbr || "",
                "iconUrl": row.iconUrl || "",
                "iconName": row.iconName || "",
                "unread": unread,
                "unreadKind": row.unreadKind || "count"
            })
        }
        unreadDmItems = items
    }

    onDmChannelsChanged: rebuildUnreadDmItems()
    onRevisionChanged: rebuildUnreadDmItems()
    onUnreadDmItemsChanged: {
        if (!startupDone) {
            Qt.callLater(function() { railList.contentY = 0 })
        } else if (railList.contentY > 0) {
            // Anchor the visible content by compensating for header height change
            var savedY = railList.contentY
            var savedH = _savedHeaderHeight
            Qt.callLater(function() {
                var newH = railList.headerItem ? Math.round(railList.headerItem.height) : 0
                railList.contentY = Math.max(0, savedY + (newH - savedH))
            })
        }
    }
    Component.onCompleted: {
        rebuildUnreadDmItems()
        Qt.callLater(function() {
            railList.contentY = 0
            startupDone = true
        })
    }

    Connections {
        target: sidebar.dmChannels
        function onCountChanged() { sidebar.rebuildUnreadDmItems() }
    }

    Rectangle {
        anchors { top: parent.top; bottom: parent.bottom; right: parent.right }
        width: units.dp(1)
        color: theme.palette.normal.base
    }

    ListView {
        id: railList
        anchors.fill: parent
        anchors.topMargin: units.gu(1)
        anchors.bottomMargin: units.gu(0.5)
        model: sidebar.servers
        spacing: 0
        clip: true
        cacheBuffer: units.gu(80)
        Component.onCompleted: Qt.callLater(function() { railList.contentY = 0 })
        onModelChanged: Qt.callLater(function() { railList.contentY = 0 })

        header: Column {
            width: railList.width
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

                MouseArea {
                    id: dmMouse
                    anchors.fill: parent
                    onClicked: sidebar.dmSelected()
                }
            }

            Repeater {
                model: sidebar.unreadDmItems

                delegate: Item {
                    width: railList.width
                    height: sidebar.width

                    readonly property bool selected: sidebar.activeMode === "dm"
                                                     && sidebar.activeChannelId === (modelData.channelId || "")

                    Rectangle {
                        anchors.fill: parent
                        color: dmEntryMouse.pressed || selected
                               ? theme.palette.highlighted.base
                               : "transparent"
                    }

                    SidebarIcon {
                        anchors.centerIn: parent
                        width: units.gu(5)
                        height: width
                        imageSource: modelData.iconUrl || ""
                        iconName: modelData.iconName || ""
                        label: modelData.abbr || ""
                    }

                    UnreadBadge {
                        count: modelData.unread || 0
                        kind: modelData.unreadKind || ((modelData.unread || 0) > 0 ? "count" : "none")
                        anchors {
                            bottom: parent.bottom
                            right: parent.right
                            bottomMargin: units.gu(0.5)
                            rightMargin: units.gu(0.5)
                        }
                    }

                    MouseArea {
                        id: dmEntryMouse
                        anchors.fill: parent
                        onClicked: sidebar.dmChannelSelected(modelData.channelId || "", modelData.name || "")
                    }
                }
            }

            Rectangle {
                width: units.gu(4)
                height: units.dp(1)
                anchors.horizontalCenter: parent.horizontalCenter
                color: theme.palette.normal.base
                visible: true
            }

            Item {
                width: parent.width
                height: units.gu(0.5)
            }
        }

        delegate: Item {
            id: del
            width: railList.width
            readonly property bool isFH: model.itemType === "folderHeader"
            readonly property bool isSrv: model.itemType === "server"
            readonly property string fk: model.folderKey || ""
            readonly property bool srvInFolder: isSrv && fk !== ""
            readonly property bool srvVisible: isSrv && (!srvInFolder || sidebar.isFolderOpen(fk))

            // Computed lazily to avoid recreating arrays on every binding re-eval
            property var previewUrls:  []
            property var previewAbbrs: []
            property int previewN:     0
            property bool hasFolderColor: false

            function _recompute() {
                var us = model.previewIconUrls || ""
                var ps = us !== "" ? us.split("\n") : []
                previewUrls = ps
                var as_ = model.previewAbbrs || ""
                var pa = as_ !== "" ? as_.split("\n") : []
                previewAbbrs = pa
                var n = Math.min(4, Math.max(ps.length, pa.length))
                previewN = n > 0 ? n : 0
                hasFolderColor = !!(model.folderColorHex && String(model.folderColorHex).length > 1)
            }
            Component.onCompleted: _recompute()
            // Watch model roles so _recompute fires when data changes (e.g. after icon download)
            property string watchUrls:  model.previewIconUrls || ""
            property string watchAbbrs: model.previewAbbrs    || ""
            property string watchColor: model.folderColorHex  || ""
            onWatchUrlsChanged:  _recompute()
            onWatchAbbrsChanged: _recompute()
            onWatchColorChanged: _recompute()

            height: {
                if (isFH) {
                    // Read folderExpanded directly for granular tracking
                    var open = sidebar.folderExpanded[model.folderKey]
                    return (open === true) ? units.gu(2.2) : sidebar.width
                }
                if (isSrv && !srvVisible)
                    return 0
                return sidebar.width
            }
            visible: height > 0

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

                                readonly property string previewUrl:  (index < del.previewUrls.length)  ? (del.previewUrls[index]  || "") : ""
                                readonly property string previewAbbr: (index < del.previewAbbrs.length) ? (del.previewAbbrs[index] || "") : ""

                                // Fast path: custom icon image (no shader effects)
                                Image {
                                    id: prevImg
                                    anchors.fill: parent
                                    source: parent.previewUrl
                                    fillMode: Image.PreserveAspectCrop
                                    visible: parent.previewUrl !== ""
                                    cache: true
                                    asynchronous: true
                                    clip: true
                                }

                                // Fallback: colored tile with initials
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

                    UnreadBadge {
                        count: model.folderUnread || 0
                        kind: model.folderUnreadKind || ((model.folderUnread || 0) > 0 ? "count" : "none")
                        anchors {
                            bottom: parent.bottom
                            right: parent.right
                            bottomMargin: units.gu(0.25)
                            rightMargin: units.gu(0.25)
                        }
                    }
                }

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
                    kind: model.unreadKind || ((model.unread || 0) > 0 ? "count" : "none")
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
            visible: railList.contentHeight > railList.height
            gradient: Gradient {
                GradientStop { position: 0.0; color: "transparent" }
                GradientStop { position: 1.0; color: theme.palette.normal.background }
            }
        }
    }
}
