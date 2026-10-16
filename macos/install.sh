#!/bin/bash
# 설치: whisper.cpp 설치 → 모델 다운로드 → 감시 폴더를 지켜보는 launchd 에이전트 등록
# 사용법: ./install.sh [감시 폴더]   (기본값: ~/Lecture Inbox)
set -eu
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INBOX="${1:-$HOME/Lecture Inbox}"
LABEL="com.lecture-transcriber"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

[ "$(uname)" = Darwin ] || { echo "macOS only." >&2; exit 1; }
command -v brew >/dev/null || { echo "Homebrew is required: https://brew.sh" >&2; exit 1; }
/usr/bin/python3 -c "" 2>/dev/null || { echo "Run 'xcode-select --install' first (needed for python3)." >&2; exit 1; }

echo "==> Installing whisper.cpp"
command -v whisper-cli >/dev/null || brew install whisper.cpp

echo "==> Downloading models (~4.7 GB)"
"$ROOT/macos/download-models.sh"

echo "==> Registering folder watcher"
mkdir -p "$INBOX" "$HOME/Library/LaunchAgents"
INBOX="$(cd "$INBOX" && pwd)"
chmod +x "$ROOT/macos/transcribe.sh"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$ROOT/macos/transcribe.sh</string>
    <string>$INBOX</string>
  </array>
  <key>WatchPaths</key>
  <array><string>$INBOX</string></array>
  <key>RunAtLoad</key><true/>
  <key>ProcessType</key><string>Interactive</string>
</dict>
</plist>
EOF
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"

echo
echo "Done. Drop .mp4 / .m4a / .mov files into:"
echo "  $INBOX"
open "$INBOX"
