"""Phase 0 CPU benchmark: which speech-to-text model transcribes my meetings
well enough, fast enough, on this laptop (brief §9 and §15): Whisper sizes
through faster-whisper, and NVIDIA's Parakeet through onnx-asr.

    python3 bench/whisper_benchmark.py ~/Recordings/benchmark

The folder holds a few real recordings that mix Portuguese and English
(10 to 15 minutes in all is enough). For each recording, a hand-corrected
transcript with the same name and .txt next to it lets the benchmark measure
accuracy (word error rate); without one it measures speed and memory only.

The first run creates a separate Python environment in
~/.local/share/pwi/bench-venv and installs faster-whisper there from
bench/requirements.txt, every package checked against its pinned hash. The
service itself never uses it. Models download from Hugging Face on first use;
the report records each model's revision and checksum so the chosen one can be
pinned. Each model runs with the language detected once per recording (auto),
and per utterance between pauses (utterance), which handles meetings that switch
between Portuguese and English. Results and transcripts are work data, so they stay in
~/.local/share/pwi/benchmark, outside the repository.

Run it plugged in, with other heavy work closed.
"""

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import time
import unicodedata
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "pwi"
VENV = DATA / "bench-venv"
AUDIO = (".wav", ".mp3", ".m4a", ".ogg", ".opus", ".flac", ".webm", ".mp4", ".aac")
MODELS = ["tiny", "base", "small", "medium", "large-v3-turbo", "parakeet-tdt-0.6b-v3"]
# Not Whisper: NVIDIA Parakeet TDT on ONNX Runtime, through onnx-asr. It detects the language by itself, so it
# runs once per recording (mode "auto"), with Silero splitting the audio at pauses. Only the int8 files are
# downloaded (about 670 MB instead of 3 GB).
PARAKEET = {  # name: (onnx-asr model, Hugging Face repository, quantization)
    "parakeet-tdt-0.6b-v3": ("nemo-parakeet-tdt-0.6b-v3", "istupakov/parakeet-tdt-0.6b-v3-onnx", "int8"),
    "parakeet-tdt-0.6b-v3-fp32": ("nemo-parakeet-tdt-0.6b-v3", "istupakov/parakeet-tdt-0.6b-v3-onnx", None),
}
SILERO = "istupakov/silero-vad-onnx"
# auto: one language for the whole recording. utterance: split at pauses and detect each piece's language,
# for meetings that switch language. multilingual: Whisper's own detection per 30-second window.
# pt: Portuguese forced.
MODES = {"auto": {}, "utterance": {}, "multilingual": {"multilingual": True}, "pt": {"language": "pt"}}
# The model that detects each utterance's language. tiny is fast but labelled 3 of 11 Portuguese windows as
# English in the sample run; the tested model itself labels them right but runs at under 1x real time
# (docs/whisper_benchmark.md). --detector same uses the tested model.
DETECTOR = "tiny"
LANGUAGES = ("pt", "en")  # utterance mode chooses between these, so Portuguese isn't taken for Galician or Spanish
GOOD_ENOUGH = 0.02  # a model within 2 points of the best word error rate counts as as good
FAST_ENOUGH = 2.0  # at least twice as fast as real time: an hour's meeting in half an hour while idle
USABLE = 0.25  # above this word error rate, even the best model isn't worth suggesting


# Setup: a separate environment, installed from pinned hashes ------------------------------

def ensure_environment():
    """Re-runs this script inside the benchmark environment, creating it first if needed."""
    try:
        import faster_whisper  # noqa: F401
        return
    except ImportError:
        pass
    python = VENV / "bin" / "python"
    if not python.exists():
        print(f"Setting up the benchmark's environment in {VENV} (once; about 300 MB)...")
        made = subprocess.run([sys.executable, "-m", "venv", str(VENV)], capture_output=True, text=True)
        if made.returncode:
            sys.exit("Python's venv module is missing. Install it with: sudo apt install python3-venv\n"
                     "Then run this again.")
        installed = subprocess.run([str(python), "-m", "pip", "install", "--quiet", "--require-hashes",
                                    "--only-binary", ":all:", "-r", str(HERE / "requirements.txt")])
        if installed.returncode:
            subprocess.run(["rm", "-rf", str(VENV)])
            sys.exit("Installing faster-whisper failed (see above). Nothing was left behind; run this again.")
    os.execv(str(python), [str(python), *sys.argv])


# One model and mode, in its own process, so its memory is measured alone ------------------

