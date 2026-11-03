# Speech-to-text benchmark (Phase 0), first results

Run on 3 November 2026 on the **dev PC** (Intel Core i7-9850H, 6 cores / 12 threads, plugged in), with faster-whisper 1.2.1, int8 on the CPU, on public sample recordings from `bench/fetch_samples.py`: read sentences from Google's FLEURS (CC BY 4.0) in Brazilian Portuguese and US English, about 9 minutes in all, with exact transcripts. Speeds will differ on the company laptop (Core Ultra 7 268V), and real meetings (conversational, European Portuguese, several voices) will be harder, so the choice is confirmed there.

## Word error rate per recording

`auto` detects one language per 30-second window. `utterance` splits at pauses, detects each piece's language (between Portuguese and English) with the tiny model, merges neighbouring pieces in the same language into windows of up to 28 seconds, and transcribes each window in its language.

| Model | Mode | Speed (× real time) | Peak memory | Portuguese | English | Mixed |
|---|---|---|---|---|---|---|
| tiny | auto | 12.7× | 510 MB | 27.5% | 18.7% | 65.3% |
| base | auto | 8.5× | 664 MB | 14.2% | 34.4% | 54.6% |
| small | auto | 3.7× | 1.4 GB | 8.5% | 22.4% | 50.7% |
| medium | auto | 1.8× | 3.1 GB | 5.1% | 13.6% | 55.5% |
| large-v3-turbo | auto | 1.7× | 3.3 GB | 5.8% | 7.6% | 51.5% |
| tiny | utterance | 6.9× | 427 MB | 46.1% | 26.3% | 26.6% |
| base | utterance | 5.2× | 740 MB | 16.6% | 28.4% | 22.3% |
| small | utterance | 3.1× | 1.1 GB | 12.5% | 23.6% | 17.2% |
| medium | utterance | 1.3× | 3.3 GB | 9.5% | 22.1% | 17.0% |
| large-v3-turbo | utterance | 1.4× | 3.3 GB | 7.8% | 15.4% | 16.2% |
| large-v3-turbo | utterance, self-detected | 0.5× | 3.3 GB | 6.4% | 15.4% | 16.2% |

## What it shows

1. **In one language, large-v3-turbo and medium are clearly best**: about 5–6% errors in Portuguese, and turbo 7.6% in English. Small is fine in Portuguese (8.5%) but weak in English. Tiny and base aren't good enough.
2. **When a meeting switches language within a 30-second window, every model fails in `auto` mode**: it loses about half the words, transcribing or translating everything in one language. Detecting the language per utterance cuts that to about 16–17%.
3. **Per-utterance detection has costs that need solving in Phase 3:**
   - the tiny detector labelled 3 of 11 Portuguese windows as English; letting the big model detect gets them right but runs slower than real time (0.5×);
   - whole sentences were sometimes skipped inside merged windows (turbo dropped two English sentences in `utterance` mode, one in `auto`).
   A hybrid (tiny detects, the big model rechecks only when tiny is unsure) and shorter merged windows are the next things to try, on real recordings.
4. **Speed**: on this CPU, turbo and medium run at 1.4–1.8× real time, so an hour's meeting takes 35–45 minutes of CPU. The brief runs transcription in the background, when the laptop is plugged in and idle, so that's workable; none reached the benchmark's 2× target.

## Compared with NVIDIA Parakeet TDT 0.6B v3

Parakeet is a different model family: multilingual across 25 European languages, trained on European Portuguese, detecting the language by itself, and run on ONNX Runtime through `onnx-asr` (int8). Run on the same recordings on 3 November 2026, with large-v3-turbo as the control, which reproduced its numbers exactly.

| Model | Speed (× real time) | Peak memory | Portuguese | English | Mixed |
|---|---|---|---|---|---|
| parakeet-tdt-0.6b-v3 (int8) | 11.1× | 2.2 GB | 12.9% | 14.5% | 26.4% |
| parakeet-tdt-0.6b-v3 (full precision) | 10.6× | 4.8 GB | 10.8% | 13.9% | 26.0% |
| large-v3-turbo, auto | 1.7× | 3.7 GB | 5.8% | 7.6% | 51.5% |
| large-v3-turbo, utterance | 1.4× | 3.3 GB | 7.8% | 15.4% | 16.2% |

- **6.5 times faster** than turbo, and lighter: an hour's meeting would take about 5 minutes on this CPU.
- **Roughly twice turbo's errors in one language.** Writing numbers as words ("setenta", "seventeen sixty seven") explains only a little: excluding those differences, Portuguese goes from 12.9% to 11.2%, mixed from 26.4% to 25.5%. The rest are real mistakes: names ("Javanese" as "Japanese"), and whole sentences garbled or dropped, mostly English ones in the mixed recording.
- **Quantisation isn't the reason:** the full-precision model is a little better (Portuguese 10.8%), as fast on this CPU, and twice the memory, but still about twice turbo's errors.
- **Mixed meetings:** about half turbo's `auto` errors, but worse than turbo with per-utterance detection.

The test favours Whisper in one way: the clips are Brazilian Portuguese read aloud, while Parakeet was trained on European Portuguese, which is what real meetings will be. Both stay in the benchmark for the laptop and real recordings.

## Choice

**Decided 3 November 2026: accuracy over speed, so large-v3-turbo** (int8, about 3.3 GB of RAM): the most accurate overall and as fast as medium. Accuracy matters more than speed here, because transcripts become decisions and action items with evidence, and transcription runs in the background anyway. Parakeet is the alternative if real European Portuguese meetings close the accuracy gap, or as a fast first pass. Use one-language transcription for meetings in a single language, and per-utterance detection where languages mix; recording me and the others on separate tracks (brief §9) also helps, since each track tends to stay in one language.

**To confirm on the laptop:** `python3 bench/fetch_samples.py`, then `python3 bench/whisper_benchmark.py ~/.local/share/pwi/benchmark/samples --models small,medium,large-v3-turbo,parakeet-tdt-0.6b-v3`, for its real speed; and later the same with 2 or 3 real meeting recordings, for real accuracy.

Pinned model: large-v3-turbo, revision `0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf`, `model.bin` sha256 `e76620f83d5f5b69efd3d87e3dc180c1bd21df9fbebacfd4335e5e1efcc018da`.

Parakeet, if chosen: revision `8f23f0c03c8761650bdb5b40aaf3e40d2c15f1ce` of `istupakov/parakeet-tdt-0.6b-v3-onnx`, `encoder-model.int8.onnx` sha256 `6139d2fa7e1b086097b277c7149725edbab89cc7c7ae64b23c741be4055aff09`.
