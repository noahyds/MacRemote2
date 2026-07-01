#!/bin/bash
# Mac Remote — .app builder
# Dobbeltklikk denne på Mac. Den bygger MacRemote.app, legger den i
# /Applications, installerer avhengigheter, og starter serveren.

export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
REPO="https://raw.githubusercontent.com/noahyds/MacRemote/main"
APP="/Applications/MacRemote.app"
RES="$APP/Contents/Resources"
MACOS="$APP/Contents/MacOS"

clear
echo ""
echo "  ╔══════════════════════════════════════════╗"
echo "  ║   Bygger MacRemote.app …                 ║"
echo "  ╚══════════════════════════════════════════╝"
echo ""

# ── 1. Avhengigheter ──
echo "  [1/5] Python…"
command -v python3 &>/dev/null || { echo "  ❌ Python3 mangler → https://python.org"; read -p "Enter for å lukke"; exit 1; }
echo "  ✓ $(python3 --version)"

echo "  [2/5] Homebrew + cliclick…"
if ! command -v brew &>/dev/null; then
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  [ -f /opt/homebrew/bin/brew ] && eval "$(/opt/homebrew/bin/brew shellenv)"
fi
command -v cliclick &>/dev/null || brew install cliclick --quiet
echo "  ✓ ok"

echo "  [3/5] Flask + psutil…"
pip3 install flask psutil --quiet --break-system-packages 2>/dev/null || pip3 install flask psutil --quiet 2>/dev/null
python3 -c "import flask,psutil" 2>/dev/null || { echo "  ❌ pip feilet"; read -p "Enter for å lukke"; exit 1; }
echo "  ✓ ok"

# ── 2. App-struktur ──
echo "  [4/5] Bygger .app…"
rm -rf "$APP"
mkdir -p "$RES" "$MACOS"

# Hent server + web fra GitHub
curl -fsSL "$REPO/mac_remote.py"   -o "$RES/mac_remote.py"
curl -fsSL "$REPO/mac_remote.html" -o "$RES/mac_remote.html"
[ -f "$RES/mac_remote.py" ] && [ -f "$RES/mac_remote.html" ] || { echo "  ❌ nedlasting feilet"; read -p "Enter"; exit 1; }

# Info.plist
cat > "$APP/Contents/Info.plist" << 'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>MacRemote</string>
  <key>CFBundleDisplayName</key><string>Mac Remote</string>
  <key>CFBundleIdentifier</key><string>com.noahyds.macremote</string>
  <key>CFBundleVersion</key><string>4.0</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>launch</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>LSUIElement</key><false/>
</dict>
</plist>
PLIST

# Launcher-binær (åpner Terminal så bruker ser IP + token)
cat > "$MACOS/launch" << 'LAUNCH'
#!/bin/bash
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
RES="$(cd "$(dirname "$0")/../Resources" && pwd)"
osascript <<END
tell application "Terminal"
    activate
    do script "python3 '$RES/mac_remote.py'"
end tell
END
LAUNCH
chmod +x "$MACOS/launch"
xattr -dr com.apple.quarantine "$APP" 2>/dev/null

echo "  ✓ MacRemote.app bygget"

# ── 3. Ferdig + åpne ──
echo "  [5/5] Starter…"
IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo "?")
echo ""
echo "  ╔══════════════════════════════════════════╗"
echo "  ║  ✅ Ferdig! MacRemote.app i Applications  ║"
echo "  ╠══════════════════════════════════════════╣"
echo "  ║  Mobil: http://$IP:5055           "
echo "  ║                                          ║"
echo "  ║  Åpne fra Launchpad/Applications, eller   ║"
echo "  ║  dra til Dock for fast plass              ║"
echo "  ║                                          ║"
echo "  ║  ⚠️  Første gang: gi Terminal tilgang     ║"
echo "  ║  Innstillinger→Personvern→Tilgjengelighet ║"
echo "  ╚══════════════════════════════════════════╝"
echo ""

open "$APP"
