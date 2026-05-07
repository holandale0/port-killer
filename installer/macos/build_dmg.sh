#!/bin/bash
# Build DMG for macOS (run from project root after build.py creates the .app)
# Usage: bash installer/macos/build_dmg.sh
set -e

APP_NAME="PortKiller"
APP_VERSION="1.0.0"
APP_PATH="dist/${APP_NAME}.app"
DMG_PATH="dist/PortKiller-${APP_VERSION}.dmg"

if [ ! -d "$APP_PATH" ]; then
    echo "Error: $APP_PATH not found. Run 'python build.py' first."
    exit 1
fi

[ -f "$DMG_PATH" ] && rm "$DMG_PATH"

if command -v create-dmg &>/dev/null; then
    create-dmg \
        --volname "Port Killer" \
        --window-pos 200 120 \
        --window-size 600 400 \
        --icon-size 100 \
        --app-drop-link 425 150 \
        "$DMG_PATH" \
        "$APP_PATH"
else
    # hdiutil ships with every macOS — no install needed
    hdiutil create \
        -volname "Port Killer" \
        -srcfolder "$APP_PATH" \
        -ov -format UDZO \
        "$DMG_PATH"
fi

echo "DMG created: $DMG_PATH"
