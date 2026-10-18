"""English long-form benchmark on full recordings:
  ted       TED-LIUM 3 test, 11 complete TED talks (148 min) - the closest public
            stand-in for a recorded lecture
  earnings  Earnings-21 calls - phone-quality audio, many speakers and accents,
            dense domain vocabulary (a proxy for jargon-heavy lectures)

Compares this project's whisper.cpp pipeline with newer open models that run on
Apple Silicon through mlx-audio. Non-Whisper models get identical input: the
talk is split at the same Silero-VAD speech boundaries (tuned settings from
macos/transcribe.sh) into chunks of at most 30 s, which each model transcribes
independently.

Usage:   .venv-mlx/bin/python english.py <ted|earnings> [model ...]   (default: all models)
Results: results/en-<set>-<model>.json, summary tables in RESULTS-english.md
"""
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import jiwer
import numpy as np
import pyarrow.parquet as pq
import soundfile as sf
from whisper_normalizer.english import EnglishTextNormalizer

HERE = Path(__file__).parent
ROOT = HERE.parent
SETS = {
    "ted": {"data": HERE / "data" / "tedlium" / "test.parquet", "desc": "TED-LIUM 3: 11 full TED talks"},
    "earnings": {"data": HERE / "data" / "earnings21" / "test.parquet", "desc": "Earnings-21: full earnings calls",
                 "max_min": 95},
}
SET = "ted"
WORK = HERE / "work" / SET
RES = HERE / "results"
SR = 16000
MAX_CHUNK = 30.0

TURBO = ROOT / "models" / "ggml-large-v3-turbo.bin"
VAD = ROOT / "models" / "ggml-silero-v5.1.2.bin"
VAD_ARGS = ["-vt", "0.35", "-vp", "200", "-vsd", "300"]

# name -> (Hugging Face repo, generate() kwargs)
MLX_MODELS = {
    "granite-5.0-turboctc": ("ibm-granite/granite-speech-5.0-470m-turboctc", {}),
    "granite-4.1-2b": ("ibm-granite/granite-speech-4.1-2b", {}),
    "qwen3-asr-1.7b": ("mlx-community/Qwen3-ASR-1.7B-bf16", {"language": "English"}),
    "parakeet-tdt-0.6b-v2": ("mlx-community/parakeet-tdt-0.6b-v2", {}),
}

_norm = EnglishTextNormalizer()


def norm(text):
    text = text.replace("<unk>", " ")
    return re.sub(r"\s+", " ", _norm(text)).strip()


def talks():
    """Write each recording as 16 kHz mono WAV once; return [(wav, reference), ...].
    For earnings, keep the shortest calls up to max_min minutes in total."""
    WORK.mkdir(parents=True, exist_ok=True)
    index = WORK / "index.json"
    if index.exists():
        return [(WORK / w, r) for w, r in json.loads(index.read_text())]
    out = []
    rows = pq.read_table(SETS[SET]["data"]).to_pylist()
    for i, row in enumerate(rows):
        audio = row["audio"]
        if audio.get("bytes"):
            import io
            wav, sr = sf.read(io.BytesIO(audio["bytes"]), dtype="float32")
        else:
            wav, sr = np.asarray(audio["array"], dtype=np.float32), audio["sampling_rate"]
        if wav.ndim > 1:
            wav = wav.mean(1)
        if sr != SR:                                   # simple resample (earnings audio may be 8/44.1 kHz)
            wav = np.interp(np.arange(0, len(wav), sr / SR), np.arange(len(wav)), wav).astype(np.float32)
        name = f"talk{i:02d}.wav"
        sf.write(WORK / name, wav, SR, subtype="PCM_16")
        out.append((name, row["text"]))
    if "max_min" in SETS[SET]:
        out.sort(key=lambda x: sf.info(WORK / x[0]).duration)
        kept, total = [], 0.0
        for name, ref in out:
            d = sf.info(WORK / name).duration / 60
            if total + d > SETS[SET]["max_min"]:
                (WORK / name).unlink()
                continue
            kept.append((name, ref)); total += d
        out = kept
    index.write_text(json.dumps(out))
    return [(WORK / w, r) for w, r in out]


def vad_chunks(wav):
    """Same chunking as the app (macos/qwen_asr.py): VAD speech segments grouped into <= 30 s
    chunks, cut at the longest pause."""
    sys.path.insert(0, str(ROOT / "macos"))
    import qwen_asr
    return qwen_asr.chunks(wav)


