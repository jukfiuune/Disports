import QtQuick 2.7
import QtMultimedia 5.12

Item {
    id: voiceAudioBridge
    property var python

    AudioOutput { id: audioOut }
    AudioInput  { 
        id: audioIn 
        onAudioFrameAvailable: function(frame) {
            if (voiceAudioBridge.python) {
                voiceAudioBridge.python.call("discord_client._on_capture_frame", [Qt.btoa(frame)], function(){})
            }
        }
    }

    Connections {
        target: voiceAudioBridge.python
        onVoiceStartRequested: { audioOut.start(); audioIn.start(); }
        onVoiceStopRequested: { audioOut.stop(); audioIn.stop(); }
        onVoicePcmRx: function(data) { audioOut.push(Qt.atob(data.b64)); }
        onVoiceMuteRequested: function(data) { audioIn.muted = data.enabled; }
    }
}
