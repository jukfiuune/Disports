import QtQuick 2.9
import Lomiri.Components 1.3

Item {
    id: callScreen
    anchors.fill: parent
    visible: activeCall !== null
    z: 1000

    property var activeCall: null // { channelId, guildId, name, type, participants: [{id, avatarUrl, name}] }
    property bool isSpeakerphone: false
    property bool isMuted: false

    signal speakerphoneToggled(bool enabled)
    signal hangupRequested(string guildId)

    Rectangle {
        anchors.fill: parent
        color: theme.palette.normal.background
        opacity: 0.96
    }

    // Call Header
    Column {
        id: headerCol
        anchors.top: parent.top
        anchors.topMargin: units.gu(8)
        anchors.horizontalCenter: parent.horizontalCenter
        spacing: units.gu(2)

        Label {
            text: activeCall ? activeCall.name : i18n.tr("Unknown Call")
            color: theme.palette.normal.backgroundText
            fontSize: "x-large"
            font.weight: Font.DemiBold
            anchors.horizontalCenter: parent.horizontalCenter
        }

        Label {
            id: durationLabel
            text: "00:00"
            color: theme.palette.normal.backgroundSecondaryText
            fontSize: "medium"
            anchors.horizontalCenter: parent.horizontalCenter

            property int secondsElapsed: 0
            Timer {
                interval: 1000
                running: callScreen.visible
                repeat: true
                onTriggered: {
                    durationLabel.secondsElapsed++
                    var m = Math.floor(durationLabel.secondsElapsed / 60)
                    var s = durationLabel.secondsElapsed % 60
                    durationLabel.text = (m < 10 ? "0" : "") + m + ":" + (s < 10 ? "0" : "") + s
                }
                onRunningChanged: if (!running) durationLabel.secondsElapsed = 0
            }
        }
    }

    // Participants Avatars
    Item {
        anchors.centerIn: parent
        width: parent.width - units.gu(4)
        height: units.gu(22)

        // Single Participant (1-on-1)
        LomiriShape {
            id: soloAvatar
            visible: activeCall && activeCall.participants && activeCall.participants.length === 1
            anchors.centerIn: parent
            width: units.gu(16)
            height: units.gu(16)
            radius: "medium"
            aspect: LomiriShape.Flat

            Image {
                anchors.fill: parent
                source: soloAvatar.visible ? activeCall.participants[0].avatarUrl : ""
                fillMode: Image.PreserveAspectCrop
            }
        }

        // Multiple Participants
        Row {
            visible: activeCall && activeCall.participants && activeCall.participants.length > 1
            anchors.centerIn: parent
            spacing: units.gu(1.5)

            Repeater {
                model: activeCall && activeCall.participants ? Math.min(activeCall.participants.length, 4) : 0
                delegate: LomiriShape {
                    width: units.gu(10)
                    height: units.gu(10)
                    radius: "medium"
                    aspect: LomiriShape.Flat

                    Image {
                        anchors.fill: parent
                        source: activeCall.participants[index].avatarUrl
                        fillMode: Image.PreserveAspectCrop
                    }
                }
            }

            LomiriShape {
                visible: activeCall && activeCall.participants && activeCall.participants.length > 4
                width: units.gu(10)
                height: units.gu(10)
                radius: "medium"
                aspect: LomiriShape.Flat
                color: theme.palette.normal.base

                Label {
                    anchors.centerIn: parent
                    text: activeCall && activeCall.participants ? "+" + (activeCall.participants.length - 4) : ""
                    color: theme.palette.normal.baseText
                    fontSize: "large"
                    font.weight: Font.DemiBold
                }
            }
        }
    }

    // Call Controls
    Row {
        anchors.bottom: parent.bottom
        anchors.bottomMargin: units.gu(8)
        anchors.horizontalCenter: parent.horizontalCenter
        spacing: units.gu(4)

        // Speakerphone Toggle
        LomiriShape {
            id: speakerBtn
            width: units.gu(8)
            height: units.gu(8)
            radius: "medium"
            color: isSpeakerphone ? theme.palette.normal.focus : theme.palette.normal.base

            Icon {
                anchors.centerIn: parent
                width: units.gu(4)
                height: units.gu(4)
                name: "audio-volume-high"
                color: isSpeakerphone ? "white" : theme.palette.normal.baseText
            }

            MouseArea {
                anchors.fill: parent
                onClicked: {
                    isSpeakerphone = !isSpeakerphone
                    callScreen.speakerphoneToggled(isSpeakerphone)
                }
            }
        }

        // Mute Toggle
        LomiriShape {
            id: muteBtn
            width: units.gu(8)
            height: units.gu(8)
            radius: "medium"
            color: isMuted ? theme.palette.normal.focus : theme.palette.normal.base

            Icon {
                anchors.centerIn: parent
                width: units.gu(4)
                height: units.gu(4)
                name: isMuted ? "microphone-muted" : "microphone"
                color: isMuted ? "white" : theme.palette.normal.baseText
            }

            MouseArea {
                anchors.fill: parent
                onClicked: {
                    isMuted = !isMuted
                }
            }
        }

        // Hangup Button
        LomiriShape {
            id: hangupBtn
            width: units.gu(8)
            height: units.gu(8)
            radius: "medium"
            color: theme.palette.normal.negative

            Icon {
                anchors.centerIn: parent
                width: units.gu(4)
                height: units.gu(4)
                name: "call-stop"
                color: "white"
            }

            MouseArea {
                anchors.fill: parent
                onClicked: {
                    if (activeCall) {
                        callScreen.hangupRequested(activeCall.guildId || null)
                        activeCall = null
                    }
                }
            }
        }
    }
}
