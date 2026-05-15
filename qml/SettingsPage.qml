import QtQuick 2.7
import Lomiri.Components 1.3
import Qt.labs.settings 1.0

Page {
    id: settingsPage
    property var stack
    property var settingsObject
    signal themeModeSelected(int themeMode)
    signal logoutRequested()

    ListModel {
        id: themeModel
        function initialize() {
            themeModel.append({ text: i18n.tr("Follow system"), value: 2 })
            themeModel.append({ text: i18n.tr("Light"), value: 0 })
            themeModel.append({ text: i18n.tr("Dark"), value: 1 })
        }
    }

    ListModel {
        id: blockedVisibilityModel
        function initialize() {
            blockedVisibilityModel.append({ text: i18n.tr("Hide completely"), value: "hide" })
            blockedVisibilityModel.append({ text: i18n.tr("Reveal placeholder"), value: "reveal" })
            blockedVisibilityModel.append({ text: i18n.tr("Show normally"), value: "show" })
        }
    }

    readonly property var settingsStore: settingsPage.settingsObject ? settingsPage.settingsObject : localSettings

    Settings {
        id: localSettings
        property int themeMode: 2
        property bool inlineGifPlayback: true
        property string blockedMessageVisibility: "reveal"
    }

    header: PageHeader {
        title: i18n.tr("Settings")
        leadingActionBar.actions: [
            Action {
                iconName: "back"
                text: i18n.tr("Back")
                onTriggered: settingsPage.stack.pop()
            }
        ]
    }

    Flickable {
        anchors {
            top: settingsPage.header.bottom
            left: parent.left; right: parent.right; bottom: parent.bottom
            margins: units.gu(2)
        }
        contentHeight: settingsCol.height
        clip: true

        Column {
            id: settingsCol
            width: parent.width
            spacing: units.gu(2)

            Label {
                text: i18n.tr("Theme")
                font.pixelSize: units.gu(1.6)
                font.bold: true
            }

            OptionSelector {
                id: themeChooser
                width: parent.width
                model: themeModel
                containerHeight: itemHeight * themeModel.count
                delegate: OptionSelectorDelegate {
                    text: model.text
                }
                onDelegateClicked: {
                    var themeMode = themeModel.get(index).value
                    if (settingsStore.themeMode !== themeMode) {
                        settingsStore.themeMode = themeMode
                        settingsPage.themeModeSelected(themeMode)
                    }
                }
                Component.onCompleted: {
                    themeModel.initialize()
                    for (var i = 0; i < themeModel.count; i++) {
                        if (themeModel.get(i).value === settingsStore.themeMode) {
                            themeChooser.selectedIndex = i
                            break
                        }
                    }
                }
            }

            Rectangle {
                width: parent.width; height: units.dp(1)
                color: theme.palette.normal.base
            }

            Item {
                width: parent.width
                height: units.gu(4.5)

                Label {
                    anchors {
                        left: parent.left
                        verticalCenter: parent.verticalCenter
                    }
                    text: i18n.tr("Autoplay GIFs")
                }

                Switch {
                    anchors {
                        right: parent.right
                        verticalCenter: parent.verticalCenter
                    }
                    checked: settingsStore.inlineGifPlayback
                    onCheckedChanged: settingsStore.inlineGifPlayback = checked
                }
            }

            Rectangle {
                width: parent.width; height: units.dp(1)
                color: theme.palette.normal.base
            }

            Label {
                text: i18n.tr("Blocked messages")
                font.pixelSize: units.gu(1.6)
                font.bold: true
            }

            OptionSelector {
                id: blockedChooser
                width: parent.width
                model: blockedVisibilityModel
                containerHeight: itemHeight * blockedVisibilityModel.count
                delegate: OptionSelectorDelegate {
                    text: model.text
                }
                onDelegateClicked: {
                    var mode = blockedVisibilityModel.get(index).value
                    if (settingsStore.blockedMessageVisibility !== mode) {
                        settingsStore.blockedMessageVisibility = mode
                    }
                }
                Component.onCompleted: {
                    blockedVisibilityModel.initialize()
                    for (var i = 0; i < blockedVisibilityModel.count; i++) {
                        if (blockedVisibilityModel.get(i).value === settingsStore.blockedMessageVisibility) {
                            blockedChooser.selectedIndex = i
                            break
                        }
                    }
                }
            }

            Rectangle {
                width: parent.width; height: units.dp(1)
                color: theme.palette.normal.base
            }

            Button {
                width: parent.width
                color: theme.palette.normal.negative
                text: i18n.tr("Log out")
                onClicked: {
                    settingsPage.logoutRequested()
                    settingsPage.stack.pop()
                }
            }

            // About
            Rectangle {
                width: parent.width; height: units.dp(1)
                color: theme.palette.normal.base
            }

            Label {
                text: i18n.tr("Disports - a Discord client for Ubuntu Touch")
                font.pixelSize: units.gu(1.5)
                color: theme.palette.normal.backgroundSecondaryText
                wrapMode: Text.WordWrap
                width: parent.width
            }
        }
    }
}