def parakeet_worker(model_name, files, threads):
    import resource

    import onnx_asr
    import onnxruntime
    from faster_whisper import decode_audio
    from huggingface_hub import HfApi, snapshot_download

    name, repo, quantization = PARAKEET[model_name]
    weights = ["*.int8.onnx"] if quantization else ["encoder-model.onnx", "encoder-model.onnx.data", "decoder_joint-model.onnx"]
    # Into plain folders, not the Hugging Face cache: ONNX Runtime refuses weights kept in a separate .data file
    # when the cache's symlinks put it in another folder. Pinned to the revision current when downloading.
    revision = HfApi().model_info(repo).sha
    path = Path(snapshot_download(repo, revision=revision, local_dir=DATA / "models" / repo.split("/")[1],
                                  allow_patterns=["config.json", "vocab.txt", "nemo128.onnx", *weights]))
    vad_path = Path(snapshot_download(SILERO, local_dir=DATA / "models" / SILERO.split("/")[1],
                                      allow_patterns=["config.json", "silero_vad.onnx"]))
    options = onnxruntime.SessionOptions()
    options.intra_op_num_threads = threads
    started = time.perf_counter()
    model = onnx_asr.load_model(name, path, quantization=quantization, sess_options=options).with_vad(
        onnx_asr.load_vad("silero", vad_path, sess_options=options))
    load = time.perf_counter() - started
    weights = path / ("encoder-model.int8.onnx" if quantization else "encoder-model.onnx.data")
    out = {"model": model_name, "mode": "auto", "load_s": round(load, 2), "files": [], "revision": revision,
           "sha256": hashlib.sha256(weights.read_bytes()).hexdigest()}
    for file in files:
        audio = decode_audio(file)
        started = time.perf_counter()
        text = " ".join(segment.text.strip() for segment in model.recognize(audio))
        wall = time.perf_counter() - started
        out["files"].append({"file": Path(file).name, "duration_s": round(len(audio) / 16000, 1),
                             "wall_s": round(wall, 1), "language": "auto", "text": text})
    out["peak_mb"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024)
    print(json.dumps(out))


def worker(model_name, mode, files, threads, detector_name=DETECTOR):
    if model_name in PARAKEET:
        return parakeet_worker(model_name, files, threads)
    import resource

    from faster_whisper import WhisperModel, decode_audio
    from faster_whisper.utils import download_model

    path = Path(download_model(model_name))
    started = time.perf_counter()
    model = WhisperModel(str(path), device="cpu", compute_type="int8", cpu_threads=threads)
    load = time.perf_counter() - started
    detector = (model if detector_name in (None, "same", model_name) else
                WhisperModel(str(download_model(detector_name)), device="cpu", compute_type="int8", cpu_threads=threads)
                ) if mode == "utterance" else None
    weights = path / "model.bin"
    out = {"model": model_name, "mode": mode, "load_s": round(load, 2), "files": [],
           "revision": path.name, "sha256": hashlib.sha256(weights.read_bytes()).hexdigest() if weights.exists() else None}
    for file in files:
        audio = decode_audio(file)
        duration = len(audio) / 16000
        started = time.perf_counter()
        if mode == "utterance":
            text, language = by_utterance(model, audio, detector)
        else:
            segments, info = model.transcribe(file, vad_filter=True, beam_size=5, **MODES[mode])
            text = " ".join(s.text.strip() for s in segments)  # transcription happens while iterating
            language = info.language
        wall = time.perf_counter() - started
        out["files"].append({"file": Path(file).name, "duration_s": round(duration, 1), "wall_s": round(wall, 1),
                             "language": language, "text": text})
    out["peak_mb"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024)
    print(json.dumps(out))


def by_utterance(model, audio, detector):
    """For meetings that switch language: split at pauses, detect each piece's language among LANGUAGES with the
    small `detector` model, merge neighbouring pieces in the same language into windows of up to 28 s, and
    transcribe each window in its language. Whisper pads every input to 30 s, so transcribing piece by piece
    would cost a full pass each. Returns the text and the windows per language, e.g. "en:9,pt:13"."""
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    pieces = get_speech_timestamps(audio, VadOptions(min_silence_duration_ms=400, speech_pad_ms=200,
                                                     max_speech_duration_s=28))
    windows = []  # [language, start, end] in samples
    for piece in pieces:
        start, end = piece["start"], piece["end"]
        if end - start < 1.5 * 16000 and windows:
            language = windows[-1][0]  # too short to tell; most likely the same speaker going on
        else:
            _, _, scores = detector.detect_language(audio[start:end])
            language = max((s for s in scores if s[0] in LANGUAGES), key=lambda s: s[1])[0]
        if windows and windows[-1][0] == language and end - windows[-1][1] <= 28 * 16000:
            windows[-1][2] = end
        else:
            windows.append([language, start, end])
    texts, used = [], {}
    for language, start, end in windows:
        used[language] = used.get(language, 0) + 1
        segments, _ = model.transcribe(audio[start:end], language=language, beam_size=5,
                                       condition_on_previous_text=False)
        texts.append(" ".join(s.text.strip() for s in segments))
    return " ".join(t for t in texts if t), ",".join(f"{k}:{v}" for k, v in sorted(used.items()))


