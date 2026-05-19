import QtQuick 2.7
import Disports 1.0

Item {
    id: voiceAudioBridge

    function startAudio() {
        VoiceAudio.startAudio()
    }

    function stopAudio() {
        VoiceAudio.stopAudio()
    }

    function setSpeakerphone(enabled) {
        VoiceAudio.setSpeakerphone(enabled)
    }

    function setMuted(enabled) {
        VoiceAudio.setMuted(enabled)
    }
}
