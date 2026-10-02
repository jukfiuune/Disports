import QtQuick 2.7
import Lomiri.Components 1.3
import Lomiri.Components.Popups 1.3

// Shown once (Main.qml): the Telegram group for news about Disports and
// the beta of the new version.
Dialog {
    id: communityNotice

    title: i18n.tr("Disports is getting a big update")
    text: i18n.tr("A rewritten Disports, with voice calls, captcha and password sign-in, is in beta. Join the Telegram group for news, beta versions and to share feedback.")
          + "\n\n"
          + i18n.tr("The beta needs Ubuntu Touch 24.04-2.x and uses parts of the system that aren't final yet. It's made by Disports, not by UBports, so please report problems in the group, not to UBports.")

    Button {
        text: i18n.tr("Join the group")
        color: theme.palette.normal.positive
        onClicked: {
            Qt.openUrlExternally("https://t.me/disportsdiscussion")
            PopupUtils.close(communityNotice)
        }
    }
    Button {
        text: i18n.tr("No thanks")
        onClicked: PopupUtils.close(communityNotice)
    }
}