# Accuracy ---------------------------------------------------------------------------------

def words(text, fold=False):
    text = text.lower()
    if fold:
        text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    return re.findall(r"\w+", text)


def wer(reference, hypothesis):
    """Word error rate: word edits needed to turn the transcript into the reference, per reference word."""
    ref, hyp = reference, hypothesis
    previous = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        current = [i]
        for j, h in enumerate(hyp, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (r != h)))
        previous = current
    return previous[-1] / max(len(ref), 1)


# The report -------------------------------------------------------------------------------

def machine():
    cpu = next((line.split(":", 1)[1].strip() for line in open("/proc/cpuinfo") if line.startswith("model name")), "?")
    memory = next((int(line.split()[1]) // 1024 for line in open("/proc/meminfo") if line.startswith("MemTotal")), 0)
    power = [p for p in Path("/sys/class/power_supply").glob("*/online")] if Path("/sys/class/power_supply").exists() else []
    plugged = any(p.read_text().strip() == "1" for p in power) if power else None
    return {"cpu": cpu, "cores": os.cpu_count(), "memory_mb": memory, "plugged_in": plugged,
            "python": platform.python_version()}


def report(results, refs, info, threads):
    lines = [f"# Whisper benchmark, {datetime.now():%Y-%m-%d %H:%M}", "",
             f"{info['cpu']}, {info['cores']} cores, {info['memory_mb'] // 1024} GB RAM, {threads} threads, "
             f"Python {info['python']}, {'plugged in' if info['plugged_in'] else 'ON BATTERY: results will be slower'}"
             if info['plugged_in'] is not None else f"{info['cpu']}, {info['cores']} cores", "",
             "| Model | Language | Speed (× real time) | Load | Peak memory | Word error rate | Without accents |",
             "|---|---|---|---|---|---|---|"]
    rows = []
    for r in results:
        audio = sum(f["duration_s"] for f in r["files"])
        wall = sum(f["wall_s"] for f in r["files"])
        scored = [(refs[f["file"]], f["text"]) for f in r["files"] if f["file"] in refs]
        strict = folded = None
        if scored:
            total = sum(len(words(ref)) for ref, _ in scored)
            strict = sum(wer(words(ref), words(hyp)) * len(words(ref)) for ref, hyp in scored) / total
            folded = sum(wer(words(ref, True), words(hyp, True)) * len(words(ref)) for ref, hyp in scored) / total
        speed = audio / wall if wall else 0
        rows.append({**r, "speed": speed, "wer": strict})
        lines.append(f"| {r['model']} | {r['mode']} | {speed:.1f}× | {r['load_s']:.0f} s | {r['peak_mb']:,} MB | "
                     f"{'n/a' if strict is None else f'{strict:.1%}'} | {'n/a' if folded is None else f'{folded:.1%}'} |")
    lines.append("")
    files = sorted({f["file"] for r in results for f in r["files"] if f["file"] in refs})
    if len(files) > 1:  # a recording that goes wrong stands out here, not in the totals
        lines += ["Word error rate per recording:", "",
                  "| Model | Language | " + " | ".join(Path(f).stem for f in files) + " |",
                  "|---|---|" + "---|" * len(files)]
        for r in results:
            by_file = {f["file"]: f["text"] for f in r["files"]}
            cells = [f"{wer(words(refs[f]), words(by_file[f])):.1%}" if f in by_file else "n/a" for f in files]
            lines.append(f"| {r['model']} | {r['mode']} | " + " | ".join(cells) + " |")
        lines.append("")
    scored = [r for r in rows if r["wer"] is not None]
    if scored:
        best = min(r["wer"] for r in scored)
        fit = [r for r in scored if r["wer"] <= best + GOOD_ENOUGH and r["speed"] >= FAST_ENOUGH]
        if best > USABLE:
            lines += [f"Even the best run misses {best:.0%} of the words, so nothing is suggested. Check that each "
                      ".txt really transcribes its recording, and that the recordings are clear enough.", ""]
        elif fit:
            pick = max(fit, key=lambda r: r["speed"])
            lines += [f"**Suggested: {pick['model']}, language mode {pick['mode']}.** It's the fastest model within "
                      f"{GOOD_ENOUGH:.0%} of the best word error rate ({best:.1%}) that runs at least "
                      f"{FAST_ENOUGH:.0f}× real time: {pick['speed']:.1f}×, {pick['wer']:.1%} errors, "
                      f"{pick['peak_mb']:,} MB.", ""]
        else:
            lines += [f"No model is both within {GOOD_ENOUGH:.0%} of the best word error rate and {FAST_ENOUGH:.0f}× "
                      "faster than real time. Compare the transcripts, and consider running transcription only "
                      "overnight, or a smaller model with corrections.", ""]
    else:
        lines += ["No reference transcripts, so accuracy wasn't measured. Read the transcripts in this folder and "
                  "judge them, or add a hand-corrected .txt for each recording and run again.", ""]
    lines += ["To pin the chosen model, keep its revision and checksum:", ""]
    for r in {r["model"]: r for r in results}.values():
        weights = (("encoder-model.int8.onnx" if PARAKEET[r["model"]][2] else "encoder-model.onnx.data")
                   if r["model"] in PARAKEET else "model.bin")
        lines.append(f"- {r['model']}: revision `{r['revision']}`, {weights} sha256 `{r['sha256']}`")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description="Choose the Whisper model for meetings on this laptop.")
    parser.add_argument("folder", nargs="?", help="recordings, each with an optional hand-corrected .txt of the same name")
    parser.add_argument("--models", default=",".join(MODELS), help=f"default: {','.join(MODELS)}")
    parser.add_argument("--modes", default="auto,utterance",
                        help="auto, utterance, multilingual and/or pt (default: auto,utterance)")
    parser.add_argument("--threads", type=int, default=os.cpu_count(), help="CPU threads (default: all)")
    parser.add_argument("--detector", default=DETECTOR,
                        help="model that detects each utterance's language: tiny (default, fast) or same (the tested model)")
    parser.add_argument("--worker", nargs=2, help=argparse.SUPPRESS)
    args = parser.parse_args()

    ensure_environment()
    files = sorted(str(p) for p in Path(args.folder).expanduser().iterdir() if p.suffix.lower() in AUDIO) if args.folder else []
    if args.worker:
        return worker(*args.worker, files, args.threads, args.detector)
    if not files:
        sys.exit("Give a folder of recordings: python3 bench/whisper_benchmark.py ~/Recordings/benchmark")
    modes = [m for m in args.modes.split(",") if m in MODES]
    refs = {Path(f).name: Path(f).with_suffix(".txt").read_text(encoding="utf-8")
            for f in files if Path(f).with_suffix(".txt").exists()}
    out = DATA / "benchmark" / datetime.now().strftime("%Y-%m-%d-%H%M")
    out.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = machine()
    print(f"{len(files)} recordings, {len(refs)} with a reference transcript. Results go to {out}")
    if info["plugged_in"] is False:
        print("The laptop is on battery: plug it in for results that match how transcription will run.")
    results = []
    for model in args.models.split(","):
        for mode in (["auto"] if model in PARAKEET else modes):
            print(f"- {model}, {mode}...", end=" ", flush=True)
            run = subprocess.run([sys.executable, __file__, args.folder, "--threads", str(args.threads),
                                  *(["--detector", args.detector] if args.detector else []),
                                  "--worker", model, mode], capture_output=True, text=True)
            if run.returncode:
                print("failed:", (run.stderr.strip().splitlines() or ["?"])[-1])
                continue
            result = json.loads(run.stdout.strip().splitlines()[-1])
            audio, wall = sum(f["duration_s"] for f in result["files"]), sum(f["wall_s"] for f in result["files"])
            print(f"{audio / wall:.1f}× real time, {result['peak_mb']:,} MB")
            results.append(result)
            for f in result["files"]:
                (out / f"{Path(f['file']).stem}.{model}.{mode}.txt").write_text(f["text"] + "\n", encoding="utf-8")
    if not results:
        sys.exit("Every run failed; see the errors above.")
    (out / "results.json").write_text(json.dumps({"machine": info, "threads": args.threads, "results": results},
                                                 indent=2, ensure_ascii=False), encoding="utf-8")
    text = report(results, refs, info, args.threads)
    (out / "report.md").write_text(text, encoding="utf-8")
    print()
    print(text)
    print(f"Transcripts of every run, to compare by eye: {out}")


if __name__ == "__main__":
    main()
