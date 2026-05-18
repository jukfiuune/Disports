cmake_minimum_required(VERSION 3.0.0)
project(disports C CXX)

# Automatically create moc files
set(CMAKE_AUTOMOC ON)

execute_process(
    COMMAND dpkg-architecture -qDEB_HOST_MULTIARCH
    OUTPUT_VARIABLE ARCH_TRIPLET
    ERROR_VARIABLE ARCH_ERR
    OUTPUT_STRIP_TRAILING_WHITESPACE
)

if(NOT ARCH_TRIPLET)
    if(CMAKE_SYSTEM_PROCESSOR STREQUAL "aarch64" OR CMAKE_SYSTEM_PROCESSOR STREQUAL "arm64")
        set(ARCH_TRIPLET "aarch64-linux-gnu")
    elseif(CMAKE_SYSTEM_PROCESSOR STREQUAL "armv7l" OR CMAKE_SYSTEM_PROCESSOR STREQUAL "armhf")
        set(ARCH_TRIPLET "arm-linux-gnueabihf")
    else()
        set(ARCH_TRIPLET "x86_64-linux-gnu")
    endif()
endif()
set(QT_IMPORTS_DIR "lib/${ARCH_TRIPLET}")

set(PROJECT_NAME "disports")
set(FULL_PROJECT_NAME "disports.jukfiuu")
set(DATA_DIR /)
set(DESKTOP_FILE_NAME ${PROJECT_NAME}.desktop)



configure_file(manifest.json.in ${CMAKE_CURRENT_BINARY_DIR}/manifest.json)
install(FILES ${CMAKE_CURRENT_BINARY_DIR}/manifest.json DESTINATION ${CMAKE_INSTALL_PREFIX})
install(FILES ${PROJECT_NAME}.apparmor DESTINATION ${DATA_DIR})

install(DIRECTORY assets DESTINATION ${DATA_DIR})
install(DIRECTORY src DESTINATION ${DATA_DIR})

install(DIRECTORY qml DESTINATION ${DATA_DIR})

# Python Deps
install(FILES "build-python-deps.sh" DESTINATION ${DATA_DIR})
install(FILES "requirements.txt" DESTINATION ${DATA_DIR})

# Translations
file(GLOB_RECURSE I18N_SRC_FILES RELATIVE ${CMAKE_CURRENT_SOURCE_DIR}/po qml/*.qml qml/*.js)
list(APPEND I18N_SRC_FILES ${DESKTOP_FILE_NAME}.in.h)

find_program(INTLTOOL_MERGE intltool-merge)
if(NOT INTLTOOL_MERGE)
    message(FATAL_ERROR "Could not find intltool-merge, please install the intltool package")
endif()
find_program(INTLTOOL_EXTRACT intltool-extract)
if(NOT INTLTOOL_EXTRACT)
    message(FATAL_ERROR "Could not find intltool-extract, please install the intltool package")
endif()

add_custom_target(${DESKTOP_FILE_NAME} ALL
    COMMENT "Merging translations into ${DESKTOP_FILE_NAME}..."
    COMMAND LC_ALL=C ${INTLTOOL_MERGE} -d -u ${CMAKE_SOURCE_DIR}/po ${CMAKE_SOURCE_DIR}/${DESKTOP_FILE_NAME}.in ${DESKTOP_FILE_NAME}
    COMMAND sed -i 's/${PROJECT_NAME}-//g' ${CMAKE_CURRENT_BINARY_DIR}/${DESKTOP_FILE_NAME}
)

install(FILES ${CMAKE_CURRENT_BINARY_DIR}/${DESKTOP_FILE_NAME} DESTINATION ${DATA_DIR})

add_subdirectory(po)

# Make source files visible in qtcreator
file(GLOB_RECURSE PROJECT_SRC_FILES
    RELATIVE ${CMAKE_CURRENT_SOURCE_DIR}
    qml/*.qml
    qml/*.js
    src/*
    *.json
    *.json.in
    *.apparmor
    *.desktop.in
)

add_custom_target(${PROJECT_NAME}_FILES ALL SOURCES ${PROJECT_SRC_FILES})

# ---------------------------------------------------------------------------
# C++ VoiceAudio QML plugin
# ---------------------------------------------------------------------------
find_package(Qt5 REQUIRED COMPONENTS Core Multimedia Qml Quick)

# Python 3 headers removed

set(VOICEAUDIO_PLUGIN_DIR "${QT_IMPORTS_DIR}/Disports")

add_library(disportsvoice SHARED
    src/cpp/voiceaudio.cpp
    src/cpp/plugin.cpp
    src/cpp/disports_dave.cpp
)

set_target_properties(disportsvoice PROPERTIES
    AUTOMOC ON
    OUTPUT_NAME "disportsvoice"
    CXX_STANDARD 17
    CXX_STANDARD_REQUIRED ON
)

target_include_directories(disportsvoice PRIVATE
    src/cpp
    3rdparty/libdave/cpp/includes
)

target_link_libraries(disportsvoice
    Qt5::Core
    Qt5::Multimedia
    Qt5::Qml
    Qt5::Quick
    ${CMAKE_BINARY_DIR}/../libdave/install/lib/libdave.so
)

install(TARGETS disportsvoice
    LIBRARY DESTINATION "${VOICEAUDIO_PLUGIN_DIR}"
)

install(FILES src/cpp/qmldir
    DESTINATION "${VOICEAUDIO_PLUGIN_DIR}"
)

