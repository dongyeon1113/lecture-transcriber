#!/bin/bash
# FLEURS 테스트셋(한국어·영어)을 benchmark/data/ 에 받는다 (~500 MB, 압축 해제 후 ~690 MB)
# 비교 실험용 large-v3 모델(~3.1 GB)도 models/ 에 받는다 (프로그램 자체는 turbo 만 사용)
set -eu
DATA="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/data"
BASE=https://huggingface.co/datasets/google/fleurs/resolve/main/data

for L in ko_kr en_us; do
  mkdir -p "$DATA/$L"
  [ -d "$DATA/$L/test" ] && { echo "✓ $L"; continue; }
  echo "↓ $L"
  curl -L --fail -sS -o "$DATA/$L/test.tsv" "$BASE/$L/test.tsv"
  until curl -L --fail --progress-bar -C - --speed-limit 10000 --speed-time 60 \
             -o "$DATA/$L/test.tar.gz" "$BASE/$L/audio/test.tar.gz"; do sleep 5; done
  tar xzf "$DATA/$L/test.tar.gz" -C "$DATA/$L" && rm "$DATA/$L/test.tar.gz"
done

"$(dirname "$DATA")/../macos/download-models.sh" ggml-large-v3.bin
