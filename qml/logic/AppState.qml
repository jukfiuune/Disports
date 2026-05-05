import QtQuick 2.7
import Lomiri.Connectivity 1.0

QtObject {
    property string mode: "dm" // "dm" | "server"
    property string activeServerId: ""
    property string activeServerName: ""
    property url activeServerIcon: ""
    property var activeServerEmojis: []
    property var unicodeEmojis: []
    property string activeChannelId: ""
    property string activeChannelName: ""
    property string myUserId: ""
    property string myUsername: ""
    property string typingNotice: ""
    property string draftText: ""
    property string replyMessageId: ""
    property string replyAuthor: ""
    property string replyBody: ""
    property bool authenticated: false
    property bool loginBusy: false
    property string loginError: ""
    property int totalDmUnread: 0
    property string qrImageSource: ""
    property bool loadingOlderMessages: false
    property bool isOnline: Connectivity.status === Connectivity.Online
    property int lastConnectivityStatus: Connectivity.status
    property string qrStatusText: ""
    property bool pythonReady: false
    property string startupPhase: "initializing" // initializing | checking | syncing | offline | loaded
    property bool isWideLayout: false
    property int sidebarRevision: 0
    property bool runningUnderClickableDesktop: false
}
