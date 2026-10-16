# Lecture Transcriber

Drop a lecture video into a folder and get a text transcript next to it. Everything runs locally and offline, and it handles both Korean and English lectures.

```
📁 Lecture Inbox/
   week3-thermodynamics.mp4     ← you drop this in
   week3-thermodynamics.txt     ← this appears a few minutes later
```

- **Zero-click:** a background watcher picks up new files automatically. You get a notification when a file starts and when it finishes, and the transcript opens on its own.
- **Korean / English auto-detection:** the language is detected from the *middle* of the recording, not the intro (see [Design notes](#design-notes)).
- **Best open models per language:** Whisper `large-v3-turbo` for Korean (fast) and Whisper `large-v3` for English (most accurate open model on long-form English).
- **Silence-robust:** Silero VAD strips silent stretches before decoding. That stops Whisper from inventing text during long pauses, which is common in lecture recordings.
- **Private:** no cloud APIs, nothing leaves your machine.
- **macOS and Windows.**

## Install

### macOS (Apple Silicon)

Requirements: [Homebrew](https://brew.sh) and Xcode Command Line Tools (`xcode-select --install`).

```bash
git clone https://github.com/dongyeon1113/lecture-transcriber.git
cd lecture-transcriber
./macos/install.sh                   # watches ~/Lecture Inbox
./macos/install.sh ~/Desktop/lectures   # or any folder you like
```

The installer:
1. installs `whisper.cpp` via Homebrew
2. downloads the models (~4.7 GB) with resume support and SHA-256 checks
3. registers a `launchd` agent that watches the folder (it survives reboots)

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

> On CPU-only Windows machines, English also uses `large-v3-turbo`, because `large-v3` is too slow without a GPU.

## Usage

1. Put an `.mp4`, `.m4a` or `.mov` file in the inbox folder.
2. Wait for the **"done"** notification. The `.txt` file opens automatically.

| Situation | What to do |
|---|---|
| Re-transcribe a file | Delete its `.txt` file. It is processed again automatically. |
| A `file.mp4.failed` marker appeared | The file has no readable audio track. Delete the marker to retry. |
| Check progress or errors | macOS: `~/Library/Logs/lecture-transcriber.log` · Windows: `%LOCALAPPDATA%\lecture-transcriber\transcribe.log` |

## Uninstall

```bash
./macos/uninstall.sh
```
```powershell
powershell -ExecutionPolicy Bypass -File windows\uninstall.ps1
```

This stops the watcher. Your transcripts and the downloaded models are left in place; delete `models/` (macOS) or `%LOCALAPPDATA%\lecture-transcriber` (Windows) to reclaim disk space.

## How it works

```
new file in inbox
  └─ wait until the file size stops changing (download/copy finished)
  └─ extract audio → 16 kHz mono WAV          (macOS: afconvert / avconvert, Windows: ffmpeg)
  └─ language detection
       cut 30 s clips at 25 % / 50 % / 75 % of the recording
       run Whisper language ID on each → majority vote (en / ko)
  └─ transcribe with whisper.cpp
       ko → large-v3-turbo   en → large-v3
       Silero VAD on, no cross-segment context (-mc 0) to prevent repetition loops
  └─ write <name>.txt next to the video, notify, open it
```

| | macOS | Windows |
|---|---|---|
| ASR engine | whisper.cpp (Homebrew), Metal GPU | whisper.cpp official build, CUDA or CPU |
| Audio extraction | `afconvert` (built-in), `avconvert` fallback | `ffmpeg` |
| Folder watching | `launchd` `WatchPaths` | Startup-folder PowerShell loop (10 s poll) |
| Notifications | `osascript` | Windows toast |

## Design notes

**Why whisper.cpp + Whisper instead of newer models?** (surveyed October 2026)
- **NVIDIA Parakeet** is far faster on Apple Silicon, but it supports only European languages, so it has no Korean.
- **Qwen3-ASR 1.7B** had a slightly lower Korean CER in one small test: 3.34 vs 4.60 for turbo on 60 FLEURS utterances. The confidence intervals overlap, and it needs a multi-GB PyTorch stack. whisper.cpp is a single native binary with GPU acceleration on both platforms.
- On the [Open ASR Leaderboard](https://huggingface.co/blog/open-asr-leaderboard) **long-form** track, Whisper `large-v3` is the most accurate open model for English (WER 6.43 vs 6.68 for Parakeet CTC 1.1B). Long-form is what lectures are.

**Why detect the language from the middle?** whisper.cpp's language ID looks only at the first 30 s of audio, and its `--offset-t` flag does not change that. Lectures often open with a Korean greeting or attendance even when the lecture itself is in English, so the script cuts clips from three points in the recording and takes a majority vote.

**Why VAD?** Whisper is known to hallucinate text, often repeated phrases, on silence and background noise. Lecture recordings have many pauses. Silero VAD removes non-speech before decoding.

**Windows paths:** whisper.cpp can fail to open non-ASCII paths on Windows (for example a Korean user name). Models and temp files are therefore kept in an ASCII-only directory, and only ffmpeg touches the original file name.

## Performance

Measured on a MacBook Air M2 (16 GB) using synthetic TTS lecture audio:

| Audio | Model | Wall time | Speed |
|---|---|---|---|
| Korean, 2 min 42 s | large-v3-turbo (f16) | 16 s | ~10× real-time |
| English, 2 min 41 s | large-v3 (f16) | 34 s | ~4.7× real-time |

That works out to about **6–7 min** of processing for a 75-minute Korean lecture and about **16 min** for an English one. The times include language detection.

## Status

- **macOS:** tested end-to-end on Apple Silicon, including the folder watcher, Korean/English detection and the failure handling.
- **Windows:** the transcription logic was exercised on macOS with PowerShell 7 and stand-in tools. The installer has **not yet been run on real Windows hardware.** Issues and PRs are welcome.

## Note

Transcribe only recordings you are allowed to use. Lecture recordings and their transcripts are usually the instructor's copyrighted work, so keep them for personal study and do not redistribute them.
