# Lecture Transcriber

Drop a lecture video into a folder and get a text transcript next to it. Everything runs locally and offline, and it handles both Korean and English lectures.

```
📁 Lecture Inbox/
   week3-thermodynamics.mp4     ← you drop this in
   week3-thermodynamics.txt     ← this appears a few minutes later
```

- **Zero-click:** a background watcher picks up new files automatically. You get a notification when a file starts and when it finishes, and the transcript opens on its own.
- **Korean / English auto-detection:** the language is detected from the *middle* of the recording, so a Korean greeting before an English lecture doesn't fool it. It was right on 30/30 test recordings; Whisper's built-in detection got 20/30.
- **Best measured model per language:** Korean uses Whisper `large-v3-turbo`. English uses **Qwen3-ASR 1.7B** on macOS. We compared five current open models on 4 hours of full-length English recordings, and Qwen3-ASR made **30% fewer errors** than Whisper on TED talks (WER 2.12% vs 3.04%) and was better on 13 of 14 recordings.
- **Knows computer-science vocabulary:** English lectures are transcribed with a ~300-term CS glossary (`glossary/computer-science.txt`): OS, architecture, algorithms, networks, databases, security and ML. On a real 59-minute operating-systems lecture, misheard technical terms fell from 39 to 22 (e.g. "Peter thread" → pthread, "less condition" → race condition, "thread pull" → thread pool). Add your own course terms as another `.txt` in `glossary/`.
- **Built for long recordings:** in our benchmark, plain whisper.cpp hit 21% WER on a 27-minute lecture-style recording because it hallucinated repeated sentences. This project's settings get **5.5%**.
- **Handles quiet recordings:** quiet audio is boosted automatically, so the speech detector doesn't throw away soft-spoken lectures.
- **Readable output:** one sentence per line, with punctuation, instead of Whisper's raw 30-second fragments.
- **Private:** no cloud APIs, nothing leaves your machine.
- **macOS and Windows.**

