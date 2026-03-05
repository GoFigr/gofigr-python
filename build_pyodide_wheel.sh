#!/usr/bin/env bash
#
# Builds a pure-Python wheel from the local gofigr-python source and copies
# it to the webapp's public directory so it can be served as a static asset
# for Pyodide.
#
# Usage:
#   ./build_pyodide_wheel.sh
#
# The wheel is placed at:
#   ~/dev/gofigr_webapp/public/pyodide/gofigr-latest-py3-none-any.whl

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WEBAPP_DIR="${WEBAPP_DIR:-$HOME/dev/gofigr_webapp}"
DEST_DIR="$WEBAPP_DIR/public/pyodide"

cd "$SCRIPT_DIR"

VERSION=$(python3 -c "
import re
with open('pyproject.toml') as f:
    m = re.search(r'^version\s*=\s*\"(.+?)\"', f.read(), re.M)
    print(m.group(1))
")

echo "Building gofigr $VERSION wheel for Pyodide..."

TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

WHEEL_NAME="gofigr-${VERSION}-py3-none-any"
WHEEL_DIR="$TMPDIR/$WHEEL_NAME"

mkdir -p "$WHEEL_DIR/gofigr"
cp -r gofigr/*.py "$WHEEL_DIR/gofigr/"

# Copy subpackages (Python files + all resource files)
for subdir in $(find gofigr -mindepth 1 -type d ! -name __pycache__ ! -path '*/node_modules/*' ! -path '*/labextension/*'); do
    mkdir -p "$WHEEL_DIR/$subdir"
    # Copy all files except .pyc and __pycache__
    find "$subdir" -maxdepth 1 -type f ! -name '*.pyc' -exec cp {} "$WHEEL_DIR/$subdir/" \;
done

# Create METADATA
mkdir -p "$WHEEL_DIR/gofigr-${VERSION}.dist-info"
cat > "$WHEEL_DIR/gofigr-${VERSION}.dist-info/METADATA" <<EOF
Metadata-Version: 2.1
Name: gofigr
Version: $VERSION
Summary: GoFigr client library (Pyodide build)
EOF

cat > "$WHEEL_DIR/gofigr-${VERSION}.dist-info/WHEEL" <<EOF
Wheel-Version: 1.0
Generator: build_pyodide_wheel.sh
Root-Is-Purelib: true
Tag: py3-none-any
EOF

cat > "$WHEEL_DIR/gofigr-${VERSION}.dist-info/top_level.txt" <<EOF
gofigr
EOF

# Create RECORD (empty is fine for local dev)
touch "$WHEEL_DIR/gofigr-${VERSION}.dist-info/RECORD"

# Build the wheel (a wheel is just a zip with .whl extension)
cd "$TMPDIR"
WHEEL_FILE="${WHEEL_NAME}.whl"
cd "$WHEEL_NAME"
zip -r "$TMPDIR/$WHEEL_FILE" . -x '*.pyc' '__pycache__/*' > /dev/null

mkdir -p "$DEST_DIR"

# Always copy with a stable name so the worker URL doesn't change
cp "$TMPDIR/$WHEEL_FILE" "$DEST_DIR/gofigr-latest-py3-none-any.whl"

echo "Done. Wheel copied to: $DEST_DIR/gofigr-latest-py3-none-any.whl"
echo "Size: $(du -h "$DEST_DIR/gofigr-latest-py3-none-any.whl" | cut -f1)"
