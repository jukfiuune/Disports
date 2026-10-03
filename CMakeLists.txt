cmake_minimum_required(VERSION 3.21)
project(disports VERSION 1.0.0 LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

set(APP_NAME "disports")
set(APP_ID "disports.jukfiuu")

# The click's version: 1.0.0 when built from the tag v1.0.0, 1.0.0~beta1
# from v1.0.0-beta1 (git tags can't hold "~", and it sorts before 1.0.0),
# and 1.0.0.<commit> otherwise, so each build installs as a new version (and
# gets a fresh AppArmor profile).
set(APP_VERSION ${PROJECT_VERSION})
find_package(Git QUIET)
if(GIT_FOUND AND EXISTS ${CMAKE_CURRENT_SOURCE_DIR}/.git)
    # The build container runs as another user than the checkout's owner.
    set(GIT ${GIT_EXECUTABLE} -c safe.directory=* -C ${CMAKE_CURRENT_SOURCE_DIR})
    execute_process(COMMAND ${GIT} tag --points-at HEAD
        OUTPUT_VARIABLE TAGS OUTPUT_STRIP_TRAILING_WHITESPACE ERROR_QUIET)
    execute_process(COMMAND ${GIT} rev-parse --short=7 HEAD
        OUTPUT_VARIABLE COMMIT OUTPUT_STRIP_TRAILING_WHITESPACE ERROR_QUIET)
    string(REPLACE "." "\\." VERSION_PATTERN ${PROJECT_VERSION})
    string(REPLACE "\n" ";" TAGS "${TAGS}")
    set(RELEASE_VERSION "")
    foreach(TAG ${TAGS})
        if(TAG STREQUAL "v${PROJECT_VERSION}")
            set(RELEASE_VERSION ${PROJECT_VERSION})
        elseif(TAG MATCHES "^v${VERSION_PATTERN}-([A-Za-z0-9.]+)$" AND NOT RELEASE_VERSION)
            set(RELEASE_VERSION "${PROJECT_VERSION}~${CMAKE_MATCH_1}")
        endif()
    endforeach()
    if(RELEASE_VERSION)
        set(APP_VERSION ${RELEASE_VERSION})
    elseif(COMMIT)
        set(APP_VERSION ${PROJECT_VERSION}.${COMMIT})
    endif()
    # Configure again after each commit.
    if(EXISTS ${CMAKE_CURRENT_SOURCE_DIR}/.git/logs/HEAD)
        set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS ${CMAKE_CURRENT_SOURCE_DIR}/.git/logs/HEAD)
    endif()
endif()
message(STATUS "Disports ${APP_VERSION}")

option(CLICK_MODE "Install as an Ubuntu Touch click package" ON)

find_package(Qt6 6.4 REQUIRED COMPONENTS Core Gui Qml Quick Network WebSockets DBus)
find_package(OpenSSL REQUIRED)

qt_standard_project_setup(REQUIRES 6.8)

option(DISPORTS_SANITIZE "Build with AddressSanitizer, LeakSanitizer and UBSan (tests)" OFF)
option(DISPORTS_TEST_HOOKS "Build the hooks tools/test drives the app with" OFF)

add_subdirectory(third_party)

# Our own code only: third-party libraries are linked in uninstrumented.
# See tools/test/check.sh.
if(DISPORTS_SANITIZE)
    add_compile_options(-fsanitize=address,undefined -fno-omit-frame-pointer -g)
    add_link_options(-fsanitize=address,undefined)
endif()

# The client core, see src/discord/CMakeLists.txt.
add_subdirectory(src/discord)

