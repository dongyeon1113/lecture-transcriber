"""영어 강의 인식: Qwen3-ASR 1.7B (MLX, Apple Silicon)
benchmark/english.py 에서 TED 강연·실적발표 통화 모두 whisper turbo 보다 오류가 적었음 (14개 녹음 중 12개).

  qwen_asr.py 입력.wav 출력.txt     인식 (입력: 16kHz 모노 WAV)
  qwen_asr.py --download             모델 받기 (install.sh 가 호출)

긴 녹음은 Silero VAD 말소리 경계에서 30초 이하 조각으로 잘라 하나씩 인식한다.
"""
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = "mlx-community/Qwen3-ASR-1.7B-bf16"
REVISION = "e1f6c266914abc5a46e8756e02580f834a6cf8a7"
SR = 16000
MAX_CHUNK = 30.0
ROOT = Path(__file__).resolve().parent.parent
VAD = ROOT / "models" / "ggml-silero-v5.1.2.bin"
VAD_ARGS = ["-vt", "0.35", "-vp", "200", "-vsd", "300"]   # macos/transcribe.sh 와 같은 설정


def download():
    # Xet 전송이 멈추는 경우가 있어 일반 HTTP 로 받고, 실패하면 이어받기로 재시도
    os.environ["HF_HUB_DISABLE_XET"] = "1"
    from huggingface_hub import snapshot_download
    for attempt in range(30):
        try:
            return snapshot_download(REPO, revision=REVISION)
        except Exception as e:  # 네트워크 오류
            print(f"  retrying ({type(e).__name__})", flush=True)
            time.sleep(5)
    sys.exit("model download failed")


def speech_segments(wav):
    """Silero VAD 말소리 구간 [(시작초, 끝초), ...]."""
    vad_cli = shutil.which("whisper-vad-speech-segments") or "/opt/homebrew/bin/whisper-vad-speech-segments"
    p = subprocess.run([vad_cli, "-vm", str(VAD), *VAD_ARGS, "-f", str(wav)],
                       capture_output=True, text=True, check=True)
    return [(float(a) / 100, float(b) / 100) for a, b in re.findall(r"start = ([\d.]+), end = ([\d.]+)", p.stdout)]


def plan_chunks(segs, max_len=MAX_CHUNK, min_len=10.0):
    """말소리 구간을 max_len 초 이하 조각으로 묶음. 조각을 끊어야 할 때는 (min_len 초 이후의)
    가장 긴 쉼에서 끊는다 — 문장 중간에서 잘려 마침표가 잘못 찍히는 일을 줄이기 위함."""
    pieces = []
    for s, e in segs:                                   # 아주 긴 구간은 미리 max_len 단위로 자름
        while e - s > max_len:
            pieces.append((s, s + max_len))
            s += max_len
        pieces.append((s, e))
    chunks, cur = [], []
    for seg in pieces:
        while cur and seg[1] - cur[0][0] > max_len:
            best, best_gap = len(cur), -1.0
            for i in range(1, len(cur) + 1):
                if cur[i - 1][1] - cur[0][0] < min_len:
                    continue
                gap = (cur[i][0] if i < len(cur) else seg[0]) - cur[i - 1][1]
                if gap > best_gap:
                    best, best_gap = i, gap
            chunks.append((cur[0][0], cur[best - 1][1]))
            cur = cur[best:]
        cur.append(seg)
    if cur:
        chunks.append((cur[0][0], cur[-1][1]))
    return chunks


def chunks(wav):
    return plan_chunks(speech_segments(wav))


def transcribe(src, dst):
    os.environ["HF_HUB_OFFLINE"] = "1"               # 실행 중에는 네트워크 접속 안 함
    import soundfile as sf
    from huggingface_hub import snapshot_download
    from mlx_audio.stt import load

    model = load(snapshot_download(REPO, revision=REVISION))
    audio, sr = sf.read(src, dtype="float32")
    assert sr == SR, sr
    lines = []
    for s, e in chunks(src):
        piece = audio[int(s * SR):int(e * SR)]
        if len(piece) < SR // 4:
            continue
        text = model.generate(piece, language="English").text.strip()
        if text:
            lines.append(text)
    Path(dst).write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    if sys.argv[1:] == ["--download"]:
        download()
    else:
        transcribe(*sys.argv[1:3])
