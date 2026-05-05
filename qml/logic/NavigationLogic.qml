import QtQuick 2.7
import Lomiri.Connectivity 1.0

QtObject {
    property var appState
    property var python
    property var appSettings
    property var pageStack

    property var chatPageComp

    property var channelModel
    property var serverModel

    property var authLogic
    property var chatLogic

    property int rootWidth: 0
    onRootWidthChanged: {
        appState.isWideLayout = rootWidth >= units.gu(90)
        if (appState.isWideLayout && pageStack.currentPage && pageStack.currentPage.objectName === "chatPage") {
            pageStack.pop()
        } else if (!appState.isWideLayout && appState.activeChannelId !== "" && pageStack.currentPage && pageStack.currentPage.objectName !== "chatPage") {
            pageStack.push(chatPageComp)
        }
    }

    function checkInitialState() {
        if (!appState.pythonReady) return;

        if (!appState.runningUnderClickableDesktop && Connectivity.status !== Connectivity.Online) {
            appState.startupPhase = "offline";
            return;
        }

        python.call("discord_client.load_token", [], function(result) {
            var fromFile = (result && result.token) ? result.token : "";
            if (fromFile !== "") {
                if (appSettings.token !== "")
                    appSettings.token = "";
                appState.startupPhase = "checking";
                authLogic.beginLogin(fromFile);
                return;
            }
            if (appSettings.token !== "") {
                var leg = appSettings.token;
                appSettings.token = "";
                python.call("discord_client.save_token", [leg], function(saveRes) {
                    if (!saveRes || !saveRes.ok) {
                        appState.startupPhase = "loaded";
                        authLogic.startQrLogin();
                        return;
                    }
                    appState.startupPhase = "checking";
                    authLogic.beginLogin(leg);
                });
                return;
            }
            appState.startupPhase = "loaded";
            authLogic.startQrLogin();
        });
    }

    function selectServer(id, name) {
        if (!appState.pythonReady)
            return
        appState.mode            = "server"
        appState.activeServerId   = id
        appState.activeServerName = name

        if (channelModel)
            chatLogic.replaceModel(channelModel, [])
        appState.activeChannelId = ""
        appState.activeChannelName = ""
        if (chatLogic && chatLogic.chatMessageModel)
            chatLogic.replaceModel(chatLogic.chatMessageModel, [])

        // Find icon in serverModel
        if (serverModel) {
            for (var i = 0; i < serverModel.count; i++) {
                var item = serverModel.get(i)
                if (item.serverId === id) {
                    appState.activeServerIcon = item.iconUrl || ""
                    break
                }
            }
        }

        python.call("discord_client.fetch_guild_channels", [id], function(channels) {
            chatLogic.replaceModel(channelModel, channels)
        })
    }

    function refreshActiveServerEmojis() {
        if (!appState.pythonReady) {
            appState.activeServerEmojis = []
            return
        }
        if ((appState.activeServerId || "") === "") {
            appState.activeServerEmojis = []
            return
        }
        python.call("discord_client.fetch_guild_emojis", [appState.activeServerId], function(emojis) {
            appState.activeServerEmojis = emojis || []
        })
    }

    function refreshUnicodeEmojis() {
        if (!appState.pythonReady) {
            appState.unicodeEmojis = []
            return
        }
        python.call("discord_client.fetch_unicode_emojis", [], function(emojis) {
            appState.unicodeEmojis = emojis || []
        })
    }
}
