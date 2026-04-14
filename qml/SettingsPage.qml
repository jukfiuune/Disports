/*
 * SettingsPage.qml
 *
 * Pushed from the main page header's settings action.
 * Houses token input and other app preferences.
 */

import QtQuick 2.7
import Lomiri.Components 1.3
import Qt.labs.settings 1.0

Page {
    id: settingsPage
    property var stack
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

    Settings {
        id: appSettings
        property int themeMode: 2
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
                    if (appSettings.themeMode !== themeMode) {
                        appSettings.themeMode = themeMode
                        settingsPage.themeModeSelected(themeMode)
                    }
                }
                Component.onCompleted: {
                    themeModel.initialize()
                    for (var i = 0; i < themeModel.count; i++) {
                        if (themeModel.get(i).value === appSettings.themeMode) {
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

            Button {
                width: parent.width
                color: theme.palette.normal.negative
                text: i18n.tr("Log out")
                onClicked: {
                    settingsPage.logoutRequested()
                    settingsPage.stack.pop()
                }
            }

            // ── About ─────────────────────────────────────────────────────
            Rectangle {
                width: parent.width; height: units.dp(1)
                color: theme.palette.normal.base
            }

            Label {
                text: i18n.tr("Disports — a Discord client for Ubuntu Touch")
                font.pixelSize: units.gu(1.5)
                color: theme.palette.normal.backgroundSecondaryText
                wrapMode: Text.WordWrap
                width: parent.width
            }
        }
    }
}