def run_whispercpp(wav):
    """This project's macOS pipeline: volume normalisation + whisper.cpp turbo + tuned VAD."""
    tmp = WORK / "level.wav"
    subprocess.run(["/usr/bin/python3", "-I", str(ROOT / "macos" / "wavtool.py"), "level", str(wav), str(tmp)],
                   check=True, capture_output=True)
    out = WORK / "whisper-out"
    subprocess.run(["whisper-cli", "-m", str(TURBO), "-l", "en", "-t", "8", "--vad", "-vm", str(VAD), *VAD_ARGS,
                    "-mc", "0", "-sns", "-otxt", "-of", str(out), "-f", str(tmp), "-np"],
                   check=True, capture_output=True)
    return out.with_suffix(".txt").read_text(encoding="utf-8")


_loaded = {}


def run_mlx(name, wav):
    from mlx_audio.stt import load
    repo, kwargs = MLX_MODELS[name]
    if name not in _loaded:
        _loaded.clear()
        _loaded[name] = load(repo)
    model = _loaded[name]
    audio, _ = sf.read(wav, dtype="float32")
    texts = []
    for s, e in vad_chunks(wav):
        piece = audio[int(s * SR):int(e * SR)]
        if len(piece) < SR // 4:
            continue
        if name.startswith("parakeet"):              # parakeet's generate() takes mx.array, not numpy
            import mlx.core as mx
            piece = mx.array(piece)
        texts.append(model.generate(piece, **kwargs).text.strip())
    return " ".join(texts)


def evaluate(name):
    path = RES / f"en-{SET}-{name}.json"
    if path.exists():
        return json.loads(path.read_text())
    print(f"running {name} ...", flush=True)
    errors = n = ins = dels = 0
    audio_secs = wall = 0.0
    per_talk = []
    for wav, ref in talks():
        t = time.time()
        hyp = run_whispercpp(wav) if name == "whisper.cpp-turbo-pipeline" else run_mlx(name, wav)
        wall += time.time() - t
        (WORK / f"{wav.stem}.{name}.txt").write_text(hyp, encoding="utf-8")
        o = jiwer.process_words(norm(ref), norm(hyp))
        e = o.substitutions + o.deletions + o.insertions
        m = o.hits + o.substitutions + o.deletions
        errors, n, ins, dels = errors + e, n + m, ins + o.insertions, dels + o.deletions
        dur = sf.info(wav).duration
        audio_secs += dur
        per_talk.append(round(e / m, 4))
        print(f"  {wav.stem}: WER {e / m:.2%}  ({dur / 60:.1f} min)", flush=True)
    result = {"wer": errors / n, "ins": ins / n, "del": dels / n, "speed": audio_secs / wall,
              "audio_min": audio_secs / 60, "per_talk": per_talk}
    RES.mkdir(exist_ok=True)
    path.write_text(json.dumps(result, indent=1))
    print(f"  => {name}: WER {result['wer']:.2%}, {result['speed']:.1f}x real-time", flush=True)
    return result


def report():
    lines = [
        "# English long-form benchmark",
        "",
        "Full recordings, WER after Whisper's English normalizer, Apple M2. Non-Whisper models transcribe ≤30 s",
        "chunks of Silero-VAD speech. `qwen3-asr-1.7b` uses the app's chunker (macos/qwen_asr.py, cut at the longest",
        "pause); the other mlx models and `qwen3-asr-1.7b-greedy-chunks` were run with an earlier greedy chunker that",
        "cut wherever 30 s was reached. *Wrong words* are substitutions; most deletions on TED are repeated words",
        "(\"the the\") that Whisper tidies away but the verbatim references keep.",
    ]
    for set_name, meta in SETS.items():
        results = {p.stem[len(f"en-{set_name}-"):]: json.loads(p.read_text()) for p in sorted(RES.glob(f"en-{set_name}-*.json"))}
        if not results:
            continue
        rows = sorted(results.items(), key=lambda kv: kv[1]["wer"])
        lines += ["", f"## {meta['desc']} ({rows[0][1]['audio_min']:.0f} min)", "",
                  "| Model | WER | Wrong words | Deletions | Insertions | Speed |", "|---|---|---|---|---|---|"]
        for name, r in rows:
            sub = r["wer"] - r["ins"] - r["del"]
            lines.append(f"| {name} | {r['wer']:.2%} | {sub:.2%} | {r['del']:.2%} | {r['ins']:.2%} | {r['speed']:.1f}× |")
    (HERE / "RESULTS-english.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


def main():
    global SET, WORK
    SET = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] in SETS else "ted"
    WORK = HERE / "work" / SET
    names = [a for a in sys.argv[1:] if a not in SETS] or ["whisper.cpp-turbo-pipeline", *MLX_MODELS]
    for name in names:
        evaluate(name)
    report()


if __name__ == "__main__":
    main()
