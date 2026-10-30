#!/bin/sh
# Le pont Rappels/Calendrier dans une petite app : `sh eventkit/make-app.sh` depuis ~/personal-hub/personal-hub/assistant.
#
# macOS accorde Rappels et Calendrier à l'app responsable du programme qui demande. Lancé depuis le Terminal, c'est le
# Terminal ; lancé par launchd, le Python du venv n'a ni bundle ni phrases d'usage, et n'obtient rien. Cette app porte
# ses phrases d'usage (Info.plist) et lance le pont : lancée par `open`, elle est responsable du Python qu'elle exécute,
# et c'est elle qui apparaît dans Réglages Système → Confidentialité. Le LaunchAgent ch.domia.eventkit l'ouvre.
set -eu
HERE=$(cd "$(dirname "$0")/.." && pwd)
APP="$HOME/Applications/Domia Rappels.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS"
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleIdentifier</key><string>ch.domia.ekbridge</string>
  <key>CFBundleName</key><string>Domia Rappels</string>
  <key>CFBundleExecutable</key><string>ekbridge</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>LSUIElement</key><true/>
  <key>NSRemindersUsageDescription</key><string>L'assistant de maison lit et ajoute des rappels (liste de courses).</string>
  <key>NSRemindersFullAccessUsageDescription</key><string>L'assistant de maison lit et ajoute des rappels (liste de courses).</string>
  <key>NSCalendarsUsageDescription</key><string>L'assistant de maison lit et ajoute des événements.</string>
  <key>NSCalendarsFullAccessUsageDescription</key><string>L'assistant de maison lit et ajoute des événements.</string>
</dict>
</plist>
PLIST
cat > "$APP/Contents/MacOS/ekbridge" <<SCRIPT
#!/bin/sh
cd "$HERE/eventkit"
exec "$HERE/.venv/bin/python" -m ekbridge "\$@" >> "$HOME/Domia/logs/eventkit.log" 2>&1
SCRIPT
chmod +x "$APP/Contents/MacOS/ekbridge"
codesign --force --deep --sign - "$APP"
echo "prêt : $APP"
