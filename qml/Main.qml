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

    function applyLaunchModeFromArguments() {
        var args = Qt.application.arguments || []
        for (var i = 0; i < args.length; i++) {
            var p = String(args[i])
            if (p.indexOf("install/qml/") >= 0) {
                appState.runningUnderClickableDesktop = true
                return
            }
        }
    }

    // Logic & State
    AppState { id: appState; isWideLayout: root.width >= units.gu(90) }

    PythonBridge {
        id: pythonBridge
        onReady: function(data) {
            appState.myUserId = data.me ? (data.me.id || "") : ""
            appState.myUsername = data.me ? (data.me.username || "") : ""
            chatLogic.replaceModel(serverModel, data.guilds || [])
            chatLogic.replaceModel(dmContactModel, data.dmContacts || [])
            chatLogic.replaceModel(dmGroupModel, data.dmGroups || [])
            dmLogic.rebuildDmChannelModel()
            if (appState.authenticated)
                appState.startupPhase = "loaded"
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
            chatLogic.upsertMessage(msg)
            if (msg.channelId === appState.activeChannelId) {
                pythonBridge.call("discord_client.mark_seen", [msg.channelId, msg.messageId], function(){});
                if ((msg.authorId || "") !== appState.myUserId)
                    pythonBridge.call("discord_client.ack_message", [msg.channelId, msg.messageId], function(){});
            }
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
        onGatewayLog: function(data) {
            var message = (data && data.message) ? String(data.message) : ""
            console.log("Gateway: " + message)
        }
        onQrLoginImage: function(data) {
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
            navigationLogic.refreshUnicodeEmojis()
            root.applyLaunchModeFromArguments()
            pythonBridge.call("discord_client.dev_flags", [], function(flags) {
                if (flags && flags.clickableDesktopMode === true)
                    appState.runningUnderClickableDesktop = true
                navigationLogic.checkInitialState()
            })
            pythonBridge.call("discord_client.set_preference", ["blockedMessageVisibility", appSettings.blockedMessageVisibility], function(){});
        }
    }

    ChatLogic {
        id: chatLogic
        appState: appState; python: pythonBridge; appSettings: appSettings; pageStack: pageStack
        chatMessageModel: chatMessageModel; channelModel: channelModel; chatPageComp: chatPageComp
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
    }

    Connections {
        target: Connectivity
        onStatusChanged: {
            if (Connectivity.status === Connectivity.Online && appState.lastConnectivityStatus !== Connectivity.Online) {
                if (appState.pythonReady && appState.authenticated) {
                    pythonBridge.call("discord_client.reconnect", [], function(){});
                }
            }
            appState.lastConnectivityStatus = Connectivity.status;
        }
    }

    Settings {
        id: appSettings
        property string token: ""
        property int themeMode: 2
        property bool inlineGifPlayback: true
        property string uitkTheme: ""
        property string blockedMessageVisibility: "reveal"
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
            isOnline: appState.runningUnderClickableDesktop || appState.isOnline
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
                Component.onCompleted: pageStack.push(mainPageComp)

        Component {
            id: mainPageComp
            Page {
                id: mainPage
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
            id: settingsPageComp
            SettingsPage {
                stack: pageStack
                settingsObject: appSettings
                onThemeModeSelected: function(tMode) { themeLogic.applyThemePreference(tMode) }
                onLogoutRequested: authLogic.logout()
            }
        }
        }
    } // end mainArea
    } // end mainLayout

    // Splash & Offline Views
    SplashView { startupPhase: appState.startupPhase }
    OfflineView {
        visibleState: appState.startupPhase === "offline"
        onRetryRequested: navigationLogic.checkInitialState()
    }

    Component.onCompleted: {
        chatLogic.unreadLogic = unreadLogic
        root.applyLaunchModeFromArguments()
    }

}
