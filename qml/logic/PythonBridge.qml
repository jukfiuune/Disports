import QtQuick 2.7
import io.thp.pyotherside 1.4
import Disports 1.0

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
    signal messageReaction(var data)
    signal readyForInit()
    signal callUpdate(var data)
    signal callDelete(var data)
    signal voiceStateUpdate(var data)
    signal voiceLog(var data)
    signal voiceStartRequested()
    signal voiceStopRequested()
    signal voiceSpeakerRequested(var data)
    signal voiceMuteRequested(var data)

    Component.onCompleted: {
        addImportPath(Qt.resolvedUrl("../../src/"))

        // Register the C++ VoiceAudio singleton with the Python layer so that
        // qt_audio.py can call startAudio(), pushPlaybackPCM(), etc. directly
        // without crossing the QML event loop in the audio hot path.
        addImportPath(Qt.resolvedUrl("../../lib/"))

        importModule("discord_client", function() {
            console.log("discord_client loaded")

            // Hand the AudioPipe capsule to Python.  getAudioPipeCapsule()
            // runs on the main thread (safe), returns a PyCapsule wrapping
            // the raw AudioPipe*.  All subsequent audio I/O uses that pointer
            // directly via ctypes — zero Qt main-thread involvement.
            var capsule = VoiceAudio.getAudioPipeCapsule()
            call("discord_client.set_audio_pipe_capsule",
                 [capsule], function() {
                console.log("AudioPipe capsule registered with Python")
            })

            // All setHandler calls must be inside this callback —
            // pyotherside will not route events from a module that
            // hasn't finished importing yet.
            setHandler("ready",              ready)
            setHandler("private_channels",   privateChannels)
            setHandler("message_create",     messageCreate)
            setHandler("channel_unread",     channelUnread)
            setHandler("message_update",     messageUpdate)
            setHandler("message_delete",     messageDelete)
            setHandler("message_bulk_delete",messageBulkDelete)
            setHandler("typing",             typing)
            setHandler("presence",           presence)
            setHandler("gateway_log",        gatewayLog)
            setHandler("qr_login_image",     qrLoginImage)
            setHandler("qr_login_pending",   qrLoginPending)
            setHandler("qr_login_token",     qrLoginToken)
            setHandler("qr_login_error",     qrLoginError)
            setHandler("guild_channels",     guildChannels)
            setHandler("guild_sidebar",      guildSidebar)
            setHandler("guild_member_chunk", guildMemberChunk)
            setHandler("message_reaction",   messageReaction)
            setHandler("call_update",        callUpdate)
            setHandler("call_delete",        callDelete)
            setHandler("voice_state_update", voiceStateUpdate)
            setHandler("voice_log",          function(data) {
                dbgLog("VOICE: " + (data && data.message ? data.message : JSON.stringify(data)))
                voiceLog(data)
            })
            setHandler("voice_start",        voiceStartRequested)
            setHandler("voice_stop",         voiceStopRequested)
            setHandler("voice_speaker",      voiceSpeakerRequested)
            setHandler("voice_mute",         voiceMuteRequested)

            // Signal QML that Python is ready — only after everything
            // above is wired up, so callers can safely invoke functions.
            readyForInit()
        })
    }

    onError: console.log("Python error: " + traceback)
}
