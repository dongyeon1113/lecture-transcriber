"""Run every benchmark experiment with whisper.cpp and write RESULTS.md.

Each run is cached in results/<name>.json, so an interrupted benchmark resumes
where it stopped. Delete a file to re-run that experiment.

Metrics
  Korean  CER  (characters, whitespace removed) after Whisper's BasicTextNormalizer
  English WER  after Whisper's EnglishTextNormalizer
  "ins"  insertion rate = inserted units / reference units; this is where
         hallucinated text shows up
  speed  audio duration / wall-clock time (includes model loading)
"""
import json
import platform
import re
import subprocess
import sys
import time
from pathlib import Path

import jiwer
import numpy as np
import soundfile as sf
from whisper_normalizer.basic import BasicTextNormalizer
from whisper_normalizer.english import EnglishTextNormalizer

HERE = Path(__file__).parent
SETS = HERE / "sets"
RES = HERE / "results"
WORK = HERE / "work"
MODELS = HERE.parent / "models"
WHISPER = "whisper-cli"
THREADS = "8"

MODEL_FILES = {"turbo": "ggml-large-v3-turbo.bin", "large-v3": "ggml-large-v3.bin"}
VAD = str(MODELS / "ggml-silero-v5.1.2.bin")
WAVTOOL = HERE.parent / "macos" / "wavtool.py"

# Long-form settings compared in experiment 2. `level` = run the pipeline's
# volume normalisation (macos/wavtool.py level) before whisper.
VAD_TUNED = ["--vad", "-vm", VAD, "-vt", "0.35", "-vp", "200", "-vsd", "300"]
CONFIGS = {
    "default":    {"flags": [], "level": False},
    "mc0":        {"flags": ["-mc", "0"], "level": False},
    "mc0+vad":    {"flags": ["--vad", "-vm", VAD, "-mc", "0", "-sns"], "level": False},   # first version
    "pipeline":   {"flags": VAD_TUNED + ["-mc", "0", "-sns"], "level": True},          # = macos/transcribe.sh
    "pipeline-no-level": {"flags": VAD_TUNED + ["-mc", "0", "-sns"], "level": False},
}
QUIET_DB = -35   # experiment 4: the English long-form recording made this much quieter

_basic, _english = BasicTextNormalizer(), EnglishTextNormalizer()


def norm(lang, text):
    if lang == "ko":
        return re.sub(r"\s+", "", _basic(text))
    return re.sub(r"\s+", " ", _english(text)).strip()


def score(lang, refs, hyps):
    """Corpus-level error, insertion and deletion rates, plus per-item counts."""
    refs = [norm(lang, r) for r in refs]
    hyps = [norm(lang, h) for h in hyps]
    per_item = []
    for r, h in zip(refs, hyps):
        out = (jiwer.process_characters if lang == "ko" else jiwer.process_words)(r, h)
        errors = out.substitutions + out.deletions + out.insertions
        per_item.append((errors, out.insertions, out.deletions, out.hits + out.substitutions + out.deletions))
    e, i, d, n = (sum(x) for x in zip(*per_item))
    return e / n, i / n, d / n, per_item


def bootstrap_ci(per_item, iters=2000, seed=0):
    rng = np.random.default_rng(seed)
    arr = np.array([(e, n) for e, _, _, n in per_item], dtype=float)
    idx = rng.integers(0, len(arr), size=(iters, len(arr)))
    rates = arr[idx, 0].sum(1) / arr[idx, 1].sum(1)
    return float(np.percentile(rates, 2.5)), float(np.percentile(rates, 97.5))


def whisper(args, quiet=True):
    """quiet=False keeps whisper's log, which carries the detected language."""
    t = time.time()
    p = subprocess.run([WHISPER, "-t", THREADS, *(["-np"] if quiet else []), *args], capture_output=True, text=True)
    if p.returncode != 0:
        sys.exit(f"whisper-cli failed: {' '.join(args)}\n{p.stderr[-2000:]}")
    return time.time() - t, p.stderr


def cached(name, fn):
    path = RES / f"{name}.json"
    if path.exists():
        return json.loads(path.read_text())
    print(f"running {name} ...", flush=True)
    result = fn()
    RES.mkdir(exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=1))
    print(f"  {name}: {json.dumps({k: v for k, v in result.items() if k != 'hyp'}, ensure_ascii=False)}", flush=True)
    return result


def read_txt(path):
    return " ".join(line.strip() for line in path.read_text(encoding="utf-8").splitlines())


