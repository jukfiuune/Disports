import QtQuick 2.7
import QtQuick.Layouts 1.3
import Lomiri.Components 1.3
import "../"

Item {
    id: pickerRoot

    property string serverName: ""
    property string activeServerId: ""
    property url activeServerIcon: ""
    property var serverEmojis: []
    property var unicodeEmojis: []
    property string pickerMode: "unicode"
    property string unicodeCategory: "faces"
    property var displayItems: []
    readonly property bool allowServerEmojis: (activeServerId || "") !== ""
    readonly property var unicodeCategories: [
        { "key": "faces", "label": i18n.tr("Faces"), "icon": "😀" },
        { "key": "people", "label": i18n.tr("People"), "icon": "👋" },
        { "key": "nature", "label": i18n.tr("Nature"), "icon": "🌲" },
        { "key": "food", "label": i18n.tr("Food"), "icon": "🍕" },
        { "key": "activities", "label": i18n.tr("Activity"), "icon": "⚽" },
        { "key": "travel", "label": i18n.tr("Travel"), "icon": "✈️" },
        { "key": "objects", "label": i18n.tr("Objects"), "icon": "💡" },
        { "key": "symbols", "label": i18n.tr("Symbols"), "icon": "❤️" },
        { "key": "flags", "label": i18n.tr("Flags"), "icon": "🏁" }
    ]
    readonly property var modeLabels: allowServerEmojis
                                      ? [i18n.tr("Emoji"), i18n.tr("Server")]
                                      : [i18n.tr("Emoji")]
    signal emojiChosen(string text, var emojiData)

    function categoryIndexForKey(key) {
        for (var i = 0; i < unicodeCategories.length; i++) {
            if ((unicodeCategories[i].key || "") === key)
                return i
        }
        return 0
    }

    function setPickerMode(mode) {
        var desired = String(mode || "unicode")
        if (desired === "server" && !allowServerEmojis)
            desired = "unicode"
        pickerMode = desired
    }

    function rebuildDisplayItems() {
        if (pickerMode === "server") {
            displayItems = serverEmojis || []
            return
        }

        var source = unicodeEmojis || []
        var filtered = []
        for (var i = 0; i < source.length; i++) {
            var entry = source[i]
            if ((entry.category || "symbols") === unicodeCategory)
                filtered.push(entry)
        }
        displayItems = filtered
    }

    function chooseUnicode(entry) {
        emojiChosen(entry.char || "", {
            "kind": "unicode",
            "text": entry.char || "",
            "name": entry.name || "",
            "label": entry.label || "",
            "category": entry.category || ""
        })
    }

    function chooseCustom(entry) {
        emojiChosen(entry.code || "", {
            "kind": "custom",
            "text": entry.code || "",
            "name": entry.name || "",
            "emojiId": entry.emojiId || "",
            "animated": !!entry.animated,
            "guildId": activeServerId
        })
    }

    onPickerModeChanged: rebuildDisplayItems()
    onUnicodeCategoryChanged: rebuildDisplayItems()
    onUnicodeEmojisChanged: rebuildDisplayItems()
    onServerEmojisChanged: rebuildDisplayItems()
    onAllowServerEmojisChanged: {
        if (!allowServerEmojis && pickerMode === "server")
            pickerMode = "unicode"
    }

    Component.onCompleted: rebuildDisplayItems()

    RowLayout {
        anchors.fill: parent
        spacing: units.gu(1)

        // Sidebar
        Item {
            Layout.preferredWidth: units.gu(6)
            Layout.fillHeight: true

            Rectangle {
                anchors { right: parent.right; top: parent.top; bottom: parent.bottom }
                width: units.dp(1)
                color: theme.palette.normal.base
                opacity: 0.2
            }

            Flickable {
                anchors.fill: parent
                contentWidth: parent.width
                contentHeight: sidebarColumn.height
                clip: true

                Column {
                    id: sidebarColumn
                    width: parent.width
                    spacing: units.gu(0.5)

                    // Server Icon
                    Item {
                        width: parent.width
                        height: width
                        visible: pickerRoot.allowServerEmojis

                        Rectangle {
                            anchors.fill: parent
                            color: theme.palette.highlighted.base
                            visible: pickerRoot.pickerMode === "server"
                            radius: units.gu(0.6)
                            opacity: 0.15
                        }

                        SidebarIcon {
                            anchors.centerIn: parent
                            width: units.gu(4)
                            height: width
                            imageSource: pickerRoot.activeServerIcon
                            label: pickerRoot.serverName.substring(0, 2).toUpperCase()
                        }

                        MouseArea {
                            anchors.fill: parent
                            onClicked: pickerRoot.pickerMode = "server"
                        }
                    }

                    Rectangle {
                        width: parent.width * 0.6
                        height: units.dp(1)
                        anchors.horizontalCenter: parent.horizontalCenter
                        color: theme.palette.normal.base
                        opacity: 0.2
                        visible: pickerRoot.allowServerEmojis
                    }

                    Repeater {
                        model: pickerRoot.unicodeCategories
                        delegate: Item {
                            width: sidebarColumn.width
                            height: width

                            readonly property bool selected: pickerRoot.pickerMode === "unicode" && pickerRoot.unicodeCategory === modelData.key

                            Rectangle {
                                anchors.fill: parent
                                color: theme.palette.highlighted.base
                                visible: selected
                                radius: units.gu(0.6)
                                opacity: 0.15
                            }

                            Label {
                                anchors.centerIn: parent
                                text: modelData.icon
                                font.pixelSize: units.gu(2.4)
                                opacity: selected ? 1.0 : 0.6
                            }

                            MouseArea {
                                anchors.fill: parent
                                onClicked: {
                                    pickerRoot.pickerMode = "unicode"
                                    pickerRoot.unicodeCategory = modelData.key
                                }
                            }
                        }
                    }
                }
            }
        }

        // Main content
        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true

            ActivityIndicator {
                anchors.centerIn: parent
                running: pickerRoot.pickerMode === "unicode" && (pickerRoot.unicodeEmojis || []).length === 0
                visible: running
            }

            GridView {
                id: emojiGrid
                anchors.fill: parent
                visible: !loadingLabel.visible && !emptyLabel.visible
                clip: true
                model: pickerRoot.displayItems
                cellWidth: units.gu(5)
                cellHeight: units.gu(5)
                cacheBuffer: units.gu(80)

                delegate: Item {
                    width: emojiGrid.cellWidth
                    height: emojiGrid.cellHeight

                    Rectangle {
                        anchors {
                            fill: parent
                            margins: units.dp(2)
                        }
                        radius: units.gu(0.6)
                        color: emojiMouse.pressed ? theme.palette.highlighted.base : theme.palette.normal.base
                        opacity: emojiMouse.containsMouse ? 0.92 : 0.72
                    }

                    Column {
                        anchors {
                            fill: parent
                            margins: units.gu(0.4)
                        }
                        spacing: units.gu(0.25)

                        Label {
                            anchors.horizontalCenter: parent.horizontalCenter
                            visible: pickerRoot.pickerMode !== "server"
                            text: modelData.char || ""
                            font.pixelSize: units.gu(2.2)
                        }

                        Image {
                            anchors.horizontalCenter: parent.horizontalCenter
                            visible: pickerRoot.pickerMode === "server"
                            width: units.gu(2.8)
                            height: width
                            source: modelData.imageUrl || ""
                            fillMode: Image.PreserveAspectFit
                            asynchronous: true
                            cache: true
                        }


                    }

                    MouseArea {
                        id: emojiMouse
                        anchors.fill: parent
                        hoverEnabled: true
                        onClicked: {
                            if (pickerRoot.pickerMode === "server")
                                pickerRoot.chooseCustom(modelData)
                            else
                                pickerRoot.chooseUnicode(modelData)
                        }
                    }
                }
            }

            Label {
                id: loadingLabel
                anchors.centerIn: parent
                visible: pickerRoot.pickerMode === "unicode" && (pickerRoot.unicodeEmojis || []).length === 0
                text: i18n.tr("Loading…")
                color: theme.palette.normal.backgroundSecondaryText
            }

            Label {
                id: emptyLabel
                anchors.centerIn: parent
                width: parent.width - units.gu(4)
                wrapMode: Text.WordWrap
                horizontalAlignment: Text.AlignHCenter
                visible: !loadingLabel.visible && pickerRoot.displayItems.length === 0
                color: theme.palette.normal.backgroundSecondaryText
                text: pickerRoot.pickerMode === "server"
                      ? (pickerRoot.allowServerEmojis
                         ? i18n.tr("This server has no custom emoji.")
                         : i18n.tr("Server emoji are for server channels."))
                      : i18n.tr("Empty.")
            }
        }
    }
}
