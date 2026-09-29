import QtQuick 2.7
import QtQuick.Layouts 1.3
import Lomiri.Components 1.3
import Lomiri.Components.Popups 1.3
import Lomiri.Connectivity 1.0
import Qt.labs.settings 1.0
import io.thp.pyotherside 1.4
import "./"
import "./logic"
import "./components"

MainView {
    id: root
    objectName: "mainView"
    applicationName: "disports.jukfiuu"
    automaticOrientation: true
    theme.name: appSettings.uitkTheme

    width:  units.gu(45)
    height: units.gu(75)
    property string pendingNotificationChannelId: ""
    // Sentinel forces the first sync to clear stale daemon state if necessary.
    property string backendVisibleChannelId: "__unknown__"
    property bool applicationActive: Qt.application.state === Qt.ApplicationActive

    onApplicationActiveChanged: {
        root.syncAppForeground()
        root.syncActiveChatVisibility()
        if (root.applicationActive) {
            root.consumeNotificationAction()
            root.refreshSessionAfterResume()
        }
    }

    // Tells Python about network loss/regain: offline, API calls fail at
    // once (serving the cache) and the dead gateway socket is dropped; back
    // online, the session reconnects (or starts) without waiting out backoff.
    function syncNetworkState(online) {
        if (!appState.pythonReady || appState.runningUnderClickableDesktop) return
        pythonBridge.call("discord_client.set_network_available", [online], function() {})
    }

    // The daemon posts notifications only while no app is in the
    // foreground: Lomiri suspends backgrounded apps, so they cannot.
    function syncAppForeground() {
        if (!appState.pythonReady) return
        pythonBridge.call("discord_client.set_app_foreground", [root.applicationActive], function() {})
    }

    function isActiveChatVisible() {
        if (!root.applicationActive
                || !appState.authenticated
                || appState.activeChannelId === ""
                || !pageStack.visible
                || !pageStack.currentPage)
            return false
        if (appState.isWideLayout)
            return pageStack.currentPage.objectName === "mainPage"
        return pageStack.currentPage.objectName === "chatPage"
    }

    function syncActiveChatVisibility() {
        if (!appState.pythonReady) return
        var visibleChannelId = root.isActiveChatVisible() ? appState.activeChannelId : ""
        if (visibleChannelId === root.backendVisibleChannelId) return
        root.backendVisibleChannelId = visibleChannelId
        pythonBridge.call("discord_client.set_active_channel", [visibleChannelId], function() {})
    }

    function channelIdFromUri(rawUri) {
        var match = String(rawUri || "").match(/^disports:\/\/channel\/([0-9]+)(?:[\/?#]|$)/)
        return match ? match[1] : ""
    }

    function openDisportsUri(rawUri) {
        var channelId = root.channelIdFromUri(rawUri)
        if (channelId === "") {
            console.log("Notification navigation: ignored URI without channel id")
            return
        }
        console.log("Notification navigation: received channel=" + channelId)
        root.pendingNotificationChannelId = channelId
        root.openPendingNotificationChannel()
    }

    function openPendingNotificationChannel() {
        if (root.pendingNotificationChannelId === "")
            return
        if (!appState.pythonReady
                || !appState.authenticated
                || appState.startupPhase !== "loaded") {
            console.log("Notification navigation: deferred channel="
                        + root.pendingNotificationChannelId
                        + " pythonReady=" + appState.pythonReady
                        + " authenticated=" + appState.authenticated
                        + " startupPhase=" + appState.startupPhase)
            return
        }
        var channelId = root.pendingNotificationChannelId
        root.pendingNotificationChannelId = ""
        console.log("Notification navigation: opening channel=" + channelId)
        while (pageStack.depth > 1)
            pageStack.pop()
        chatLogic.openChannelById(channelId)
    }

    function consumeNotificationAction() {
        if (!appState.pythonReady || !root.applicationActive)
            return
        pythonBridge.call("discord_client.take_notification_action", [], function(data) {
            if (data && data.channelId) {
                console.log("Notification navigation: consumed live action channel=" + data.channelId)
                root.openDisportsUri("disports://channel/" + data.channelId)
            }
        })
    }

    function openActiveChannelInfo() {
        if (appState.activeChannelId === "")
            return
        pageStack.push(channelInfoPageComp, {
            "stack": pageStack,
            "python": pythonBridge,
            "channelId": appState.activeChannelId,
            "fallbackName": appState.activeChannelName
        })
    }

    function refreshSessionAfterResume() {
        if (!appState.pythonReady || !appState.authenticated)
            return
        // Events may have been missed while suspended (in daemon mode the
        // daemon drops clients that stop reading), so resync either way.
        console.log("Session: foreground refresh")
        appState.refreshing = true
        pythonBridge.call("discord_client.resume_session", [], function() {
            chatLogic.refreshActiveChannel(function() {
                appState.refreshing = false
                console.log("Session: foreground conversation refresh complete")
            })
        })
    }

    function applySessionPayload(data, fromCache) {
        if (!data || !data.me || !data.me.id)
            return false
        appState.myUserId = data.me.id || ""
        appState.myUsername = data.me.username || ""
        chatLogic.replaceModel(serverModel, data.guilds || [])
        chatLogic.replaceModel(dmContactModel, data.dmContacts || [])
        chatLogic.replaceModel(dmGroupModel, data.dmGroups || [])
        dmLogic.rebuildDmChannelModel()
        appState.authenticated = true
        // Cached data can arrive after a live READY event. It hydrates models,
        // but must never make an already-connected session look disconnected.
        if (!fromCache)
            appState.gatewayReady = true
        appState.hasCachedSession = true
        appState.startupPhase = "loaded"
        console.log((fromCache ? "Offline cache: hydrated" : "Session: refreshed")
                    + " guilds=" + (data.guilds || []).length
                    + " dms=" + ((data.dmContacts || []).length + (data.dmGroups || []).length))
        root.openPendingNotificationChannel()
        return true
    }

    function applyLaunchArguments() {
        var args = Qt.application.arguments || []
        for (var i = 0; i < args.length; i++) {
            var p = String(args[i])
            if (p.indexOf("install/qml/") >= 0)
                appState.runningUnderClickableDesktop = true
            root.openDisportsUri(p)
        }
    }

    // Logic & State
    AppState { id: appState; isWideLayout: root.width >= units.gu(90) }

    PythonBridge {
        id: pythonBridge
        onReady: function(data) {
            root.applySessionPayload(data, !!(data && data.cached))
        }
        onPrivateChannels: function(data) {
            chatLogic.replaceModel(dmContactModel, data.dmContacts || [])
            chatLogic.replaceModel(dmGroupModel, data.dmGroups || [])
            dmLogic.rebuildDmChannelModel()
        }
        onGuildChannels: function(data) {
            if (data && data.guildId === appState.activeServerId)
                chatLogic.replaceModel(channelModel, data.list || [])
        }
        onGuildSidebar: function(data) {
            chatLogic.replaceModel(serverModel, data.guilds || [])
        }
        onGuildMemberChunk: function(data) {}
        onMessageCreate: function(msg) {
            appState.typingNotice = ""
            // Notification text rides along with the event; keep it out of
            // the message model.
            var notifySummary = msg.notifySummary || ""
            var notifyBody = msg.notifyBody || ""
            delete msg.notifySummary
            delete msg.notifyBody
            chatLogic.upsertMessage(msg)
            if (msg.channelId === appState.activeChannelId && root.isActiveChatVisible()) {
                pythonBridge.call("discord_client.mark_seen", [msg.channelId, msg.messageId], function(){});
                if ((msg.authorId || "") !== appState.myUserId)
                    pythonBridge.call("discord_client.ack_message", [msg.channelId, msg.messageId], function(){});
            }
            root.maybeNotifyMessage(msg.channelId, notifySummary, notifyBody)
        }
        onChannelUnread: function(data) { unreadLogic.applyChannelUnread(data) }
        onMessageUpdate: function(msg) { chatLogic.upsertMessage(msg) }
        onMessageDelete: function(msg) { if (msg.channelId === appState.activeChannelId) chatLogic.removeMessage(msg.messageId) }
        onMessageBulkDelete: function(msg) {
            if (msg.channelId !== appState.activeChannelId) return
            for (var i = 0; i < msg.messageIds.length; i++) chatLogic.removeMessage(msg.messageIds[i])
        }
        onTyping: function(data) { if (data.channelId === appState.activeChannelId) appState.typingNotice = data.author + " is typing..." }
        onPresence: function(data) { dmLogic.updateContactStatus(data.userId, data.status) }
        onMessageReaction: function(data) { chatLogic.applyReactionUpdate(data) }
        onSessionInvalid: function(data) {
            authLogic.handleSessionInvalid(data && data.error ? String(data.error) : "")
        }
        onConnectionStatus: function(data) {
            appState.gatewayReady = !!(data && data.ready)
            if (data && data.phase)
                appState.connectionPhase = String(data.phase)
            appState.reconnectDelaySeconds = data && data.retrySeconds
                                             ? Number(data.retrySeconds) : 0
        }
        onGatewayLog: function(data) {
            var message = (data && data.message) ? String(data.message) : ""
            console.log("Gateway: " + message)
        }
        onQrLoginImage: function(data) {
            appState.loginBusy = false
            appState.qrImageSource = data.dataUri || ""
            appState.qrStatusText = i18n.tr("Scan with the Discord mobile app.")
            appState.loginError = ""
        }
        onQrLoginPending: function(data) { appState.qrStatusText = data.message || i18n.tr("Confirm the login on your phone.") }
        onQrLoginToken: function(data) { if (data.token) authLogic.beginLogin(data.token) }
        onQrLoginError: function(data) {
            appState.loginBusy = false
            appState.qrImageSource = ""
            appState.qrStatusText = ""
            appState.loginError = data.error || i18n.tr("QR login failed.")
        }
        onReadyForInit: {
            appState.pythonReady = true
            root.syncAppForeground()
            root.consumeNotificationAction()
            navigationLogic.refreshUnicodeEmojis()
            root.applyLaunchArguments()
            pythonBridge.call("discord_client.load_offline_state", [], function(cached) {
                root.applySessionPayload(cached, true)
                pythonBridge.call("discord_client.dev_flags", [], function(flags) {
                    if (flags && flags.clickableDesktopMode === true)
                        appState.runningUnderClickableDesktop = true
                    if (!appState.runningUnderClickableDesktop && !appState.isOnline)
                        root.syncNetworkState(false)
                    navigationLogic.checkInitialState()
                })
            })
            pythonBridge.call("discord_client.set_preference", ["blockedMessageVisibility", appSettings.blockedMessageVisibility], function(){});
            pythonBridge.call("discord_client.get_settings", [], function(result) {
                if (result) appSettings.notificationsEnabled = !!result.notifications
            });
        }
    }

    ChatLogic {
        id: chatLogic
        appState: appState; python: pythonBridge; appSettings: appSettings; pageStack: pageStack
        chatMessageModel: chatMessageModel; channelModel: channelModel; serverModel: serverModel; chatPageComp: chatPageComp
        onDeleteConfirmRequested: function(messageId) {
            PopupUtils.open(deleteDialogComp, root, { messageId: messageId })
        }
    }

    Component {
        id: deleteDialogComp
        DeleteDialog {
            onDeleteConfirmed: function(mId) {
                pythonBridge.call("discord_client.delete_message", [appState.activeChannelId, mId], function(result){})
            }
        }
    }

    DmLogic {
        id: dmLogic
        appState: appState; chatLogic: chatLogic
        dmContactModel: dmContactModel; dmGroupModel: dmGroupModel; dmChannelModel: dmChannelModel
    }

    AuthLogic {
        id: authLogic
        appState: appState; python: pythonBridge; appSettings: appSettings; pageStack: pageStack
        serverModel: serverModel; dmContactModel: dmContactModel; dmGroupModel: dmGroupModel; dmChannelModel: dmChannelModel; channelModel: channelModel; chatMessageModel: chatMessageModel
    }

    NavigationLogic {
        id: navigationLogic
        appState: appState; python: pythonBridge; appSettings: appSettings; pageStack: pageStack
        chatPageComp: chatPageComp; channelModel: channelModel; serverModel: serverModel; authLogic: authLogic; chatLogic: chatLogic
        rootWidth: root.width
    }

    ThemeLogic {
        id: themeLogic
        appSettings: appSettings
    }

    Connections {
        target: appState
        onActiveServerIdChanged: navigationLogic.refreshActiveServerEmojis()
        onConnectionReadyChanged: {
            console.log("Session: connectionReady=" + appState.connectionReady
                        + " gatewayReady=" + appState.gatewayReady
                        + " networkOnline=" + appState.isOnline)
            if (!appState.connectionReady)
                return
            // Everything shown while disconnected came from the cache.
            chatLogic.refreshActiveChannel()
            if (appState.mode === "server" && appState.activeServerId !== "")
                chatLogic.loadServerChannels(appState.activeServerId)
            navigationLogic.refreshActiveServerEmojis()
        }
        onActiveChannelIdChanged: root.syncActiveChatVisibility()
        onAuthenticatedChanged: {
            root.openPendingNotificationChannel()
            root.syncActiveChatVisibility()
        }
        onIsWideLayoutChanged: root.syncActiveChatVisibility()
        onPythonReadyChanged: root.syncActiveChatVisibility()
        onStartupPhaseChanged: root.openPendingNotificationChannel()
    }

    Connections {
        target: UriHandler
        onOpened: {
            for (var i = 0; i < uris.length; i++)
                root.openDisportsUri(uris[i])
        }
    }

    Connections {
        target: Connectivity
        onStatusChanged: {
            var online = Connectivity.status === Connectivity.Online
            var wasOnline = appState.lastConnectivityStatus === Connectivity.Online
            appState.lastConnectivityStatus = Connectivity.status
            console.log("Connectivity: status=" + Connectivity.status + " online=" + online)
            if (online === wasOnline)
                return
            if (!online)
                appState.gatewayReady = false
            root.syncNetworkState(online)
            if (online && appState.pythonReady && !appState.authenticated
                    && appState.startupPhase === "offline")
                navigationLogic.checkInitialState()
        }
    }

    Settings {
        id: appSettings
        property string token: ""
        property int themeMode: 2
        property bool inlineGifPlayback: true
        property string uitkTheme: ""
        property string blockedMessageVisibility: "reveal"
        property int maxComposerLines: 3
        property bool notificationsEnabled: false
    }

    function maybeNotifyMessage(channelId, summary, body) {
        // Whether a message deserves a notification (DM / mention, mutes,
        // blocked users) is decided in Python so the daemon and the app agree.
        if (!appSettings.notificationsEnabled || summary === "") return
        if (channelId === appState.activeChannelId && root.isActiveChatVisible()) return
        pythonBridge.call("discord_client.local_notify", [summary, body, channelId], function(result) {})
    }

    Connections {
        target: appSettings
        onBlockedMessageVisibilityChanged: {
            if (appState.pythonReady) {
                pythonBridge.call("discord_client.set_preference", ["blockedMessageVisibility", appSettings.blockedMessageVisibility], function(){});
            }
        }
    }

    // Shared models
    ListModel {
        id: serverModel
    }

    ListModel {
        id: dmContactModel
    }

    ListModel {
        id: dmGroupModel
    }

    ListModel {
        id: dmChannelModel
    }

    ListModel { id: channelModel } // rebuilt by selectServer()

    ListModel {
        id: chatMessageModel
    }

    UnreadLogic {
        id: unreadLogic
        appState: appState
        serverModel: serverModel
        dmContactModel: dmContactModel
        dmGroupModel: dmGroupModel
        dmChannelModel: dmChannelModel
        channelModel: channelModel
    }

    ColumnLayout {
        id: mainLayout
        anchors.fill: parent
        spacing: 0

        OfflineBanner {
            id: offlineBanner
            networkOnline: appState.runningUnderClickableDesktop || appState.isOnline
            connectionReady: appState.connectionReady
            hasCachedSession: appState.hasCachedSession
            applicationActive: root.applicationActive
            reconnectPhase: appState.connectionPhase
            retrySeconds: appState.reconnectDelaySeconds
            refreshing: appState.refreshing
        }

        Item {
            id: mainArea
            Layout.fillWidth: true
            Layout.fillHeight: true

            LoginPage {
                id: loginPage
                anchors.fill: parent
                visible: appState.startupPhase === "loaded" && !appState.authenticated
                busy: appState.loginBusy
                errorText: appState.loginError
                qrImageSource: appState.qrImageSource
                qrStatusText: appState.qrStatusText
                onTokenLoginRequested: function(token) { authLogic.beginLogin(token) }
                onRefreshQrRequested: authLogic.startQrLogin()
            }

    // Navigation stack
            PageStack {
                id: pageStack
                anchors.fill: parent
                visible: appState.startupPhase === "loaded" && appState.authenticated
                onVisibleChanged: {
                    if (visible && depth === 0)
                        pageStack.push(mainPageComp)
                    root.syncActiveChatVisibility()
                }
                onCurrentPageChanged: root.syncActiveChatVisibility()
                Component.onCompleted: {
                    if (depth === 0)
                        pageStack.push(mainPageComp)
                }

            WaitingBar {
                anchors {
                    top: parent.top
                    left: parent.left
                    right: parent.right
                }
                // Offline there is nothing in progress; the banner explains.
                running: appState.authenticated
                         && (appState.runningUnderClickableDesktop || appState.isOnline)
                         && (!appState.connectionReady || appState.refreshing)
                z: 100
            }

        Component {
            id: mainPageComp
            Page {
                id: mainPage
                objectName: "mainPage"
                header: PageHeader {
                    title: i18n.tr("Disports")
                    trailingActionBar.actions: [
                        Action {
                            iconName: "settings"
                            text: i18n.tr("Settings")
                            onTriggered: pageStack.push(settingsPageComp)
                        }
                    ]
                }

                Row {
                    anchors {
                        top: mainPage.header.bottom
                        left: parent.left; right: parent.right; bottom: parent.bottom
                    }

                    Sidebar {
                        id: sidebar
                        height: parent.height
                        servers: serverModel
                        dmChannels: dmChannelModel
                        activeMode: appState.mode
                        activeServerId: appState.activeServerId
                        activeChannelId: appState.activeChannelId
                        dmUnreadCount: appState.totalDmUnread
                        revision: appState.sidebarRevision
                        onDmSelected: { appState.mode = "dm" }
                        onDmChannelSelected: function(channelId, name) {
                            appState.mode = "dm"
                            chatLogic.openChat(channelId, name)
                        }
                        onServerSelected: function(id, name) { navigationLogic.selectServer(id, name) }
                    }

                    Item {
                        width: appState.isWideLayout ? units.gu(32) : parent.width - sidebar.width
                        height: parent.height

                        DmPanel {
                            anchors.fill: parent
                            visible:  appState.mode === "dm"
                            channels: dmChannelModel
                            onChannelOpened: function(channelId, name) { chatLogic.openChat(channelId, name) }
                        }

                        ServerPanel {
                            anchors.fill: parent
                            visible:    appState.mode === "server"
                            serverName: appState.activeServerName
                            channels:   channelModel
                            onChannelOpened: function(channelId, name) { chatLogic.openChat(channelId, name) }
                        }
                    }

                    Loader {
                        id: inlineChatLoader
                        width: appState.isWideLayout ? parent.width - sidebar.width - units.gu(32) : 0
                        height: parent.height
                        active: appState.isWideLayout
                        visible: appState.isWideLayout

                        sourceComponent: Item {
                            Rectangle { anchors.fill: parent; color: theme.palette.normal.background }

                            ActiveChatPanel {
                                anchors.fill: parent
                                visible: appState.activeChannelId !== ""
                            }

                            Column {
                                anchors.centerIn: parent
                                spacing: units.gu(1)
                                visible: appState.activeChannelId === ""
                                Label {
                                    anchors.horizontalCenter: parent.horizontalCenter
                                    text: i18n.tr("Select a conversation")
                                    font.bold: true; font.pixelSize: units.gu(2)
                                }
                                Label {
                                    anchors.horizontalCenter: parent.horizontalCenter
                                    text: i18n.tr("Choose a DM, group, or channel to start chatting.")
                                    color: theme.palette.normal.backgroundSecondaryText
                                }
                            }
                        }
                    }
                }

            }
        }

        Component {
            id: chatPageComp
            ChatPage {
                stack: pageStack
            }
        }
        Component {
            id: channelInfoPageComp
            ChannelInfoPage {}
        }
        Component {
            id: settingsPageComp
            SettingsPage {
                stack: pageStack
                settingsObject: appSettings
                python: pythonBridge
                sharedAppState: appState
                onThemeModeSelected: function(tMode) { themeLogic.applyThemePreference(tMode) }
                onLogoutRequested: authLogic.logout()
            }
        }
        }
    } // end mainArea
    } // end mainLayout

    // Splash & Offline Views
    SplashView {
        startupPhase: appState.startupPhase
        pageComponent: mainPageComp
    }
    OfflineView {
        visibleState: appState.startupPhase === "offline"
        onRetryRequested: navigationLogic.checkInitialState()
    }

    Component.onCompleted: {
        chatLogic.unreadLogic = unreadLogic
        root.applyLaunchArguments()
    }

}
