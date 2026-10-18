# English long-form benchmark

Full recordings, WER after Whisper's English normalizer, Apple M2. Non-Whisper models transcribe ≤30 s
chunks of Silero-VAD speech. `qwen3-asr-1.7b` uses the app's chunker (macos/qwen_asr.py, cut at the longest
pause); the other mlx models and `qwen3-asr-1.7b-greedy-chunks` were run with an earlier greedy chunker that
cut wherever 30 s was reached. *Wrong words* are substitutions; most deletions on TED are repeated words
("the the") that Whisper tidies away but the verbatim references keep.

## TED-LIUM 3: 11 full TED talks (148 min)

| Model | WER | Wrong words | Deletions | Insertions | Speed |
|---|---|---|---|---|---|
| qwen3-asr-1.7b-greedy-chunks | 2.06% | 0.93% | 0.72% | 0.41% | 4.9× |
| qwen3-asr-1.7b | 2.12% | 0.92% | 0.79% | 0.41% | 4.8× |
| whisper.cpp-turbo-pipeline | 3.04% | 0.87% | 1.82% | 0.36% | 10.2× |
| granite-5.0-turboctc | 3.16% | 1.18% | 1.60% | 0.37% | 51.2× |
| parakeet-tdt-0.6b-v2 | 3.18% | 0.99% | 1.81% | 0.38% | 29.7× |
| granite-4.1-2b | 3.73% | 1.05% | 2.26% | 0.41% | 3.4× |

## Earnings-21: full earnings calls (92 min)

| Model | WER | Wrong words | Deletions | Insertions | Speed |
|---|---|---|---|---|---|
| qwen3-asr-1.7b | 8.48% | 4.35% | 1.96% | 2.17% | 2.8× |
| qwen3-asr-1.7b-greedy-chunks | 8.49% | 4.36% | 1.91% | 2.22% | 4.1× |
| granite-5.0-turboctc | 9.19% | 4.73% | 2.34% | 2.11% | 77.4× |
| parakeet-tdt-0.6b-v2 | 9.57% | 4.52% | 2.56% | 2.50% | 44.6× |
| whisper.cpp-turbo-pipeline | 9.74% | 4.47% | 2.86% | 2.42% | 10.5× |
