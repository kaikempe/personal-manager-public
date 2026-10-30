#!/bin/bash
# Builds ~/Applications/Personal Manager.app: a native window (WKWebView) around the dashboard.
# Sources in app/. The server itself is kept alive by scripts/install_dashboard.sh.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP="$HOME/Applications/Personal Manager.app"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

swiftc -O -o "$TMP/PersonalManager" "$ROOT/app/main.swift"
swift "$ROOT/app/make_icon.swift" "$TMP/AppIcon.iconset"
iconutil -c icns "$TMP/AppIcon.iconset" -o "$TMP/AppIcon.icns"

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$TMP/PersonalManager" "$APP/Contents/MacOS/PersonalManager"
cp "$TMP/AppIcon.icns" "$APP/Contents/Resources/AppIcon.icns"
cat > "$APP/Contents/Info.plist" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Personal Manager</string>
  <key>CFBundleDisplayName</key><string>Personal Manager</string>
  <key>CFBundleIdentifier</key><string>com.personal-manager.personal-manager</string>
  <key>CFBundleExecutable</key><string>PersonalManager</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>LSMinimumSystemVersion</key><string>12.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSAppTransportSecurity</key><dict><key>NSAllowsLocalNetworking</key><true/></dict>
</dict>
</plist>
PL
codesign --force --sign - "$APP" 2>/dev/null
touch "$APP"
echo "built $APP"
