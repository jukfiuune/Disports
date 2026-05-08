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

# ---------------------------------------------------------------------------
# Locate Python 3.8 headers without requiring python3.8-dev.
#
# The clickable arm64 container ships python3.8 (runtime) but python3.8-dev
# has a broken dependency against the exact patch version, so we cannot
# install it via apt.  However the headers are already present on the host
# system (installed by pyotherside's own build deps) in one of two canonical
# locations.  We find them here with find_path so no extra package is needed.
#
# We link against libpython3.8.so which is already in the container's sysroot
# as part of the python3.8 runtime package.
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Locate Python 3.8 headers by asking the interpreter that is already on PATH.
# This works regardless of where the clickable container stores the headers,
# because python3 --version and sysconfig are always available when pyotherside
# is present (it needs Python at build time too).
# We deliberately avoid find_package(Python3 Development) because the -dev
# package cannot be installed due to a version-pinning conflict in the arm64
# Ubuntu 20.04 repo.
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Locate Python 3.8 headers.
# ---------------------------------------------------------------------------
# In the clickable container, python3.8-dev is often broken, but the headers
# are present in /usr/include/python3.8.
if(EXISTS "/usr/include/python3.8/Python.h")
    set(Python3_INCLUDE_DIRS "/usr/include/python3.8")
else()
    # Fallback to asking the interpreter
    execute_process(
        COMMAND python3 -c "import sysconfig; print(sysconfig.get_path('include'), end='')"
        OUTPUT_VARIABLE Python3_INCLUDE_DIRS
        OUTPUT_STRIP_TRAILING_WHITESPACE
    )
endif()

# We link against 'python3.8' (linker will find it in the architecture-specific sysroot)
set(Python3_LIBRARIES "python3.8")

message(STATUS "Python3 headers : ${Python3_INCLUDE_DIRS}")
message(STATUS "Python3 library : ${Python3_LIBRARIES}")

set(VOICEAUDIO_PLUGIN_DIR "${QT_IMPORTS_DIR}/Disports")

add_library(disportsvoice SHARED
    src/cpp/voiceaudio.cpp
    src/cpp/plugin.cpp
)

set_target_properties(disportsvoice PROPERTIES
    AUTOMOC ON
    OUTPUT_NAME "disportsvoice"
)

target_include_directories(disportsvoice PRIVATE
    src/cpp
    ${Python3_INCLUDE_DIRS}
)

target_link_libraries(disportsvoice
    Qt5::Core
    Qt5::Multimedia
    Qt5::Qml
    Qt5::Quick
    ${Python3_LIBRARIES}
)

install(TARGETS disportsvoice
    LIBRARY DESTINATION "${VOICEAUDIO_PLUGIN_DIR}"
)

install(FILES src/cpp/qmldir
    DESTINATION "${VOICEAUDIO_PLUGIN_DIR}"
)

