import QtQuick 2.7

QtObject {
    property var appSettings

    function applyThemePreference(themeMode) {
        appSettings.themeMode = themeMode
        switch (themeMode) {
        case 0:
            appSettings.uitkTheme = "Lomiri.Components.Themes.Ambiance"
            break
        case 1:
            appSettings.uitkTheme = "Lomiri.Components.Themes.SuruDark"
            break
        default:
            appSettings.uitkTheme = ""
            break
        }
    }
}
