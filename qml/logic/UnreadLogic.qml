import QtQuick 2.7

QtObject {
    property var appState
    property var serverModel
    property var dmContactModel
    property var dmGroupModel
    property var dmChannelModel
    property var channelModel

    property var _byChannel: ({})

    function rebuildChannelIndex() {
        var m = {}
        addModel(m, dmContactModel)
        addModel(m, dmGroupModel)
        addModel(m, dmChannelModel)
        addModel(m, channelModel)
        _byChannel = m
    }

    function addModel(map, model) {
        if (!model) return
        var i
        for (i = 0; i < model.count; i++) {
            var id = model.get(i).channelId
            if (id)
                map[id] = { model: model, index: i }
        }
    }

    function notifyListReplaced(m) {
        if (m === dmContactModel || m === dmGroupModel || m === dmChannelModel || m === channelModel)
            rebuildChannelIndex()
    }

    function recomputeFolderUnreadTotals() {
        if (!serverModel)
            return
        var sums = {}
        var i
        for (i = 0; i < serverModel.count; i++) {
            var row = serverModel.get(i)
            if (row.itemType !== "server" || !row.serverId)
                continue
            var fk = row.folderKey || ""
            if (fk === "")
                continue
            var u = row.unread || 0
            sums[fk] = (sums[fk] || 0) + u
        }
        for (i = 0; i < serverModel.count; i++) {
            var h = serverModel.get(i)
            if (h.itemType !== "folderHeader" || !h.folderKey)
                continue
            serverModel.setProperty(i, "folderUnread", sums[h.folderKey] || 0)
        }
    }

    function applyChannelUnread(data) {
        var cId = data.channelId
        var unread = data.unread
        var i
        if (data.dmUnread !== undefined)
            appState.totalDmUnread = data.dmUnread
        if (data.guildId !== undefined && data.guildId !== null && serverModel) {
            for (i = 0; i < serverModel.count; i++) {
                if (serverModel.get(i).serverId === data.guildId) {
                    serverModel.setProperty(i, "unread", data.guildUnread || 0)
                    break
                }
            }
        }
        var entry = _byChannel[cId]
        if (entry && entry.model && entry.index < entry.model.count) {
            if (entry.model.get(entry.index).channelId === cId) {
                entry.model.setProperty(entry.index, "unread", unread)
                recomputeFolderUnreadTotals()
                return
            }
        }
        var models = [dmContactModel, dmGroupModel, dmChannelModel, channelModel]
        for (var mi = 0; mi < models.length; mi++) {
            var mod = models[mi]
            if (!mod) continue
            for (i = 0; i < mod.count; i++) {
                if (mod.get(i).channelId === cId) {
                    mod.setProperty(i, "unread", unread)
                    rebuildChannelIndex()
                    recomputeFolderUnreadTotals()
                    return
                }
            }
        }
        recomputeFolderUnreadTotals()
    }
}