All design choices are backed by a reproducible benchmark. See [Benchmark](#benchmark), [`benchmark/RESULTS.md`](benchmark/RESULTS.md) and [`benchmark/RESULTS-english.md`](benchmark/RESULTS-english.md).

## Install

### macOS (Apple Silicon)

Requirements: [Homebrew](https://brew.sh) and Xcode Command Line Tools (`xcode-select --install`).

```bash
git clone https://github.com/dongyeon1113/lecture-transcriber.git
cd lecture-transcriber
./macos/install.sh                      # watches ~/Lecture Inbox
./macos/install.sh ~/Desktop/lectures   # or any folder you like
```

The installer:
1. installs `whisper.cpp` via Homebrew
2. downloads the Whisper and VAD models (~1.6 GB) with resume support and SHA-256 checks
3. sets up Qwen3-ASR for English: installs `uv`, creates a Python 3.12 environment in `.venv/` with pinned `mlx-audio`, and downloads the model at a pinned revision (~3.8 GB)
4. registers a `launchd` agent that watches the folder (it survives reboots)

### Windows 10/11

Open PowerShell in the cloned (or unzipped) folder:

```powershell
powershell -ExecutionPolicy Bypass -File windows\install.ps1
powershell -ExecutionPolicy Bypass -File windows\install.ps1 -Inbox "D:\Lectures"   # custom folder
```

The installer:
1. installs `ffmpeg` via `winget` if it is missing
2. downloads the official `whisper.cpp` Windows build. It picks the **CUDA** build when an NVIDIA GPU is present and checks that it actually runs. Otherwise it uses the CPU build.
3. downloads the models, with SHA-256 checks
4. adds a hidden watcher to the Startup folder (it survives reboots)

> On Windows, English lectures also use Whisper `large-v3-turbo`, because the Qwen3-ASR runtime used here (MLX) is Apple-Silicon-only.

## Usage

1. Put an `.mp4`, `.m4a` or `.mov` file in the inbox folder.
2. Wait for the **"done"** notification. The `.txt` file opens automatically.

| Situation | What to do |
|---|---|
| Re-transcribe a file | Delete its `.txt` file. It is processed again automatically. |
| Add course-specific terms (English) | Put a `.txt` file with one term per line in `glossary/`. All files there are used. |
| A `file.mp4.failed` marker appeared | The file has no readable audio track. Delete the marker to retry. |
| Check progress or errors | macOS: `~/Library/Logs/lecture-transcriber.log` · Windows: `%LOCALAPPDATA%\lecture-transcriber\transcribe.log` |

## Uninstall

```bash
./macos/uninstall.sh
```
```powershell
powershell -ExecutionPolicy Bypass -File windows\uninstall.ps1
```

This stops the watcher. Your transcripts and the downloaded models are left in place. To reclaim disk space on macOS, delete `models/` and `.venv/` (~1.6 GB) and the Qwen3-ASR model at `~/.cache/huggingface/hub/models--mlx-community--Qwen3-ASR-1.7B-bf16` (~3.8 GB). On Windows, delete `%LOCALAPPDATA%\lecture-transcriber`.

## How it works

```
new file in inbox
  └─ wait until the file size stops changing (download/copy finished)
  └─ extract audio → 16 kHz mono WAV          (macOS: afconvert / avconvert, Windows: ffmpeg)
  └─ volume normalisation: if the peak is below -10 dBFS, boost it to -1 dBFS (max +40 dB)
  └─ language detection
       cut 30 s clips at 25 % / 50 % / 75 % of the recording
       run Whisper language ID on each → majority vote (en / ko)
  └─ transcribe
       Korean (and English on Windows): whisper.cpp large-v3-turbo
         -mc 0       no text context between 30 s windows (stops repetition loops)
         Silero VAD  threshold 0.35, 200 ms padding, 300 ms min silence
       English on macOS: Qwen3-ASR 1.7B via mlx-audio
         speech segments from the same VAD, grouped into ≤30 s chunks that are cut at the
         longest pause (fewer sentences split mid-way); falls back to whisper.cpp on error
         glossary/*.txt is passed as context ("hotwords") so CS terms are recognised
  └─ re-flow the fragments into one sentence per line
     (English: capitalise sentence starts; abbreviations such as "Mr." and "U.S." are not split)
  └─ write <name>.txt next to the video, notify, open it
```

| | macOS | Windows |
|---|---|---|
| ASR engine | Korean: whisper.cpp (Metal GPU) · English: Qwen3-ASR (MLX) | whisper.cpp official build, CUDA or CPU |
| Audio extraction | `afconvert` (built-in), `avconvert` fallback | `ffmpeg` |
| Volume normalisation | `audioop` in the system Python | `ffmpeg` `volumedetect` + `volume` |
| Folder watching | `launchd` `WatchPaths` | Startup-folder PowerShell loop (10 s poll) |
| Notifications | `osascript` | Windows toast |

## Benchmark

`benchmark/` builds test sets from [FLEURS](https://huggingface.co/datasets/google/fleurs), which provides read speech with reference transcripts. It then scores every design decision on an Apple M2. Korean is scored with CER and English with WER, both after Whisper's text normalizers. Full tables are in [`benchmark/RESULTS.md`](benchmark/RESULTS.md).

**1. Long recordings need different settings than short clips.** One FLEURS sentence on its own gives 4.9% WER, but the same sentences inside a 27-minute "lecture" with pauses give 21.2% with default settings. Almost all of the extra error is *inserted* text: Whisper carries its previous output forward as context and starts repeating it during pauses. Turning that off (`-mc 0`) fixes most of it.

| English, 27 min, turbo | WER | Insertions | Deletions | Speed |
|---|---|---|---|---|
| whisper.cpp defaults | 21.24% | 17.10% | 0.59% | 9.2× |
| `-mc 0` | 6.05% | 2.23% | 0.91% | 12.9× |
| `-mc 0` + VAD at default settings *(first version)* | 6.14% | 1.82% | 0.86% | 21.0× |
| **`-mc 0` + tuned VAD + volume normalisation** | **5.50%** | 2.09% | 0.64% | 19.8× |

**2. VAD at default settings was clipping speech.** It made processing faster, but on Korean it *raised* CER from 3.41% to 3.98%, because deletions more than doubled. Loosening it (threshold 0.5 → 0.35, padding 30 → 200 ms, minimum silence 100 → 300 ms) keeps the speed-up and gives the lowest error for both languages: CER 3.34% and WER 5.50%.

**3. Quiet recordings break VAD, not Whisper.** At -35 dB, Whisper alone still scores 5.5%, but with VAD it falls to 15.6%: the speech detector treats quiet speech as silence and drops 10% of the words. Boosting the volume before VAD brings it back to **5.32%**.

**4. Whisper's built-in language detection only listens to the first 30 seconds** (`--offset-t` does not change this). On English lectures that open with a 40-second Korean introduction it was wrong 10/10 times. Voting over three clips from the middle was right 30/30 times across Korean, English and Korean-intro recordings.

**5. `large-v3` vs `large-v3-turbo`:** on these sets the two are within noise of each other. Short-form English WER was 4.64% vs 4.87%, with overlapping 95% confidence intervals, and long-form English was 5.55% vs 5.50%. Turbo is about 2.5× faster, so `large-v3` was dropped.

Caveats: FLEURS is read speech, and the long recordings are built from it, so they are not real lectures. Each configuration was run once. Korean CER also counts number formatting as errors ("네 가지" vs "4가지").

### Choosing the English model

The Open ASR Leaderboard ranks models on short clips. To pick an English model for lectures, `benchmark/english.py` runs the strongest open models that work on Apple Silicon over **full-length real recordings**:
- [TED-LIUM 3](https://huggingface.co/datasets/distil-whisper/tedlium-long-form): 11 complete TED talks, 148 min, the closest public stand-in for a lecture.
- [Earnings-21](https://huggingface.co/datasets/hf-audio/asr-leaderboard-longform): 3 earnings calls, 92 min, with phone audio, many speakers and dense jargon.

All non-Whisper models get the same ≤30 s VAD chunks. Full table: [`benchmark/RESULTS-english.md`](benchmark/RESULTS-english.md).

| Model (Oct 2026) | Leaderboard WER (short clips) | TED talks WER | Earnings calls WER | Speed on M2 |
|---|---|---|---|---|
| **Qwen3-ASR 1.7B** | 5.76% | **2.12%** | **8.48%** | 3–5× |
| Whisper large-v3-turbo + this pipeline | ~7.8% | 3.04% | 9.74% | 10× |
| IBM Granite Speech 5.0 TurboCTC | ~5.0% | 3.16% | 9.19% | 51–77× |
| NVIDIA Parakeet TDT 0.6B v2 | ~6.0% | 3.18% | 9.57% | 30–45× |
| IBM Granite Speech 4.1 2B | 5.33% | 3.73% | – | 3× |

- **Leaderboard rank did not predict lecture accuracy.** Granite 4.1, which had the best leaderboard score, came last on the TED talks.
- **Qwen3-ASR beat Whisper on 13 of 14 recordings**, with 1 tie, and it is the model the app now uses for English.
- **Most of the gap on TED comes from verbatim style.** Qwen3-ASR keeps repeated words ("in in a"), as the reference transcripts do, while Whisper tidies them away. On wrong words alone the two are close: 0.92% vs 0.87% on TED and 4.35% vs 4.47% on earnings calls. Qwen3-ASR also drops fewer passages and adds less spurious text.
- **Trade-off:** Qwen3-ASR is about 3× slower than Whisper turbo, roughly 15–25 min for a 75-minute lecture on an M2.
- **CS glossary:** passing the ~300-term glossary as context cut misheard technical terms on a 59-minute OS lecture from 39 to 22. Ordinary words not in the list were unaffected. On TED talks, where the glossary is irrelevant, WER stayed the same (2.12% → 2.14%, 4 talks better and 6 worse), so it does not make general speech worse. It costs about 20–40% more time (the list is re-read for every 30 s chunk); the 59-minute lecture took 11 min instead of 7.6.
- **Not tested:** Cohere Transcribe (5.42% on the leaderboard) needs gated Hugging Face access. ARK-ASR-3B and Canary-Qwen 2.5B have no Apple Silicon runtime.

Reproduce it:

```bash
cd benchmark
./download.sh                                      # FLEURS ko/en test split (~500 MB) + large-v3 for comparison (~3.1 GB)
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python prepare.py                        # builds the test sets (deterministic)
.venv/bin/python run.py                            # ~1.5 h on an M2; writes RESULTS.md

# English model comparison (needs Python 3.12: brew install uv)
uv venv --python 3.12 .venv-mlx && uv pip install --python .venv-mlx/bin/python -r ../macos/requirements.txt jiwer whisper-normalizer pyarrow jinja2
mkdir -p data/tedlium data/earnings21
curl -L -o data/tedlium/test.parquet https://huggingface.co/datasets/distil-whisper/tedlium-long-form/resolve/main/data/test-00000-of-00001-7a1bb92f62e929b8.parquet
curl -L -o data/earnings21/test.parquet https://huggingface.co/datasets/hf-audio/asr-leaderboard-longform/resolve/main/earnings21/test-00008-of-00010.parquet
.venv-mlx/bin/python english.py ted        # all models; then: english.py earnings
```

## Design notes

**Why Whisper for Korean?** whisper.cpp is a single native binary with GPU acceleration on both platforms, and the tuned pipeline reaches 3.3% CER on the FLEURS long-form set. NVIDIA Parakeet and IBM Granite do not support Korean. Qwen3-ASR does support Korean, and one small external test put it slightly ahead (3.34 vs 4.60 CER on 60 FLEURS utterances, overlapping confidence intervals). It has not yet been benchmarked with this pipeline.

**Why Qwen3-ASR for English, and only on macOS?** It was the most accurate model in our full-length English comparison (above). It was first rejected because it needed a multi-GB PyTorch stack, but `mlx-audio` now runs it natively on Apple Silicon. Windows keeps Whisper turbo until there is a comparable runtime.

**Why not prompt Whisper for punctuation?** An initial prompt such as "Hello, everyone. Welcome to today's lecture." is the usual trick, but it is dropped when `-mc 0` is set. With a small context (`-mc 32`) plus `--carry-initial-prompt`, English punctuation barely changed and Korean CER rose from 3.3% to 8.9%. With turbo, punctuation density already matches the references: 11.7 vs 11.0 marks per 100 words. About 3% of lines can still come out unpunctuated when Whisper switches style for one 30-second window.

**Windows paths:** whisper.cpp can fail to open non-ASCII paths on Windows (for example a Korean user name). Models and temp files are therefore kept in an ASCII-only directory, and only ffmpeg touches the original file name.

## Status

- **macOS:** tested end-to-end on Apple Silicon, including the folder watcher, Korean/English detection, the Qwen3-ASR English path, volume normalisation, sentence re-flow and the failure handling.
- **Windows:** `transcribe.ps1` was run end-to-end on macOS with PowerShell 7 and a real ffmpeg, covering volume normalisation, language detection, sentence re-flow (byte-identical to the macOS output), Unicode and bracketed file names, and the failure marker. The installer, toasts and the Startup watcher have **not yet been run on real Windows hardware.** Issues and PRs are welcome.

## Note

Transcribe only recordings you are allowed to use. Lecture recordings and their transcripts are usually the instructor's copyrighted work, so keep them for personal study and do not redistribute them.
