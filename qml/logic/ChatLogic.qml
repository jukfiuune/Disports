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
                for (var i = 0; i < messages.length; i++) {
                    chatMessageModel.append(messages[i]);
                }
                rebuildMessageIndex()
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

        python.call("discord_client.send_message", [appState.activeChannelId, content, replyMessageId || ""], function(result) {
            if (!result || !result.ok) {
                console.log("Send failed: " + (result ? result.error : "unknown"))
                return
            }
            upsertMessage(result.message)
            appState.draftText = ""
            clearReplyTarget()
        })
    }

    function joinVoiceChannel(channelId) {
        // For guild voice channels, use the active server id.
        // For DM/group-DM voice calls the guild_id must be null.
        var guildId = (appState.mode === "server" && appState.activeServerId) ? appState.activeServerId : null
        python.call("discord_client.join_voice_channel", [guildId, channelId], function(result) {})
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
        model.clear()
        for (var i = 0; i < items.length; i++)
            model.append(items[i])
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

        var idx = messageIndex(message.messageId)
        if (idx >= 0) {
            chatMessageModel.set(idx, message)
            return
        }
        chatMessageModel.insert(0, message)
        rebuildMessageIndex()
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
