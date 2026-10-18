#!/bin/bash
# 사용법: transcribe.sh <감시 폴더>
# 감시 폴더에 들어온 영상/음성 파일을 텍스트(.txt)로 변환한다.
# - 같은 이름의 .txt 가 이미 있으면 건너뜀
# - 한국어/영어 자동 판별 (영상 25/50/75% 지점 다수결)
# - 엔진: whisper.cpp (Metal GPU) + Silero VAD (설정 근거: benchmark/RESULTS.md)
#     모델: large-v3-turbo (한국어·영어 공통 — 벤치마크에서 영어도 large-v3 와 정확도 동일, 2.5배 빠름)
set -u

export PATH="/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"

INBOX="${1:?usage: transcribe.sh <inbox folder>}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # 레포 루트
MODEL="$ROOT/models/ggml-large-v3-turbo.bin"
# 예상 시간 계산용 배속 (M2 실측)
SPEED=15
VAD_MODEL="$ROOT/models/ggml-silero-v5.1.2.bin"
# VAD 민감도 0.35 / 앞뒤 여유 200ms / 최소 침묵 300ms — 기본값(0.5/30ms/100ms)은 말소리 일부를 잘라냄
VAD_FLAGS=(--vad -vm "$VAD_MODEL" -vt 0.35 -vp 200 -vsd 300)
LOG="$HOME/Library/Logs/lecture-transcriber.log"
LOCK="$ROOT/.lock"
TMP="${TMPDIR:-/tmp}/transcribe-$$"

log() { echo "[$(date '+%F %T')] $*" >> "$LOG"; }
notify() { osascript -e "display notification \"$1\" with title \"Lecture Transcriber\"" >/dev/null 2>&1; }

# 동시에 여러 개 실행되지 않도록 잠금
if ! mkdir "$LOCK" 2>/dev/null; then
  # 이전 실행이 비정상 종료돼 잠금만 남은 경우 정리
  pid=$(cat "$LOCK/pid" 2>/dev/null)
  if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then exit 0; fi
  rm -rf "$LOCK"; mkdir "$LOCK" || exit 0
fi
echo $$ > "$LOCK/pid"
mkdir -p "$TMP"
trap 'rm -rf "$LOCK" "$TMP"' EXIT

# 복사/다운로드가 끝날 때까지(파일 크기가 변하지 않을 때까지) 대기
wait_stable() {
  local prev=-1 cur
  while :; do
    cur=$(stat -f %z "$1" 2>/dev/null) || return 1
    [ "$cur" = "$prev" ] && [ "$cur" -gt 0 ] && return 0
    prev=$cur; sleep 3
  done
}

# 영상 25/50/75% 지점에서 30초씩 잘라 언어 판별 → 2곳 이상 영어면 en, 아니면 ko
detect_lang() {
  local wav="$1" fr en=0 lang
  for fr in 0.25 0.5 0.75; do
    /usr/bin/python3 -I "$ROOT/macos/wavtool.py" cut "$wav" "$TMP/clip.wav" "$fr" 30 2>>"$LOG" || continue
    lang=$(whisper-cli -m "$MODEL" -l auto -dl "${VAD_FLAGS[@]}" -f "$TMP/clip.wav" 2>&1 |
           sed -n 's/.*auto-detected language: \([a-z]*\).*/\1/p')
    log "  언어 판별 ${fr}: ${lang:-?}"
    [ "$lang" = "en" ] && en=$((en + 1))
  done
  rm -f "$TMP/clip.wav"
  [ $en -ge 2 ] && echo en || echo ko
}

transcribe() {
  local src="$1" base wav start secs
  base="${src%.*}"
  wav="$TMP/audio.wav"

  log "시작: $(basename "$src")"
  start=$(date +%s)

  # 1) 오디오 추출 (맥 내장 afconvert, 16kHz 모노 — Whisper 입력 형식)
  #    afconvert 가 못 여는 파일은 avconvert(맥 내장)로 m4a 를 먼저 뽑아서 재시도
  if ! afconvert -f WAVE -d LEI16@16000 -c 1 "$src" "$wav" >>"$LOG" 2>&1 || [ ! -s "$wav" ]; then
    rm -f "$TMP/audio.m4a"
    if ! { avconvert -s "$src" -o "$TMP/audio.m4a" -p PresetAppleM4A >>"$LOG" 2>&1 &&
           afconvert -f WAVE -d LEI16@16000 -c 1 "$TMP/audio.m4a" "$wav" >>"$LOG" 2>&1 &&
           [ -s "$wav" ]; }; then
      log "실패(오디오 추출 — 소리 트랙이 없거나 손상): $(basename "$src")"
      notify "실패: $(basename "$src") — 소리 트랙을 읽을 수 없음"
      return 1
    fi
  fi

  # 2) 작게 녹음된 파일은 음량을 키움 (VAD 가 작은 목소리를 놓치지 않도록)
  /usr/bin/python3 -I "$ROOT/macos/wavtool.py" level "$wav" "$TMP/level.wav" >>"$LOG" 2>&1 &&
    mv "$TMP/level.wav" "$wav"

  # 3) 언어 판별
  local lang label dur
  lang=$(detect_lang "$wav")
  if [ "$lang" = en ]; then label="영어"; else label="한국어"; fi
  log "  언어: $label"
  dur=$(afinfo "$wav" 2>/dev/null | awk '/estimated duration/ {printf "%d", $3}')
  notify "변환 시작 ($label): $(basename "$src") — 약 $(( ${dur:-0} / SPEED / 60 + 1 ))분 예상"

  # 4) 음성 인식 (-mc 0: 앞 문장 문맥을 안 넘겨서 같은 문장 반복 환각 방지)
  if ! whisper-cli -m "$MODEL" -l "$lang" -t 8 \
        "${VAD_FLAGS[@]}" \
        -mc 0 -sns \
        -otxt -of "$TMP/out" -f "$wav" -np >>"$LOG" 2>&1; then
    log "실패(음성 인식): $(basename "$src")"
    notify "실패: $(basename "$src")"
    return 1
  fi

  # 5) 30초 단위로 끊긴 줄을 한 줄에 한 문장으로 정리해서 저장
  /usr/bin/python3 -I "$ROOT/macos/textfmt.py" "$TMP/out.txt" "$base.txt" "$lang" 2>>"$LOG" ||
    sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' -e '/^$/d' "$TMP/out.txt" > "$base.txt"
  rm -f "$wav" "$TMP/out.txt" "$TMP/audio.m4a"

  secs=$(( $(date +%s) - start ))
  log "완료: $(basename "$base").txt (${secs}초)"
  notify "완료 ($label): $(basename "$base").txt ($((secs / 60))분 $((secs % 60))초)"
  # 완료되면 텍스트 파일을 바로 열어줌
  open -a TextEdit "$base.txt" >/dev/null 2>&1
}

# 처리할 파일이 없어질 때까지 반복 (변환 중에 새로 들어온 파일도 처리)
shopt -s nullglob nocaseglob
while :; do
  found=0
  for f in "$INBOX"/*.mp4 "$INBOX"/*.m4a "$INBOX"/*.mov; do
    [ -e "${f%.*}.txt" ] && continue
    [ -e "$f.failed" ] && continue
    found=1
    wait_stable "$f" || continue
    transcribe "$f" || touch "$f.failed"
  done
  [ $found -eq 0 ] && break
done
