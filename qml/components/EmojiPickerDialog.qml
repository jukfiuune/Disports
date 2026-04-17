import QtQuick 2.7
import Lomiri.Components 1.3
import Lomiri.Components.Popups 1.3

Dialog {
    id: emojiPickerDialog

    property string serverName: ""
    property string activeServerId: ""
    property url    activeServerIcon: ""
    property var serverEmojis: []
    property var unicodeEmojis: []
    property string initialMode: "unicode"

    signal emojiChosen(string text, var emojiData)

    title: i18n.tr("Choose emoji")
    text: i18n.tr("Insert an emoji into your message.")

    Column {
        width: units.gu(40)
        spacing: units.gu(1)

        EmojiPickerContent {
            id: picker
            width: parent.width
            height: units.gu(30)
            serverName: emojiPickerDialog.serverName
            activeServerId: emojiPickerDialog.activeServerId
            activeServerIcon: emojiPickerDialog.activeServerIcon
            serverEmojis: emojiPickerDialog.serverEmojis || []
            unicodeEmojis: emojiPickerDialog.unicodeEmojis || []
            Component.onCompleted: setPickerMode(emojiPickerDialog.initialMode)
            onEmojiChosen: emojiPickerDialog.emojiChosen(text, emojiData)
        }
    }

    Button {
        text: i18n.tr("Close")
        onClicked: PopupUtils.close(emojiPickerDialog)
    }
}
