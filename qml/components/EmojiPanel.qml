import QtQuick 2.7
import Lomiri.Components 1.3

Item {
    id: emojiPanel

    property string serverName: ""
    property string activeServerId: ""
    property url activeServerIcon: ""
    property var serverEmojis: []
    property var unicodeEmojis: []
    property string initialMode: "unicode"

    signal emojiChosen(string text, var emojiData)
    signal open(string pickerMode)
    signal close()

    visible: false
    clip: false
    height: units.gu(24)
    opacity: visible ? 1 : 0

    onOpen: {
        picker.setPickerMode(pickerMode || initialMode || "unicode")
        visible = true
        picker.forceActiveFocus()
    }

    onClose: visible = false

    Behavior on opacity {
        LomiriNumberAnimation {
            duration: 160
        }
    }

    Rectangle {
        anchors.fill: parent
        color: theme.palette.normal.background
    }

    Rectangle {
        anchors {
            left: parent.left
            right: parent.right
            bottom: emojiPanel.top
        }
        height: units.dp(1)
        color: theme.palette.normal.base
        opacity: 0.7
    }

    EmojiPickerContent {
        id: picker
        anchors.fill: parent
        anchors.margins: units.gu(1)
        serverName: emojiPanel.serverName
        activeServerId: emojiPanel.activeServerId
        activeServerIcon: emojiPanel.activeServerIcon
        serverEmojis: emojiPanel.serverEmojis
        unicodeEmojis: emojiPanel.unicodeEmojis
        onEmojiChosen: emojiPanel.emojiChosen(text, emojiData)
    }
}
