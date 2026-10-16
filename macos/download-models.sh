#!/bin/bash
# Whisper / VAD 모델을 models/ 에 받는다. 끊겨도 이어받기, 받은 뒤 SHA-256 검증.
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIR="$ROOT/models"
mkdir -p "$DIR"

# 파일명  URL  SHA-256
MODELS=(
  "ggml-large-v3-turbo.bin https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo.bin 1fc70f774d38eb169993ac391eea357ef47c88757ef72ee5943879b7e8e2bc69"
  "ggml-large-v3.bin https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3.bin 64d182b440b98d5203c4f9bd541544d84c605196c4f7b845dfa11fb23594d1e2"
  "ggml-silero-v5.1.2.bin https://huggingface.co/ggml-org/whisper-vad/resolve/main/ggml-silero-v5.1.2.bin 29940d98d42b91fbd05ce489f3ecf7c72f0a42f027e4875919a28fb4c04ea2cf"
)

for entry in "${MODELS[@]}"; do
  read -r name url sha <<< "$entry"
  if [ -f "$DIR/$name" ]; then
    echo "✓ $name (already downloaded)"
    continue
  fi
  echo "↓ $name"
  # 속도가 60초 동안 10KB/s 미만이면 끊고 이어받기로 재시도
  until curl -L --fail --progress-bar -C - --speed-limit 10000 --speed-time 60 \
              -o "$DIR/$name.part" "$url"; do
    echo "  retrying..."; sleep 5
  done
  if [ "$(shasum -a 256 "$DIR/$name.part" | awk '{print $1}')" != "$sha" ]; then
    echo "✗ $name: checksum mismatch, deleting. Run this script again." >&2
    rm -f "$DIR/$name.part"
    exit 1
  fi
  mv "$DIR/$name.part" "$DIR/$name"
  echo "✓ $name"
done