def run_short(lang, model):
    src = SETS / "short" / lang
    refs = json.loads((src / "refs.json").read_text(encoding="utf-8"))
    work = WORK / f"short-{lang}-{model}"
    work.mkdir(parents=True, exist_ok=True)
    files = []
    for name in refs:
        link = work / name
        if not link.exists():
            link.symlink_to((src / name).resolve())
        files += ["-f", str(link)]
    secs, _ = whisper(["-m", str(MODELS / MODEL_FILES[model]), "-l", lang, "-otxt", *files])
    hyps = [read_txt(work / f"{name}.txt") for name in refs]
    rate, ins, dele, per_item = score(lang, list(refs.values()), hyps)
    audio = sum(sf.info(src / n).duration for n in refs)
    lo, hi = bootstrap_ci(per_item)
    return {"rate": rate, "ci": [lo, hi], "ins": ins, "del": dele, "speed": audio / secs, "audio_min": audio / 60}


def quiet_wav():
    path = WORK / "en-quiet.wav"
    if not path.exists():
        audio, sr = sf.read(SETS / "long" / "en.wav", dtype="float32")
        sf.write(path, audio * 10 ** (QUIET_DB / 20), sr, subtype="PCM_16")
    return path


def run_long(lang, model, config, quiet=False):
    wav = quiet_wav() if quiet else SETS / "long" / f"{lang}.wav"
    refs = json.loads((SETS / "long" / f"{lang}.json").read_text(encoding="utf-8"))
    out = WORK / f"{'quiet' if quiet else 'long'}-{lang}-{model}-{config}"
    out.parent.mkdir(parents=True, exist_ok=True)
    cfg = CONFIGS[config]
    t = time.time()
    if cfg["level"]:
        levelled = out.with_suffix(".in.wav")
        subprocess.run(["/usr/bin/python3", "-I", str(WAVTOOL), "level", str(wav), str(levelled)], check=True)
        wav_in = levelled
    else:
        wav_in = wav
    level_secs = time.time() - t
    secs, _ = whisper(["-m", str(MODELS / MODEL_FILES[model]), "-l", lang, *cfg["flags"],
                       "-otxt", "-of", str(out), "-f", str(wav_in)])
    secs += level_secs
    hyp = read_txt(out.with_suffix(".txt"))
    rate, ins, dele, _ = score(lang, [" ".join(refs)], [hyp])
    audio = sf.info(wav).duration
    return {"rate": rate, "ins": ins, "del": dele, "speed": audio / secs, "audio_min": audio / 60}


def detect(wav):
    _, err = whisper(["-m", str(MODELS / MODEL_FILES["turbo"]), "-l", "auto", "-dl",
                      *VAD_TUNED, "-f", str(wav)], quiet=False)
    m = re.search(r"auto-detected language: ([a-z]+)", err)
    return m.group(1) if m else "?"


def run_langid():
    labels = json.loads((SETS / "langid" / "labels.json").read_text())
    clip = WORK / "clip.wav"
    clip.parent.mkdir(parents=True, exist_ok=True)
    rows = {}
    for name, label in labels.items():
        wav = SETS / "langid" / name
        # A) whisper default: language from the first 30 s
        first = detect(wav)
        # B) this project: 30 s clips at 25/50/75 %, majority vote
        audio, sr = sf.read(wav, dtype="int16")
        votes = []
        for frac in (0.25, 0.5, 0.75):
            start = min(int(len(audio) * frac), len(audio) - 30 * sr)
            sf.write(clip, audio[max(0, start):max(0, start) + 30 * sr], sr, subtype="PCM_16")
            votes.append(detect(clip))
        vote = "en" if votes.count("en") >= 2 else "ko"
        rows[name] = {"label": label, "first30": first, "vote3": vote, "votes": votes}
    return {"rows": rows}


def pct(x):
    return f"{x * 100:.2f}%"


