import QtQuick 2.7
import io.thp.pyotherside 1.4

Python {
    id: python
    
    signal ready(var data)
    signal privateChannels(var data)
    signal messageCreate(var msg)
    signal channelUnread(var data)
    signal messageUpdate(var msg)
    signal messageDelete(var msg)
    signal messageBulkDelete(var msg)
    signal typing(var data)
    signal presence(var data)
    signal gatewayLog(var data)
    signal qrLoginImage(var data)
    signal qrLoginPending(var data)
    signal qrLoginToken(var data)
    signal qrLoginError(var data)
    signal guildChannels(var data)
    signal guildSidebar(var data)
    signal guildMemberChunk(var data)
    signal readyForInit()

    Component.onCompleted: {
        addImportPath(Qt.resolvedUrl("../../src/"))
        importModule("discord_client", function() {
            console.log("discord_client loaded")
            readyForInit()
        })
        
        setHandler("ready", function(data) { ready(data) })
        setHandler("private_channels", function(data) { privateChannels(data) })
        setHandler("message_create", function(msg) { messageCreate(msg) })
        setHandler("channel_unread", function(data) { channelUnread(data) })
        setHandler("message_update", function(msg) { messageUpdate(msg) })
        setHandler("message_delete", function(msg) { messageDelete(msg) })
        setHandler("message_bulk_delete", function(msg) { messageBulkDelete(msg) })
        setHandler("typing", function(data) { typing(data) })
        setHandler("presence", function(data) { presence(data) })
        setHandler("gateway_log", function(data) { gatewayLog(data) })
        setHandler("qr_login_image", function(data) { qrLoginImage(data) })
        setHandler("qr_login_pending", function(data) { qrLoginPending(data) })
        setHandler("qr_login_token", function(data) { qrLoginToken(data) })
        setHandler("qr_login_error", function(data) { qrLoginError(data) })
        setHandler("guild_channels", function(data) { guildChannels(data) })
        setHandler("guild_sidebar", function(data) { guildSidebar(data) })
        setHandler("guild_member_chunk", function(data) { guildMemberChunk(data) })
    }
    
    onError: console.log("Python error: " + traceback)
}
