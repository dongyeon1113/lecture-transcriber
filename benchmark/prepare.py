"""Build the benchmark sets from the FLEURS test split.

Outputs (under benchmark/sets/):
  short/{ko,en}/NNN.wav + refs.json   100 single utterances per language
  long/{ko,en}.wav      + refs.json   the same 100 utterances joined into one
                                      lecture-like recording: every sentence
                                      levelled to a common speech level, 3-10 s
                                      pauses, continuous room noise underneath
                                      (spans.json has each sentence's start/end)
  langid/*.wav          + labels.json multi-minute recordings for language ID:
                                      Korean-only, English-only, and English
                                      lectures that open with ~40 s of Korean

Everything is deterministic (fixed seed).
"""
import csv
import json
import random
from pathlib import Path

import numpy as np
import soundfile as sf

SR = 16000
N_UTTS = 100
SEED = 0
SPEECH_DB = -26            # active speech level every sentence is levelled to (dBFS)
NOISE_DB = -60             # continuous room tone (dBFS RMS) → ~34 dB SNR
GAP_RANGE = (3.0, 10.0)    # seconds of pause between utterances
LANGID_PER_KIND = 10

HERE = Path(__file__).parent
DATA = HERE / "data"
OUT = HERE / "sets"
LANGS = {"ko": "ko_kr", "en": "en_us"}


def load_split(code):
    """One recording per sentence id: [(wav_path, raw_transcription), ...]"""
    seen, rows = set(), []
    with open(DATA / code / "test.tsv", encoding="utf-8") as f:
        for row in csv.reader(f, delimiter="\t", quoting=csv.QUOTE_NONE):
            sid, fname, raw = row[0], row[1], row[2]
            if sid in seen:
                continue
            seen.add(sid)
            rows.append((DATA / code / "test" / fname, raw.replace('""', '"').strip('"')))
    rows.sort(key=lambda r: r[0].name)
    return rows


def read(path):
    audio, sr = sf.read(path, dtype="float32")
    assert sr == SR, (path, sr)
    return audio


def level(audio):
    """Scale so the active-speech RMS is SPEECH_DB. FLEURS recording levels vary
    by >40 dB, which no single lecture recording would."""
    frames = audio[: len(audio) // 320 * 320].reshape(-1, 320)
    rms = np.sqrt((frames ** 2).mean(1)) + 1e-9
    active = rms[rms > rms.max() * 10 ** (-30 / 20)]          # frames within 30 dB of the loudest
    gain = 10 ** (SPEECH_DB / 20) / np.sqrt((active ** 2).mean())
    return (audio * gain).astype(np.float32)


def silence(seconds):
    return np.zeros(int(seconds * SR), dtype=np.float32)


def write(path, audio):
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(path, np.clip(audio, -1, 1), SR, subtype="PCM_16")


def concat(rng, items, lead=1.0):
    """Join levelled utterances with pauses over continuous room noise.
    Returns audio, refs, [(start_s, end_s), ...]."""
    parts, refs, spans = [silence(lead)], [], []
    t = len(parts[0])
    for wav, ref in items:
        speech = level(read(wav))
        spans.append((t / SR, (t + len(speech)) / SR))
        parts += [speech, silence(rng.uniform(*GAP_RANGE))]
        t += len(speech) + len(parts[-1])
        refs.append(ref)
    audio = np.concatenate(parts)
    audio += (rng.standard_normal(len(audio)) * 10 ** (NOISE_DB / 20)).astype(np.float32)
    return audio, refs, spans


def take_until(rng, pool, seconds):
    """Random utterances (with replacement) until `seconds` of speech."""
    items, total = [], 0.0
    while total < seconds:
        wav, ref = pool[rng.integers(len(pool))]
        items.append((wav, ref))
        total += sf.info(wav).duration
    return items


def main():
    rng = np.random.default_rng(SEED)
    pick = random.Random(SEED)
    rest = {}

    for lang, code in LANGS.items():
        rows = load_split(code)
        chosen = pick.sample(rows, N_UTTS)
        rest[lang] = [r for r in rows if r not in chosen]

        refs = {}
        for i, (wav, ref) in enumerate(chosen):
            name = f"{i:03d}.wav"
            write(OUT / "short" / lang / name, read(wav))
            refs[name] = ref
        (OUT / "short" / lang / "refs.json").write_text(json.dumps(refs, ensure_ascii=False, indent=1), encoding="utf-8")

        audio, long_refs, spans = concat(rng, chosen)
        write(OUT / "long" / f"{lang}.wav", audio)
        (OUT / "long" / f"{lang}.json").write_text(json.dumps(long_refs, ensure_ascii=False, indent=1), encoding="utf-8")
        (OUT / "long" / f"{lang}.spans.json").write_text(json.dumps(spans), encoding="utf-8")
        print(f"{lang}: {N_UTTS} utterances, long-form {len(audio) / SR / 60:.1f} min")

    labels = {}
    for i in range(LANGID_PER_KIND):
        for kind, parts, label in [
            ("ko", [("ko", 150)], "ko"),
            ("en", [("en", 150)], "en"),
            ("ko-intro-en", [("ko", 40), ("en", 150)], "en"),
        ]:
            items = []
            for lang, secs in parts:
                items += take_until(rng, rest[lang], secs)
            audio, _, _ = concat(rng, items, lead=0.5)
            name = f"{kind}-{i:02d}.wav"
            write(OUT / "langid" / name, audio)
            labels[name] = label
    (OUT / "langid" / "labels.json").write_text(json.dumps(labels, indent=1), encoding="utf-8")
    print(f"langid: {len(labels)} recordings")


if __name__ == "__main__":
    main()
