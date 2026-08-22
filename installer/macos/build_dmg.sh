#!/bin/bash
# Build DMG for macOS (run from project root after build.py creates the .app)
# Usage: bash installer/macos/build_dmg.sh
set -e

APP_NAME="PortKiller"
# Single source of truth, same as build.py and the .spec.
APP_VERSION=$(sed -n "s/^APP_VERSION *= *[\"']\(.*\)[\"'].*/\1/p" port_killer.py)
[ -n "$APP_VERSION" ] || { echo "Error: APP_VERSION not found in port_killer.py"; exit 1; }
APP_PATH="dist/${APP_NAME}.app"
DMG_PATH="dist/PortKiller-${APP_VERSION}.dmg"

if [ ! -d "$APP_PATH" ]; then
    echo "Error: $APP_PATH not found. Run 'python build.py' first."
    exit 1
fi

[ -f "$DMG_PATH" ] && rm "$DMG_PATH"

# Both tools take a *folder* whose contents become the volume root. Passing the
# .app itself put Contents/ at the root instead of the app, and broke
# create-dmg's --app-drop-link. Stage the bundle inside a folder first.
STAGING="build/dmg"
rm -rf "$STAGING"
mkdir -p "$STAGING"
cp -R "$APP_PATH" "$STAGING/${APP_NAME}.app"

if command -v create-dmg &>/dev/null; then
    create-dmg \
        --volname "Port Killer" \
        --window-pos 200 120 \
        --window-size 600 400 \
        --icon-size 100 \
        --icon "${APP_NAME}.app" 175 150 \
        --app-drop-link 425 150 \
        "$DMG_PATH" \
        "$STAGING"
else
    # hdiutil ships with every macOS — no install needed
    hdiutil create \
        -volname "Port Killer" \
        -srcfolder "$STAGING" \
        -ov -format UDZO \
        "$DMG_PATH"
fi

rm -rf "$STAGING"

echo "DMG created: $DMG_PATH"
