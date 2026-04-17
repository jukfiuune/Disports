import QtQuick 2.7

QtObject {
    property var appState
    property var python
    property var appSettings
    property var pageStack
    
    // models to clear on logout
    property var serverModel
    property var dmContactModel
    property var dmGroupModel
    property var dmChannelModel
    property var channelModel
    property var chatMessageModel

    function beginLogin(token) {
        if (!appState.pythonReady || !token || token.trim() === "")
            return

        appState.loginBusy = true
        appState.loginError = ""
        appState.qrStatusText = i18n.tr("Signing in…")
        stopQrLogin()
        python.call("discord_client.login", [token], function(result) {
            appState.loginBusy = false
            if (!result || !result.ok) {
                if (result && result.clear_saved_token)
                    python.call("discord_client.clear_token", [], function() {})
                appSettings.token = ""
                appState.authenticated = false
                appState.loginError = result && result.error ? result.error : i18n.tr("Login failed.")
                appState.qrStatusText = ""
                appState.startupPhase = "loaded"
                startQrLogin()
                return
            }
            python.call("discord_client.save_token", [token], function(saveRes) {
                if (!saveRes || !saveRes.ok) {
                    python.call("discord_client.disconnect", [], function() {})
                    appState.loginError = (saveRes && saveRes.error) ? saveRes.error : i18n.tr("Could not save login securely.")
                    appState.startupPhase = "loaded"
                    startQrLogin()
                    return
                }
                appSettings.token = ""
                appState.myUserId = result.id
                appState.myUsername = result.username
                appState.authenticated = true
                appState.loginError = ""
                appState.qrImageSource = ""
                appState.qrStatusText = ""
                appState.startupPhase = "syncing"
                python.call("discord_client.connect_gateway", [], function() {})
            })
        })
    }

    function logout() {
        if (appState.pythonReady)
            python.call("discord_client.disconnect", [], function() {})
        stopQrLogin()
        if (appState.pythonReady)
            python.call("discord_client.clear_token", [], function() {})
        appSettings.token = ""
        appState.authenticated = false
        appState.loginBusy = false
        appState.loginError = ""
        appState.qrImageSource = ""
        appState.qrStatusText = ""
        clearSessionState()
        while (pageStack.depth > 1)
            pageStack.pop()
        startQrLogin()
    }

    function clearSessionState() {
        appState.mode = "dm"
        appState.activeServerId = ""
        appState.activeServerName = ""
        appState.activeServerEmojis = []
        appState.activeChannelId = ""
        appState.activeChannelName = ""
        appState.myUserId = ""
        appState.myUsername = ""
        appState.typingNotice = ""
        appState.draftText = ""
        
        appState.replyMessageId = ""
        appState.replyAuthor = ""
        appState.replyBody = ""
        appState.sidebarRevision += 1
        
        serverModel.clear()
        dmContactModel.clear()
        dmGroupModel.clear()
        dmChannelModel.clear()
        channelModel.clear()
        chatMessageModel.clear()
    }

    function startQrLogin() {
        if (!appState.pythonReady || appState.authenticated)
            return
        appState.qrImageSource = ""
        appState.qrStatusText = i18n.tr("Generating QR code…")
        python.call("discord_client.start_qr_login", [], function(result) {
            if (result && !result.ok) {
                appState.loginError = result.error || i18n.tr("Unable to start QR login.")
                appState.qrStatusText = ""
            }
        })
    }

    function stopQrLogin() {
        if (!appState.pythonReady)
            return
        python.call("discord_client.stop_qr_login", [], function() {})
    }
}