qt_add_executable(disports
    src/main.cpp
    src/Captcha.cpp src/Captcha.h
    src/ChannelInfo.cpp src/ChannelInfo.h
    src/ChannelPermissions.cpp src/ChannelPermissions.h
    src/DiscordUrls.cpp src/DiscordUrls.h
    src/GatewayConnection.cpp src/GatewayConnection.h
    src/Log.cpp src/Log.h
    src/MentionSuggester.cpp src/MentionSuggester.h
    src/MessageFormatter.cpp src/MessageFormatter.h
    src/MessageSender.cpp src/MessageSender.h
    src/OfflineCache.cpp src/OfflineCache.h
    src/ImageCache.cpp src/ImageCache.h
    src/Migration.cpp src/Migration.h
    src/PasswordLogin.cpp src/PasswordLogin.h
    src/Preferences.cpp src/Preferences.h
    src/RemoteAuth.cpp src/RemoteAuth.h
    src/Session.cpp src/Session.h
    src/TypingIndicator.cpp src/TypingIndicator.h
    src/backend/CoreGlobals.cpp src/backend/CoreGlobals.h
    src/backend/QtFrontend.cpp src/backend/QtFrontend.h
    src/backend/QtHttpClient.cpp src/backend/QtHttpClient.h
    src/backend/QtWebsocketClient.cpp src/backend/QtWebsocketClient.h
    src/models/ChannelListModel.cpp src/models/ChannelListModel.h
    src/models/EmojiPickerModel.cpp src/models/EmojiPickerModel.h
    src/models/GuildListModel.cpp src/models/GuildListModel.h
    src/models/MessageContent.cpp src/models/MessageContent.h
    src/models/MessageListModel.cpp src/models/MessageListModel.h
    src/models/UnreadDmListModel.cpp src/models/UnreadDmListModel.h
    src/media/GstVideoPlayer.cpp src/media/GstVideoPlayer.h
    src/media/ApngView.cpp src/media/ApngView.h
    src/media/LottieView.cpp src/media/LottieView.h
    src/voice/AudioIO.cpp src/voice/AudioIO.h
    src/voice/CallManager.cpp src/voice/CallManager.h
    src/voice/DaveSession.cpp src/voice/DaveSession.h
    src/voice/Ringtone.cpp src/voice/Ringtone.h
    src/voice/TransportCipher.cpp src/voice/TransportCipher.h
    src/voice/VoiceSession.cpp src/voice/VoiceSession.h
    src/voice/VoiceStates.cpp src/voice/VoiceStates.h
)

# Test builds (tools/test): hooks driven by environment variables.
set(TEST_QML_FILES)
if(DISPORTS_TEST_HOOKS)
    target_sources(disports PRIVATE src/testing/TestHooks.cpp src/testing/TestHooks.h)
    target_compile_definitions(disports PRIVATE DISPORTS_TEST_HOOKS)
    set(TEST_QML_FILES qml/TestHooks.qml)
endif()

# Video goes through GStreamer (hardware decoders on the phone via
# gstreamer1.0-droid), see src/media/GstVideoPlayer.h.
find_package(PkgConfig REQUIRED)
pkg_check_modules(GST REQUIRED IMPORTED_TARGET gstreamer-1.0 gstreamer-app-1.0 gstreamer-video-1.0)
# Voice calls: Opus, PulseAudio (allowed to confined apps by the audio and
# microphone policy groups), with WebRTC's audio processing and RNNoise from
# third_party/, see src/voice/.
pkg_check_modules(VOICE REQUIRED IMPORTED_TARGET opus libpulse)
# Lottie stickers (src/media/LottieView.h).
pkg_check_modules(RLOTTIE REQUIRED IMPORTED_TARGET rlottie)

qt_add_qml_module(disports
    URI Disports
    QML_FILES
        qml/Main.qml
        qml/LoginPage.qml
        qml/MainPage.qml
        qml/Sidebar.qml
        qml/SidebarIcon.qml
        qml/FolderPreviewIcon.qml
        qml/StatusDot.qml
        qml/ChannelPanel.qml
        qml/ChatPanel.qml
        qml/CallBar.qml
        qml/MessageList.qml
        qml/Composer.qml
        qml/MentionPopup.qml
        qml/AttachmentBar.qml
        qml/ChatPage.qml
        qml/MessageCitation.qml
        qml/PasswordLoginPage.qml
        qml/ProfilePage.qml
        qml/ProfileView.qml
        qml/UpdateNotice.qml
        qml/MessageDelegate.qml
        qml/PanelHeader.qml
        qml/UnreadBadge.qml
        qml/ScrollDownButton.qml
        qml/ConnectionBanner.qml
        qml/SettingsPage.qml
        qml/EmojiPicker.qml
        qml/ReactionBar.qml
        qml/MediaPreview.qml
        qml/EmbedCard.qml
        qml/GifVideo.qml
        qml/VideoPlayer.qml
        qml/StickerView.qml
        qml/PollCard.qml
        qml/MediaViewerPage.qml
        qml/ChannelInfoPage.qml
        qml/CallPage.qml
        qml/CallBanner.qml
        qml/RoundedPicture.qml
        qml/ContentPickerPage.qml
        qml/CallBadge.qml
        qml/MediaSize.js
        ${TEST_QML_FILES}
)

