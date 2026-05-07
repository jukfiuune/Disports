set -euo pipefail

cd "$INSTALL_DIR"

TARGET_PLATFORM="x86_64-unknown-linux-gnu"
ACTUAL_ARCH="${ARCH:-${CLICKABLE_ARCH:-}}"

if [ "$ACTUAL_ARCH" = "arm64" ] || [ "$ACTUAL_ARCH" = "aarch64" ]; then
    TARGET_PLATFORM="aarch64-unknown-linux-gnu"
elif [ "$ACTUAL_ARCH" = "armhf" ] || [ "$ACTUAL_ARCH" = "arm" ]; then
    TARGET_PLATFORM="armv7-unknown-linux-gnueabihf"
fi

echo "Installing Python dependencies for $TARGET_PLATFORM..."
/usr/local/uv pip install \
    --system \
    --python-platform "$TARGET_PLATFORM" \
    --python-version 3.8 \
    -r requirements.txt \
    --target src