def write_report(short, long, quiet, langid):
    ver = subprocess.run(["brew", "list", "--versions", "whisper.cpp"], capture_output=True, text=True).stdout.strip()
    chip = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True).stdout.strip()
    metric = {"ko": "CER", "en": "WER"}
    lines = [
        "# Benchmark results",
        "",
        f"Generated by `benchmark/run.py` · {ver} · {chip} · macOS {platform.mac_ver()[0]} · {THREADS} threads",
        "",
        "Data: [FLEURS](https://huggingface.co/datasets/google/fleurs) test split (CC-BY 4.0), 100 sentences per language,",
        "one recording per sentence, sampled with a fixed seed. Korean is scored with CER (whitespace removed),",
        "English with WER, both after Whisper's text normalizers. Lower is better.",
        "",
        "## 1. Short-form accuracy (single sentences, default whisper.cpp settings)",
        "",
        "| Language | Model | Error rate | 95% CI | Speed |",
        "|---|---|---|---|---|",
    ]
    for (lang, model), r in short.items():
        lines.append(f"| {lang} | {model} | {metric[lang]} {pct(r['rate'])} | {pct(r['ci'][0])} – {pct(r['ci'][1])} | {r['speed']:.1f}× |")
    desc = {
        "default": "whisper.cpp defaults",
        "mc0": "`-mc 0` (no text context carried between windows)",
        "mc0+vad": "`-mc 0` + Silero VAD at default settings (first version of this project)",
        "pipeline": "**this project**: `-mc 0` + tuned VAD + volume normalisation",
        "pipeline-no-level": "tuned VAD + `-mc 0`, without volume normalisation",
    }
    lines += [
        "",
        "## 2. Long-form, lecture-like recordings",
        "",
        "The same 100 sentences joined into one recording: every sentence levelled to the same speech level,",
        "3–10 s pauses, continuous room noise underneath (~34 dB SNR)",
        f"(Korean {long[('ko', 'turbo', 'default')]['audio_min']:.0f} min, English {long[('en', 'turbo', 'default')]['audio_min']:.0f} min).",
        "Insertions are where hallucinated text shows up; deletions are speech that was dropped.",
        "",
        "| Language | Model | Settings | Error rate | Insertions | Deletions | Speed |",
        "|---|---|---|---|---|---|---|",
    ]
    for (lang, model, config), r in long.items():
        lines.append(f"| {lang} | {model} | {desc[config]} | {metric[lang]} {pct(r['rate'])} | {pct(r['ins'])} | {pct(r['del'])} | {r['speed']:.1f}× |")
    lines += [
        "",
        "## 3. Quietly recorded lecture",
        "",
        f"The English long-form recording at {QUIET_DB} dB (peak ≈ -38 dBFS), as from a distant or low-gain microphone.",
        "",
        "| Settings | WER | Deletions |",
        "|---|---|---|",
    ]
    for config, r in quiet.items():
        lines.append(f"| {desc[config]} | {pct(r['rate'])} | {pct(r['del'])} |")
    rows = langid["rows"]
    kinds = {"ko": "Korean lecture", "en": "English lecture", "ko-intro-en": "English lecture with ~40 s Korean intro"}
    lines += [
        "",
        "## 4. Language detection",
        "",
        "Recordings of ~3 minutes. `first 30 s` is whisper.cpp's built-in detection;",
        "`3-point vote` is this project's method (30 s clips at 25 / 50 / 75 %, majority vote).",
        "",
        "| Recording type | n | first 30 s | 3-point vote |",
        "|---|---|---|---|",
    ]
    for kind, desc in kinds.items():
        sel = [v for k, v in rows.items() if re.fullmatch(rf"{re.escape(kind)}-\d+\.wav", k)]
        a = sum(v["first30"] == v["label"] for v in sel)
        b = sum(v["vote3"] == v["label"] for v in sel)
        lines.append(f"| {desc} | {len(sel)} | {a}/{len(sel)} | {b}/{len(sel)} |")
    (HERE / "RESULTS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


def main():
    short = {(l, m): cached(f"short-{l}-{m}", lambda l=l, m=m: run_short(l, m))
             for l in ("ko", "en") for m in ("turbo", "large-v3")}
    # large-v3 with default settings is left out: on long recordings it falls into
    # repetition loops and ran at ~0.06x real-time (8 h for 27 min) in an earlier run.
    runs = [(l, "turbo", c) for l in ("ko", "en") for c in ("default", "mc0", "mc0+vad", "pipeline")]
    runs += [(l, "large-v3", c) for l in ("ko", "en") for c in ("mc0", "pipeline")]
    long = {(l, m, c): cached(f"long-{l}-{m}-{c}", lambda l=l, m=m, c=c: run_long(l, m, c)) for l, m, c in runs}
    quiet = {c: cached(f"quiet-en-turbo-{c}", lambda c=c: run_long("en", "turbo", c, quiet=True))
             for c in ("mc0", "pipeline-no-level", "pipeline")}
    langid = cached("langid", run_langid)
    write_report(short, long, quiet, langid)


if __name__ == "__main__":
    main()
