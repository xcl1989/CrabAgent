#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "=== Building CrabAgent Desktop App ==="
echo ""

# Some bundled environments only expose Node under /usr/local/bin. Keep the
# build script usable there while preserving the caller's PATH precedence.
if ! command -v node >/dev/null 2>&1 && [ -x /usr/local/bin/node ]; then
  export PATH="/usr/local/bin:$PATH"
fi
if ! command -v npm >/dev/null 2>&1 && [ -f /usr/local/lib/node_modules/npm/bin/npm-cli.js ]; then
  npm() { node /usr/local/lib/node_modules/npm/bin/npm-cli.js "$@"; }
fi
if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
  echo "Error: Node.js and npm are required to build the desktop app."
  exit 127
fi

# 1. Build frontend
echo "[1/5] Building frontend..."
cd "$PROJECT_ROOT/frontend"
npm ci --silent 2>/dev/null
npm run build
echo "  Done."

# 2. Copy static to Python package
echo "[2/5] Copying static assets..."
cd "$PROJECT_ROOT"
mkdir -p src/crabagent/static
rm -rf src/crabagent/static/assets
cp -R frontend/dist/index.html frontend/dist/assets src/crabagent/static/
echo "  Done."

# 3. PyInstaller build
echo "[3/5] Compiling Python backend with PyInstaller..."
cd "$PROJECT_ROOT"
pip install pyinstaller -q
pyinstaller crabagent.spec --clean --noconfirm 2>&1 | tail -1
ls -lh dist/crabagent-backend
echo "  Done."

# 4. Copy backend binary to Electron resources
echo "[4/5] Copying backend to Electron app..."
mkdir -p electron/resources
rm -rf electron/resources/crabagent-backend
cp -R dist/crabagent-backend electron/resources/
echo "  Done."

# 5. Build Electron .app
echo "[5/6] Building Electron .app..."
cd "$PROJECT_ROOT/electron"
npm ci --silent 2>/dev/null
npx electron-builder --mac --dir -p never 2>&1 | tail -5

# 6. Build DMG with electron-builder (drag-to-Applications layout from package.json)
echo "[6/6] Creating .dmg with electron-builder..."
npx electron-builder --mac dmg -p never 2>&1 | tail -3

echo ""
echo "=== Build Complete! ==="
ls -lh dist-electron/CrabAgent-*-arm64.dmg | tail -1
