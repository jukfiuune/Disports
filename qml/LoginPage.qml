import QtQuick 2.7
import Lomiri.Components 1.3
import Lomiri.Components.Popups 1.3 as Popups

Page {
    id: loginPage

    property bool busy: false
    property string errorText: ""
    property string qrImageSource: ""
    property string qrStatusText: ""
    property bool tosDialogOpened: false

    onVisibleChanged: {
        if (visible && !tosDialogOpened) {
            Popups.PopupUtils.open(tosDialogComponent)
            tosDialogOpened = true
        }
    }

    signal tokenLoginRequested(string token)
    signal refreshQrRequested()

    header: PageHeader {
        title: i18n.tr("Sign In")
    }

    Flickable {
        anchors {
            top: loginPage.header.bottom
            left: parent.left
            right: parent.right
            bottom: parent.bottom
            margins: units.gu(2)
        }
        contentHeight: contentColumn.height
        clip: true

        Column {
            id: contentColumn
            width: parent.width
            spacing: units.gu(2)

            Label {
                width: parent.width
                text: i18n.tr("Scan the QR code with the Discord mobile app, or paste a token instead.")
                wrapMode: Text.WordWrap
                color: theme.palette.normal.backgroundSecondaryText
            }

            Rectangle {
                width: Math.min(parent.width, units.gu(28))
                height: width
                anchors.horizontalCenter: parent.horizontalCenter
                radius: units.gu(0.75)
                color: theme.palette.normal.base

                Rectangle {
                    anchors.fill: parent
                    anchors.margins: units.gu(1)
                    radius: units.gu(0.5)
                    color: "white"

                    Image {
                        anchors.fill: parent
                        anchors.margins: units.gu(1)
                        source: loginPage.qrImageSource
                        fillMode: Image.PreserveAspectFit
                        smooth: true
                        cache: false
                    }

                    Label {
                        anchors.centerIn: parent
                        visible: loginPage.qrImageSource === ""
                        text: loginPage.busy ? i18n.tr("Preparing QR code...") : i18n.tr("Tap refresh to try again")
                        color: "#444444"
                        horizontalAlignment: Text.AlignHCenter
                    }
                }
            }

            Label {
                width: parent.width
                text: loginPage.qrStatusText !== "" ? loginPage.qrStatusText : i18n.tr("Open Discord on your Android or iOS device and scan to sign in.")
                wrapMode: Text.WordWrap
                horizontalAlignment: Text.AlignHCenter
                color: theme.palette.normal.backgroundSecondaryText
            }

            Button {
                width: parent.width
                text: i18n.tr("Refresh QR code")
                enabled: !loginPage.busy
                onClicked: loginPage.refreshQrRequested()
            }

            Label {
                width: parent.width
                visible: loginPage.errorText !== ""
                text: loginPage.errorText
                wrapMode: Text.WordWrap
                color: theme.palette.normal.negative
            }

            Rectangle {
                width: parent.width
                height: units.dp(1)
                color: theme.palette.normal.base
            }

            Button {
                width: parent.width
                text: i18n.tr("Paste a token instead (not recommended)")
                onClicked: {
                    var popup = __popups.open(tokenDialogComponent)
                }
            }
        }
    }

    // Quick popups utility
    Item { id: __popups; function open(comp) { return Popups.PopupUtils.open(comp) } }

    Component {
        id: tokenDialogComponent
        Popups.Dialog {
            id: tokenDialog
            title: i18n.tr("Manual Login")
            text: i18n.tr("Paste your Discord account token to sign in directly.")

            TextField {
                id: tokenField
                width: parent.width
                placeholderText: i18n.tr("Token")
                echoMode: TextInput.Password
            }

            Button {
                text: i18n.tr("Cancel")
                onClicked: Popups.PopupUtils.close(tokenDialog)
            }

            Button {
                text: i18n.tr("Sign In")
                color: theme.palette.normal.positive
                enabled: tokenField.text.trim() !== ""
                onClicked: {
                    var t = tokenField.text;
                    Popups.PopupUtils.close(tokenDialog);
                    loginPage.tokenLoginRequested(t);
                }
            }
        }
    }
    Component {
        id: tosDialogComponent
        Popups.Dialog {
            id: tosDialog
            title: i18n.tr("Warning")

            Column {
                width: parent.width
                spacing: units.gu(2)

                Label {
                    width: parent.width
                    text: i18n.tr("Using any unofficial Discord client is against Discord's Terms of Service and may result in your account being restricted or permanently banned (I've tried to minimize the risk of this as much as possible).")
                    wrapMode: Text.WordWrap
                    horizontalAlignment: Text.AlignHCenter
                    font.pixelSize: units.gu(1.8)
                }

                Label {
                    width: parent.width
                    text: i18n.tr("Use Disports at your own risk.")
                    wrapMode: Text.WordWrap
                    horizontalAlignment: Text.AlignHCenter
                    font.bold: true
                    font.pixelSize: units.gu(1.8)
                }

                Button {
                    width: parent.width
                    text: i18n.tr("I understand")
                    color: theme.palette.normal.positive
                    onClicked: Popups.PopupUtils.close(tosDialog)
                }
            }
        }
    }
}