# Next to the module's QML, but read only when shown: it imports the
# system's QtWebEngine, which the build doesn't need.
qt_add_resources(disports "captcha"
    PREFIX "/qt/qml/Disports"
    BASE ${PROJECT_SOURCE_DIR}
    FILES
        ${PROJECT_SOURCE_DIR}/qml/CaptchaPage.qml
)

qt_add_resources(disports "assets"
    PREFIX "/"
    BASE ${PROJECT_SOURCE_DIR}
    FILES
        ${PROJECT_SOURCE_DIR}/assets/logo.svg
        ${PROJECT_SOURCE_DIR}/assets/splash.svg
)

qt_add_resources(disports "data"
    PREFIX "/"
    FILES
        data/emoji.json
)

target_include_directories(disports PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/src)
target_compile_definitions(disports PRIVATE DISPORTS_VERSION="${APP_VERSION}"
    DISPORTS_ARCH_TRIPLET="${CMAKE_LIBRARY_ARCHITECTURE}")

target_link_libraries(disports PRIVATE
    Qt6::Gui
    Qt6::Qml
    Qt6::Quick
    Qt6::Network
    Qt6::WebSockets
    Qt6::DBus
    PkgConfig::GST
    PkgConfig::VOICE
    PkgConfig::RLOTTIE
    dave
    OpenSSL::Crypto
    discord
    qrcodegen
    rnnoise
    webrtc_audio_processing
)

install(TARGETS disports RUNTIME DESTINATION bin)

# Translations: each po/<lang>.po becomes
# share/locale/<lang>/LC_MESSAGES/disports.jukfiuu.mo. The template is made
# by tools/translations.sh, not by the build.
file(GLOB PO_FILES CONFIGURE_DEPENDS ${CMAKE_CURRENT_SOURCE_DIR}/po/*.po)
find_program(MSGFMT msgfmt)
if(PO_FILES AND NOT MSGFMT)
    message(WARNING "msgfmt (gettext) not found: building without translations")
elseif(PO_FILES)
    foreach(PO ${PO_FILES})
        get_filename_component(LANG ${PO} NAME_WE)
        set(MO ${CMAKE_CURRENT_BINARY_DIR}/locale/${LANG}/LC_MESSAGES/${APP_ID}.mo)
        add_custom_command(OUTPUT ${MO}
            COMMAND ${CMAKE_COMMAND} -E make_directory ${CMAKE_CURRENT_BINARY_DIR}/locale/${LANG}/LC_MESSAGES
            COMMAND ${MSGFMT} --check-format -o ${MO} ${PO}
            DEPENDS ${PO})
        list(APPEND MO_FILES ${MO})
        install(FILES ${MO} DESTINATION share/locale/${LANG}/LC_MESSAGES)
    endforeach()
    add_custom_target(translations ALL DEPENDS ${MO_FILES})
endif()

if(CLICK_MODE)
    configure_file(manifest.json.in ${CMAKE_CURRENT_BINARY_DIR}/manifest.json)
    configure_file(disports.desktop.in ${CMAKE_CURRENT_BINARY_DIR}/disports.desktop)
    install(
        FILES
            ${CMAKE_CURRENT_BINARY_DIR}/manifest.json
            ${CMAKE_CURRENT_BINARY_DIR}/disports.desktop
            disports.apparmor
        DESTINATION .
    )
    install(DIRECTORY assets DESTINATION .)
endif()
