import QtQuick 2.7

QtObject {
    property var appState
    property var chatLogic
    property var dmContactModel
    property var dmGroupModel
    property var dmChannelModel

    function rebuildDmChannelModel() {
        var merged = []
        var i
        var dmUnreads = 0

        for (i = 0; i < dmContactModel.count; i++) {
            var contact = dmContactModel.get(i)
            if (contact.unread > 0) dmUnreads++
            merged.push({
                "channelId": contact.channelId || "",
                "name": contact.name || "",
                "unread": contact.unread || 0,
                "itemType": "contact",
                "status": contact.status || "offline",
                "iconName": "",
                "sortKey": contact.sortKey || 0,
                "contactId": contact.contactId || ""
            })
        }

        for (i = 0; i < dmGroupModel.count; i++) {
            var group = dmGroupModel.get(i)
            if (group.unread > 0) dmUnreads++
            merged.push({
                "channelId": group.channelId || "",
                "name": group.name || "",
                "unread": group.unread || 0,
                "itemType": "group",
                "status": "",
                "iconName": "contact-group",
                "sortKey": group.sortKey || 0,
                "contactId": ""
            })
        }

        merged.sort(function(a, b) {
            var aKey = Number(a.sortKey || 0)
            var bKey = Number(b.sortKey || 0)
            if (aKey === bKey)
                return (a.name || "").localeCompare(b.name || "")
            return bKey - aKey
        })

        chatLogic.replaceModel(dmChannelModel, merged)
        appState.totalDmUnread = dmUnreads
    }

    function updateContactStatus(userId, status) {
        var i
        for (i = 0; i < dmContactModel.count; i++) {
            if (dmContactModel.get(i).contactId === userId) {
                dmContactModel.setProperty(i, "status", status)
                break
            }
        }

        for (i = 0; i < dmChannelModel.count; i++) {
            if (dmChannelModel.get(i).contactId === userId) {
                dmChannelModel.setProperty(i, "status", status)
                return
            }
        }
    }
}
