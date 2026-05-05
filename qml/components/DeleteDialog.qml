import QtQuick 2.7
import Lomiri.Components 1.3
import Lomiri.Components.Popups 1.3

Dialog {
    id: deleteDialogInstance
    property string messageId: ""
    signal deleteConfirmed(string msgId)

    title: i18n.tr("Delete message")
    text: i18n.tr("Are you sure you want to permanently delete this message?")

    Button {
        text: i18n.tr("Delete")
        color: "#ED3146"
        onClicked: {
            PopupUtils.close(deleteDialogInstance)
            deleteConfirmed(messageId)
        }
    }
    Button {
        text: i18n.tr("Cancel")
        onClicked: PopupUtils.close(deleteDialogInstance)
    }
}
