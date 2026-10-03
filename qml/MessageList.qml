import QtQuick
import Lomiri.Components
import Lomiri.Components.Popups
import Disports.Core

// The open channel's messages, newest at the bottom. Loads older ones when
// scrolled to the top.
ListView {
    id: list

    signal replyRequested(string messageId, string author, string text)
    signal reactRequested(string messageId, var caller)
    signal editRequested(string messageId, string text)
    signal deleteRequested(string messageId)
    signal mediaOpened(var media)
    signal profileRequested(string userId)

    // Stays on the newest message until scrolled away from, and goes back
    // to it when the content grows (history arriving, images laid out) or
    // the view shrinks (the keyboard opening). Bottom-to-top: the newest
    // message is at atYEnd, and positionViewAtBeginning() goes there.
    property bool followNewest: true

    // At the newest message, give or take a little: rows still being laid
    // out can leave the view a few pixels short of atYEnd.
    function nearNewest() {
        return atYEnd || originY + contentHeight - contentY - height < units.gu(1)
    }

    function scrollToNewest() {
        cancelFlick()
        openingAtNew = false
        followNewest = true
        updateAtNewest()
        Qt.callLater(function() {
            if (list.followNewest)
                list.positionViewAtBeginning()
        })
    }

    // A channel with unread messages opens at the first one, under the
    // "Unread messages" bar, once its messages are in. Only showing the
    // newest ones marks the channel read (Session.atNewest).
    property bool openingAtNew: false

    function openAtNew() {
        if (!openingAtNew || Session.loadingMessages || count === 0)
            return
        openingAtNew = false
        let index = Session.messages.firstNewIndex
        // Further back than loaded: the oldest loaded, which loads more.
        if (index < 0 && Session.messages.hasNew)
            index = count - 1
        if (index < 0) {
            scrollToNewest()
            return
        }
        positionViewAtIndex(index, ListView.Center)
        // All of it fits: already at the newest.
        Qt.callLater(function() { list.followNewest = list.nearNewest() })
    }

    function updateAtNewest() {
        if (!started)
            return
        Session.atNewest = !openingAtNew && followNewest
    }
    onFollowNewestChanged: updateAtNewest()
    onOpeningAtNewChanged: updateAtNewest()

    // Going to a message (a reply's original): it flashes once there. Not
    // loaded yet, older pages are loaded until it is; every few pages the
    // user is asked whether to keep going.
    property string highlightedId: ""
    property string seekingId: ""
    property int seekPages: 0
    readonly property int pagesBeforeAsking: 5

    function jumpToMessage(id) {
        const index = Session.messages.indexOfMessage(id)
        if (index >= 0) {
            seekingId = ""
            followNewest = false
            positionViewAtIndex(index, ListView.Center)
            highlightedId = id
            highlightTimer.restart()
            return
        }
        if (seekingId === "") {
            seekingId = id
            seekPages = 0
        }
        if (!Session.messages.hasOlder || !Session.permissions.canReadHistory) {
            seekingId = ""
            Session.showNotice(i18n.tr("The message could not be found."))
            return
        }
        if (seekPages > 0 && seekPages % pagesBeforeAsking === 0) {
            PopupUtils.open(farBackDialog, list)
            return
        }
        loadNextPage()
    }

    // A link to a message: gone to once its channel's messages are in.
    property string requestedId: ""

    function goToRequested() {
        if (requestedId === "" || Session.loadingMessages || count === 0)
            return
        const id = requestedId
        requestedId = ""
        jumpToMessage(id)
    }

    function loadNextPage() {
        seekPages++
        Session.loadOlderMessages()
    }

    Timer {
        id: highlightTimer
        interval: 1500
        onTriggered: list.highlightedId = ""
    }

    Connections {
        target: Session
        // A page arrived: look again.
        function onLoadingMessagesChanged() {
            if (!Session.loadingMessages && list.seekingId !== "")
                Qt.callLater(list.jumpToMessage, list.seekingId)
            if (list.openingAtNew)
                Qt.callLater(list.openAtNew)
            if (list.requestedId !== "")
                Qt.callLater(list.goToRequested)
        }
        function onCurrentChannelChanged() { list.seekingId = "" }
        function onMessageRequested(messageId) {
            list.openingAtNew = false
            list.followNewest = false
            list.requestedId = messageId
            Qt.callLater(list.goToRequested)
        }
        function onChannelOpened() {
            list.requestedId = ""
            if (Session.atNewest) {
                list.scrollToNewest()
            } else {
                list.openingAtNew = true
                list.followNewest = false
                Qt.callLater(list.openAtNew)
            }
        }
    }

    Component {
        id: farBackDialog

        Dialog {
            id: dialog
            title: i18n.tr("The message is far back")
            text: i18n.tr("It isn't in the last %1 messages. Keep looking?").arg(list.count)

            Button {
                text: i18n.tr("Keep looking")
                color: theme.palette.normal.positive
                onClicked: {
                    PopupUtils.close(dialog)
                    list.loadNextPage()
                }
            }

            Button {
                text: i18n.tr("Stop")
                onClicked: {
                    list.seekingId = ""
                    PopupUtils.close(dialog)
                }
            }
        }
    }

    // The part on screen, for rows that only play GIFs while shown. Updated
    // a few times a second while scrolling rather than every frame.
    property real visibleTop: 0
    property real visibleBottom: 0

    function updateVisibleRange() {
        visibleTop = contentY
        visibleBottom = contentY + height
    }

    clip: true
    model: Session.messages

    // The theme's colours for formatted text (code, subtext, spoilers),
    // built into each message's text by the model.
    Binding {
        target: Session.messages
        property: "palette"
        value: ({
            "muted": theme.palette.normal.backgroundSecondaryText.toString(),
            "code": Qt.tint(theme.palette.normal.background, "#24808080").toString(),
            "spoiler": Qt.tint(theme.palette.normal.background, "#b0808080").toString(),
            "text": theme.palette.normal.backgroundText.toString(),
            "link": theme.palette.normal.activity.toString(),
        })
    }
    verticalLayoutDirection: ListView.BottomToTop
    // Rows are built ahead of the finger in the background.
    cacheBuffer: units.gu(150)

    // On a phone the chat page (and this list) comes after the channel
    // was opened: start as Session::channelOpened would have. Until then
    // it doesn't follow the newest message or mark anything read.
    property bool started: false
    Component.onCompleted: {
        started = true
        updateVisibleRange()
        if (!Session.atNewest) {
            openingAtNew = true
            followNewest = false
            Qt.callLater(openAtNew)
        } else {
            scrollToNewest()
        }
    }
    onContentYChanged: {
        // Dragged away from the newest, even slowly: stop following it, or
        // rows growing as they are laid out would pull the view back down.
        if (moving && followNewest && !nearNewest())
            followNewest = false
        if (!moving)
            updateVisibleRange()
    }
    onMovementEnded: {
        followNewest = nearNewest()
        updateVisibleRange()
    }
    onFlickEnded: followNewest = nearNewest()
    onCountChanged: {
        if (!started)
            return
        if (requestedId !== "")
            Qt.callLater(goToRequested)
        else if (openingAtNew)
            Qt.callLater(openAtNew)
        else if (followNewest)
            scrollToNewest()
    }
    onContentHeightChanged: {
        if (followNewest && started)
            scrollToNewest()
        updateVisibleRange()
    }
    onHeightChanged: {
        if (followNewest && started)
            scrollToNewest()
        updateVisibleRange()
    }
    // The visual top is atYBeginning.
    onAtYBeginningChanged: {
        if (atYBeginning && !followNewest && !openingAtNew && count > 0
                && Session.messages.hasOlder && !Session.loadingMessages)
            Session.loadOlderMessages()
    }

    Timer {
        running: list.moving
        interval: 250
        repeat: true
        triggeredOnStart: true
        onTriggered: list.updateVisibleRange()
    }

    delegate: MessageDelegate {
        width: list.width
        onReplyRequested: function(messageId, author, text) { list.replyRequested(messageId, author, text) }
        onJumpRequested: function(messageId) { list.jumpToMessage(messageId) }
        onProfileRequested: function(userId) { list.profileRequested(userId) }
        onReactRequested: function(messageId, caller) { list.reactRequested(messageId, caller) }
        onEditRequested: function(messageId, text) { list.editRequested(messageId, text) }
        onDeleteRequested: function(messageId) { list.deleteRequested(messageId) }
        onMediaOpened: function(media) { list.mediaOpened(media) }
    }

    // Above the oldest message (bottom-to-top).
    footer: Item {
        width: list.width
        // Room for a long name in "This is the beginning of..." too.
        height: Math.max(units.gu(6), beginning.height + units.gu(3))

        Label {
            anchors.centerIn: parent
            width: parent.width - units.gu(4)
            visible: Session.currentChannelId !== "" && !Session.permissions.canReadHistory
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
            text: i18n.tr("You don't have permission to read earlier messages in this channel")
            color: theme.palette.normal.backgroundSecondaryText
        }

        Button {
            anchors.centerIn: parent
            visible: Session.messages.hasOlder && Session.permissions.canReadHistory
            text: Session.loadingMessages ? i18n.tr("Loading...") : i18n.tr("Load older messages")
            enabled: !Session.loadingMessages
            onClicked: Session.loadOlderMessages()
        }

        Label {
            id: beginning
            anchors.centerIn: parent
            width: parent.width - units.gu(4)
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.Wrap
            visible: Session.messages.reachedStart && list.count > 0 && Session.permissions.canReadHistory
            text: Session.inDirectMessages
                  ? i18n.tr("This is the beginning of your conversation with %1").arg(Session.currentChannelName)
                  : i18n.tr("This is the beginning of #%1").arg(Session.currentChannelName)
            color: theme.palette.normal.backgroundSecondaryText
        }
    }

    ActivityIndicator {
        anchors.centerIn: parent
        running: Session.loadingMessages && (list.count === 0 || list.seekingId !== "")
    }
}
