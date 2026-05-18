#!/usr/bin/env bash
# desktop-with-audio.sh — run Disports desktop with PulseAudio/PipeWire socket
# Usage: ./scripts/desktop-with-audio.sh [--skip-build]
set -e

# Build first (skip with --skip-build)
if [[ "$1" != "--skip-build" ]]; then
    clickable build --skip-review
fi

PULSE_SOCKET="/run/user/$(id -u)/pulse/native"
INSTALL_DIR="$(pwd)/build/x86_64-linux-gnu/app/install"
BUILD_HOME="$(pwd)/build/x86_64-linux-gnu/app/.clickable/home"

# Get the most recently used clickable image
IMAGE=$(docker images --format "{{.Repository}}:{{.Tag}}" | grep "clickable/amd64-20.04-amd64" | head -1)
echo "Using image: $IMAGE"
echo "Pulse socket: $PULSE_SOCKET"

mkdir -p "$BUILD_HOME"

# Allow docker X11 access
touch /tmp/.docker.xauth
xauth nlist "$DISPLAY" | sed -e 's/^..../ffff/' | xauth -f /tmp/.docker.xauth nmerge - 2>/dev/null || true
xhost +local:docker 2>/dev/null || true

# Run; fix ownership of any root-created files on exit
cleanup() {
    find "$INSTALL_DIR" -user root \( -name "*.pyc" -o -type d -name "__pycache__" \) -delete 2>/dev/null || true
}
trap cleanup EXIT

docker run --rm \
    --network=host \
    --user "$(id -u):$(id -g)" \
    -e DISPLAY="$DISPLAY" \
    -e QT_QPA_PLATFORM=xcb \
    -e LIBGL_ALWAYS_SOFTWARE=1 \
    -e GALLIUM_DRIVER=softpipe \
    -e PULSE_SERVER="unix:/tmp/pulse-socket" \
    -e PYTHONPATH=/app/src \
    -e LD_LIBRARY_PATH="/app/lib/x86_64-linux-gnu:/app/lib" \
    -e QML2_IMPORT_PATH="/app/lib/x86_64-linux-gnu:/app/lib" \
    -e XDG_RUNTIME_DIR=/tmp/runtime \
    -e HOME=/home/phablet \
    -e UITK_ICON_THEME=suru \
    -e APP_DIR=/app \
    -e CLICKABLE_DESKTOP_MODE=1 \
    -e UBUNTU_APP_LAUNCH_ARCH=x86_64-linux-gnu \
    -e OXIDE_NO_SANDBOX=1 \
    -e XAUTHORITY=/tmp/.docker.xauth \
    -v /tmp/.X11-unix:/tmp/.X11-unix \
    -v /tmp/.docker.xauth:/tmp/.docker.xauth \
    -v /etc/machine-id:/etc/machine-id \
    -v /var/lib/dbus:/var/lib/dbus \
    -v /dev/snd:/dev/snd \
    -v /dev/shm:/dev/shm \
    -v /etc/passwd:/etc/passwd \
    -v "${PULSE_SOCKET}:/tmp/pulse-socket" \
    -v "${INSTALL_DIR}:/app" \
    -v "${BUILD_HOME}:/home/phablet" \
    -w /app \
    "$IMAGE" \
    qmlscene -I /app/lib/x86_64-linux-gnu qml/Main.qml
