import QtQuick 2.7
import Lomiri.Components 1.3
import Lomiri.Components.Popups 1.3 as Popups
import QtWebEngine 1.8

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

    Connections {
        target: typeof appState !== "undefined" ? appState : null
        onCaptchaRequiredChanged: {
            if (appState.captchaRequired) {
                __popups.open(captchaDialogComponent)
            }
        }
    }

    signal tokenLoginRequested(string token)
    signal refreshQrRequested()
    signal captchaSolved(string captchaToken)
    signal captchaCanceled()

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

            Button {
                width: parent.width
                text: "Open WebEngine Test Dialog"
                onClicked: {
                    __popups.open(captchaDialogComponent)
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
    Component {
        id: captchaDialogComponent
        Popups.Dialog {
            id: captchaDialog
            title: i18n.tr("Security Check Required")

            Item {
                width: parent.width
                height: units.gu(45) // Allow enough height for hCaptcha to open the image grid

                WebEngineView {
                    id: webView
                    anchors.fill: parent

                    Component.onCompleted: {
                        if (typeof appState === "undefined" || !appState.captchaSiteKey) {
                            // Render a simple placeholder test page when opened manually
                            var testHtml = "<html><body style=\"background-color: #36393f; color: #ffffff; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; font-family: sans-serif; text-align: center;\">" +
                                           "<div><h2>QtWebEngine Test Mode</h2><p>Click 'Load Google (Test)' below to verify web navigation works.</p></div>" +
                                           "</body></html>";
                            loadHtml(testHtml, "https://discord.com/");
                            return;
                        }
                        // Crucial: rqdata is mandatory if provided, omit it otherwise.
                        var rqDataJS = appState.captchaRqData ? "rqdata: '" + appState.captchaRqData + "',\n" : "";
                        var html = "<html><head><meta name=\"viewport\" content=\"width=device-width, initial-scale=1, maximum-scale=1, user-scalable=0\">" +
                                   "<script src=\"https://js.hcaptcha.com/1/api.js?onload=onHcaptchaLoad&render=explicit&host=discord.com\" async defer></script></head>" +
                                   "<body style=\"background-color: #36393f; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0;\">" +
                                   "<div id=\"captcha\"></div>" +
                                   "<script>function gotToken(token) { window.location.href = 'disports-captcha://solved?token=' + encodeURIComponent(token); }" +
                                   "window.onHcaptchaLoad = function() { hcaptcha.render('captcha', { sitekey: '" + appState.captchaSiteKey + "', theme: 'dark', callback: gotToken, " + rqDataJS + " }); };</script>" +
                                   "</body></html>";
                        
                        // Render with discord.com as BaseURL to trick Discord CORS validation
                        loadHtml(html, "https://discord.com/");
                    }

                    onUrlChanged: {
                        var urlStr = url.toString();
                        if (urlStr.indexOf("disports-captcha://solved?token=") === 0) {
                            var token = decodeURIComponent(urlStr.split("token=")[1]);
                            Popups.PopupUtils.close(captchaDialog);
                            loginPage.captchaSolved(token);
                        }
                    }
                }
            }

            Button {
                text: "Load Google (Test)"
                onClicked: {
                    webView.url = "https://google.com"
                }
            }

            Button {
                text: i18n.tr("Cancel")
                onClicked: {
                    Popups.PopupUtils.close(captchaDialog);
                    if (typeof appState !== "undefined") {
                        appState.captchaRequired = false;
                        appState.loginBusy = false;
                    }
                    loginPage.captchaCanceled();
                }
            }
        }
    }
}
