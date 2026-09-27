#!/bin/bash
set -e
cd "$(dirname "$0")"
REPO="$(pwd)"
APP="$HOME/Applications/Watchbar.app"

if [ ! -d .venv ]; then
    /opt/homebrew/bin/python3 -m venv .venv
    .venv/bin/pip install -r requirements.txt
fi

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS"

cat > "$APP/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>Watchbar</string>
    <key>CFBundleIdentifier</key>
    <string>com.joshuaswanson.watchbar</string>
    <key>CFBundleExecutable</key>
    <string>Watchbar</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>LSUIElement</key>
    <true/>
</dict>
</plist>
EOF

clang -O2 -DREPO="\"$REPO\"" -o "$APP/Contents/MacOS/Watchbar" launcher.c
codesign --force --sign - "$APP"

echo "Built $APP"
