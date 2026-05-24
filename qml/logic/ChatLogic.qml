import QtQuick 2.7

QtObject {
    property var appState
    property var python
    property var appSettings
    property var pageStack
    property var unreadLogic

    property var chatMessageModel
    property var channelModel

    property var chatPageComp
    property var _messageIndexById: ({})

    signal deleteConfirmRequested(string messageId)

    function openChat(channelId, name) {
        if (!appState.pythonReady)
            return
        appState.activeChannelId = channelId
        appState.activeChannelName = name
        appState.typingNotice = ""
        appState.draftText = ""
        clearReplyTarget()
        replaceModel(chatMessageModel, [])
        python.call("discord_client.set_active_channel", [channelId], function() {})
        python.call("discord_client.fetch_messages", [channelId, 50, ""], function(messages) {
            messages = messages || []
            replaceModel(chatMessageModel, messages)
            if (!appState.isWideLayout && pageStack.currentPage.objectName !== "chatPage")
                pageStack.push(chatPageComp)

            if (messages.length > 0) {
                var latestId = messages[0].messageId
                python.call("discord_client.mark_seen", [channelId, latestId], function(){})
                if ((messages[0].authorId || "") !== appState.myUserId)
                    python.call("discord_client.ack_message", [channelId, latestId], function(){})
            }
        })
    }

    function openChannelById(channelId) {
        if (!appState.pythonReady || channelId === "")
            return

        python.call("discord_client.resolve_channel", [channelId], function(result) {
            if (!result || !result.ok || !result.channel) {
                console.log("Resolve channel failed: " + (result ? result.error : "unknown error"))
                return
            }

            var channel = result.channel
            var guildId = channel.guildId || ""
            var channelName = channel.name || ""
            if (guildId !== "") {
                appState.mode = "server"
                appState.activeServerId = guildId
                appState.activeServerName = channel.guildName || appState.activeServerName
                replaceModel(channelModel, []) // Clear stale channels immediately
                python.call("discord_client.fetch_guild_channels", [guildId], function(channels) {
                    replaceModel(channelModel, channels || [])
                    openChat(channelId, channelName)
                })
                return
            }

            appState.mode = "dm"
            openChat(channelId, channelName)
        })
    }

    function fetchOlderMessages() {
        if (!appState.pythonReady || appState.loadingOlderMessages || chatMessageModel.count === 0 || appState.activeChannelId === "") return;

        appState.loadingOlderMessages = true;
        var oldestId = chatMessageModel.get(chatMessageModel.count - 1).messageId || "";

        python.call("discord_client.fetch_messages", [appState.activeChannelId, 50, oldestId], function(messages) {
            if (messages && messages.length > 0) {
                var oldCount = chatMessageModel.count;
                _applyGroupingToItems(messages);
                for (var i = 0; i < messages.length; i++) {
                    chatMessageModel.append(messages[i]);
                }
                rebuildMessageIndex()
                if (oldCount > 0)
                    _updateGroupingAt(oldCount - 1)
            }
            appState.loadingOlderMessages = false;
        });
    }

    function refreshActiveChannel() {
        if (!appState.pythonReady || appState.activeChannelId === "")
            return
        python.call("discord_client.fetch_messages", [appState.activeChannelId, 50, ""], function(messages) {
            replaceModel(chatMessageModel, messages || [])
        })
    }

    function postMessage(content, replyMessageId) {
        if (!appState.pythonReady || content.trim() === "" || appState.activeChannelId === "")
            return

        var pendingId = "pending_" + Date.now()
        var pendingMsg = {
            messageId: pendingId,
            channelId: appState.activeChannelId,
            authorId: appState.myUserId,
            author: appState.myUsername || "You",
            timestamp: new Date().toLocaleTimeString(Qt.locale(), "HH:mm"),
            rawTimestamp: new Date().toISOString(),
            body: content,
            rawBody: content,
            displayKind: "default",
            discordMessageType: "Default",
            medias: [],
            richEmbeds: [],
            reactionsJson: "[]",
            hasReply: replyMessageId !== "",
            replyMessageId: replyMessageId || "",
            replyAuthor: appState.replyAuthor || "",
            replyBody: appState.replyBody || "",
            hasForwarded: false,
            forwardedLabel: "",
            forwardedAuthor: "",
            forwardedBody: "",
            authorBlocked: false,
            blockedVisibility: "show",
            isPending: true
        }
        chatMessageModel.insert(0, pendingMsg)
        rebuildMessageIndex()

        appState.draftText = ""
        clearReplyTarget()

        python.call("discord_client.send_message", [appState.activeChannelId, content, replyMessageId || ""], function(result) {
            if (!result || !result.ok) {
                console.log("Send failed: " + (result ? result.error : "unknown"))
                // Remove the pending placeholder on failure
                removeMessage(pendingId)
                return
            }
            removeMessage(pendingId)
            upsertMessage(result.message)
        })
    }

    function editMessage(messageId, newContent) {
        if (!appState.pythonReady || messageId === "" || newContent.trim() === "" || appState.activeChannelId === "")
            return

        python.call("discord_client.edit_message", [appState.activeChannelId, messageId, newContent], function(result) {
            if (!result || !result.ok) {
                console.log("Edit failed: " + (result ? result.error : "unknown error"))
                return
            }
            upsertMessage(result.message)
        })
    }

    function confirmDeleteMessage(messageId) {
        deleteConfirmRequested(messageId)
    }

    function replaceModel(model, items) {
        if (!model)
            return
        if (!items)
            items = []
            
        if (model === chatMessageModel)
            _applyGroupingToItems(items)
        
        if (model.count > 0 && model.count === items.length) {
            for (var i = 0; i < items.length; i++) {
                var newItem = items[i]
                var keys = Object.keys(newItem)
                for (var k = 0; k < keys.length; k++) {
                    var key = keys[k]
                    model.setProperty(i, key, newItem[key])
                }
            }
        } else {
            model.clear()
            for (var j = 0; j < items.length; j++)
                model.append(items[j])
        }

        if (model === chatMessageModel)
            rebuildMessageIndex()
        if (unreadLogic)
            unreadLogic.notifyListReplaced(model)
    }

    function rebuildMessageIndex() {
        var map = {}
        if (chatMessageModel) {
            for (var i = 0; i < chatMessageModel.count; i++) {
                var id = chatMessageModel.get(i).messageId || ""
                if (id !== "")
                    map[id] = i
            }
        }
        _messageIndexById = map
    }

    function messageIndex(messageId) {
        if (!chatMessageModel || !messageId)
            return -1
        var idx = _messageIndexById[messageId]
        if (idx !== undefined && idx < chatMessageModel.count) {
            if ((chatMessageModel.get(idx).messageId || "") === messageId)
                return idx
        }
        rebuildMessageIndex()
        idx = _messageIndexById[messageId]
        return idx !== undefined ? idx : -1
    }

    function upsertMessage(message) {
        if (!message || message.channelId !== appState.activeChannelId)
            return

        if ((message.authorId || "") === appState.myUserId && !(message.isPending)) {
            var pendingIdx = _findPendingByContent(message.body || "")
            if (pendingIdx >= 0) {
                chatMessageModel.remove(pendingIdx)
                rebuildMessageIndex()
            }
        }

        var idx = messageIndex(message.messageId)
        if (idx >= 0) {
            chatMessageModel.set(idx, message)
            _updateGroupingAt(idx)
            return
        }
        chatMessageModel.insert(0, message)
        rebuildMessageIndex()
        _updateGroupingAt(0)
    }

    function _computeGrouping(current, older) {
        if (!current || !older) return false;
        if ((current.authorId || "") !== (older.authorId || "")) return false;
        if ((current.displayKind || "default") === "system" || (older.displayKind || "default") === "system") return false;
        if (!!current.hasReply || !!current.hasForwarded) return false;
        var currentTs = new Date(current.rawTimestamp || "").getTime();
        var olderTs = new Date(older.rawTimestamp || "").getTime();
        if (isNaN(currentTs) || isNaN(olderTs)) return false;
        return (currentTs - olderTs) < 300000 && (currentTs - olderTs) >= 0;
    }

    function _applyGroupingToItems(items) {
        for (var i = 0; i < items.length; i++) {
            var current = items[i];
            var older = i + 1 < items.length ? items[i + 1] : null;
            var newer = i - 1 >= 0 ? items[i - 1] : null;
            current.isGrouped = _computeGrouping(current, older);
            current.isGroupedWithNext = newer ? _computeGrouping(newer, current) : false;
        }
    }

    function _updateGroupingAt(idx) {
        if (!chatMessageModel || idx < 0 || idx >= chatMessageModel.count) return;
        var current = chatMessageModel.get(idx);
        var older = idx + 1 < chatMessageModel.count ? chatMessageModel.get(idx + 1) : null;
        var newer = idx - 1 >= 0 ? chatMessageModel.get(idx - 1) : null;
        
        var isGrouped = _computeGrouping(current, older);
        if (current.isGrouped !== isGrouped)
            chatMessageModel.setProperty(idx, "isGrouped", isGrouped);
            
        var isGroupedWithNext = newer ? _computeGrouping(newer, current) : false;
        if (current.isGroupedWithNext !== isGroupedWithNext)
            chatMessageModel.setProperty(idx, "isGroupedWithNext", isGroupedWithNext);
            
        if (older) {
            var olderIsGroupedWithNext = _computeGrouping(current, older);
            if (older.isGroupedWithNext !== olderIsGroupedWithNext)
                chatMessageModel.setProperty(idx + 1, "isGroupedWithNext", olderIsGroupedWithNext);
        }
        if (newer) {
            var newerIsGrouped = _computeGrouping(newer, current);
            if (newer.isGrouped !== newerIsGrouped)
                chatMessageModel.setProperty(idx - 1, "isGrouped", newerIsGrouped);
        }
    }

    function _findPendingByContent(content) {
        if (!chatMessageModel || content === "")
            return -1
        for (var i = 0; i < chatMessageModel.count; i++) {
            var item = chatMessageModel.get(i)
            if (!!item.isPending && (item.body || "") === content)
                return i
        }
        return -1
    }

    function removeMessage(messageId) {
        var idx = messageIndex(messageId)
        if (idx >= 0) {
            chatMessageModel.remove(idx)
            rebuildMessageIndex()
        }
    }

    function applyReactionUpdate(data) {
        if (!data || !data.messageId || data.channelId !== appState.activeChannelId)
            return
        var json = data.reactionsJson || "[]"
        var idx = messageIndex(data.messageId)
        if (idx >= 0)
            chatMessageModel.setProperty(idx, "reactionsJson", json)
    }

    function toggleReaction(messageId, apiString, alreadyReacted) {
        if (!appState.pythonReady || !messageId || !apiString || !appState.activeChannelId)
            return
        var channelId = appState.activeChannelId
        if (alreadyReacted) {
            python.call("discord_client.remove_reaction", [channelId, messageId, apiString], function(result) {
                if (result && !result.ok)
                    console.log("Remove reaction failed: " + result.error)
            })
        } else {
            python.call("discord_client.add_reaction", [channelId, messageId, apiString], function(result) {
                if (result && !result.ok)
                    console.log("Add reaction failed: " + result.error)
            })
        }
    }

    function setReplyTarget(messageId) {
        var idx = messageIndex(messageId)
        var message = idx >= 0 ? chatMessageModel.get(idx) : null
        if (!message) return

        appState.replyMessageId = message.messageId || ""
        appState.replyAuthor = message.author || ""
        if (message.body && message.body.trim() !== "")
            appState.replyBody = message.body
        else if (message.messageType === "image")
            appState.replyBody = i18n.tr("Image")
        else if (message.messageType === "video")
            appState.replyBody = i18n.tr("Video")
        else if (message.messageType === "audio")
            appState.replyBody = i18n.tr("Audio")
        else if (message.mediaFileName && message.mediaFileName !== "")
            appState.replyBody = message.mediaFileName
        else
            appState.replyBody = i18n.tr("Message")
    }

    function clearReplyTarget() {
        appState.replyMessageId = ""
        appState.replyAuthor = ""
        appState.replyBody = ""
    }
}
