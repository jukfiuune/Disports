import QtQuick 2.7

QtObject {
    property var appState
    property var serverModel
    property var dmContactModel
    property var dmGroupModel
    property var dmChannelModel
    property var channelModel

    property var _byChannel: ({})
    property var _byServer: ({})

    function rebuildChannelIndex() {
        var mc = {}
        addModel(mc, dmContactModel)
        addModel(mc, dmGroupModel)
        addModel(mc, dmChannelModel)
        addModel(mc, channelModel)
        _byChannel = mc
    }

    function rebuildServerIndex() {
        if (!serverModel) return
        var ms = {}
        for (var i = 0; i < serverModel.count; i++) {
            var sid = serverModel.get(i).serverId
            if (sid)
                ms[sid] = i
        }
        _byServer = ms
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
        if (m === serverModel)
            rebuildServerIndex()
    }

    function recomputeFolderUnreadTotals() {
        if (!serverModel)
            return
        var counts = {}
        var dots = {}
        var i
        for (i = 0; i < serverModel.count; i++) {
            var row = serverModel.get(i)
            if (row.itemType !== "server" || !row.serverId)
                continue
            var fk = row.folderKey || ""
            if (fk === "")
                continue
            var kind = row.unreadKind || "none"
            var u = Number(row.unread || 0)
            if (kind === "count")
                counts[fk] = (counts[fk] || 0) + u
            if (kind !== "none")
                dots[fk] = true
        }
        for (i = 0; i < serverModel.count; i++) {
            var h = serverModel.get(i)
            if (h.itemType !== "folderHeader" || !h.folderKey)
                continue
            var total = counts[h.folderKey] || 0
            var kindOut = total > 0 ? "count" : (dots[h.folderKey] ? "dot" : "none")
            serverModel.setProperty(i, "folderUnread", total)
            serverModel.setProperty(i, "folderUnreadKind", kindOut)
        }
    }

    function applyChannelUnread(data) {
        var cId = data.channelId
        var unread = data.unread
        var i
        if (data.dmUnread !== undefined)
            appState.totalDmUnread = data.dmUnread
        if (data.guildId && serverModel) {
            var sIdx = _byServer[data.guildId]
            if (sIdx !== undefined && sIdx < serverModel.count && serverModel.get(sIdx).serverId === data.guildId) {
                serverModel.setProperty(sIdx, "unread", data.guildUnread || 0)
                serverModel.setProperty(sIdx, "unreadKind", data.guildUnreadKind || ((data.guildUnread || 0) > 0 ? "count" : "none"))
            } else {
                for (i = 0; i < serverModel.count; i++) {
                    if (serverModel.get(i).serverId === data.guildId) {
                        serverModel.setProperty(i, "unread", data.guildUnread || 0)
                        serverModel.setProperty(i, "unreadKind", data.guildUnreadKind || ((data.guildUnread || 0) > 0 ? "count" : "none"))
                        rebuildServerIndex()
                        break
                    }
                }
            }
        }

        var entry = _byChannel[cId]
        if (entry && entry.model && entry.index < entry.model.count && entry.model.get(entry.index).channelId === cId) {
            entry.model.setProperty(entry.index, "unread", unread)
            entry.model.setProperty(entry.index, "unreadKind", data.unreadKind || ((unread || 0) > 0 ? "count" : "none"))
        } else {
            var models = [dmContactModel, dmGroupModel, dmChannelModel, channelModel]
            var found = false
            for (var mi = 0; mi < models.length; mi++) {
                var mod = models[mi]
                if (!mod) continue
                for (i = 0; i < mod.count; i++) {
                    if (mod.get(i).channelId === cId) {
                        mod.setProperty(i, "unread", unread)
                        mod.setProperty(i, "unreadKind", data.unreadKind || ((unread || 0) > 0 ? "count" : "none"))
                        rebuildChannelIndex()
                        found = true
                        break
                    }
                }
                if (found) break
            }
        }
        appState.sidebarRevision += 1
        recomputeFolderUnreadTotals()
    }
}
