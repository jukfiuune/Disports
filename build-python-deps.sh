set -euo pipefail

cd "$INSTALL_DIR"
/usr/local/uv pip install --system -r requirements.txt --target src
