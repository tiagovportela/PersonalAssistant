"""Downloads public sample recordings for the Whisper benchmark, when there are
no real meeting recordings yet. Standard library only.

    python3 bench/fetch_samples.py

It takes read sentences in Brazilian Portuguese and US English from Google's
FLEURS dataset (CC BY 4.0), each with its exact transcript, and builds three
test recordings with their references:

- portuguese.wav: about 2.5 minutes of Portuguese
- english.wav: about 2.5 minutes of English
- mixed.wav: about 4 minutes alternating Portuguese and English sentences,
  like a meeting that switches language

Only the start of each archive is downloaded (streamed until enough clips are
found), a few megabytes. The same clips come out every time, so results from
the dev PC and the laptop compare. They go to ~/.local/share/pwi/benchmark/samples.

Read sentences are easier than real meetings (no crosstalk, one clear speaker,
and Brazilian rather than European Portuguese), so they rank the models and
measure speed, but a real recording is still the better test of accuracy.
"""

import array
import os
import struct
import tarfile
import urllib.request
import wave
from pathlib import Path

BASE = "https://huggingface.co/datasets/google/fleurs/resolve/main/data"
OUT = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "pwi" / "benchmark" / "samples"
PURE_SECONDS = 150
MIXED_PER_LANGUAGE = 120
GAP = 0.8  # seconds of silence between sentences


def transcripts(language):
    """{file name: (sentence id, transcript)} from the dev split's TSV."""
    with urllib.request.urlopen(f"{BASE}/{language}/dev.tsv", timeout=60) as response:
        rows = response.read().decode("utf-8").splitlines()
    out = {}
    for row in rows:
        fields = row.split("\t")
        if len(fields) >= 3:
            out[fields[1]] = (fields[0], fields[2].strip())
    return out


def pcm16(data):
    """16 kHz mono 16-bit PCM from a WAV file that's 16-bit PCM or 32-bit float (FLEURS uses float); None otherwise."""
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        return None
    fmt, samples, pos = None, None, 12
    while pos + 8 <= len(data):
        chunk, size = data[pos:pos + 4], struct.unpack("<I", data[pos + 4:pos + 8])[0]
        body = data[pos + 8:pos + 8 + size]
        if chunk == b"fmt ":
            fmt = struct.unpack("<HHIIHH", body[:16])  # tag, channels, rate, byte rate, block align, bits
        elif chunk == b"data":
            samples = body
        pos += 8 + size + (size & 1)
    if not fmt or samples is None or fmt[1] != 1 or fmt[2] != 16000:
        return None
    if fmt[0] == 1 and fmt[5] == 16:
        return samples
    if fmt[0] == 3 and fmt[5] == 32:
        floats = array.array("f")
        floats.frombytes(samples[:len(samples) - len(samples) % 4])
        return array.array("h", (max(-32768, min(32767, int(x * 32767))) for x in floats)).tobytes()
    return None


def clips(language, seconds):
    """Streams the dev audio archive and keeps distinct sentences until there is enough audio."""
    texts = transcripts(language)
    found, seen, total = [], set(), 0.0
    with urllib.request.urlopen(f"{BASE}/{language}/audio/dev.tar.gz", timeout=60) as response:
        with tarfile.open(fileobj=response, mode="r|gz") as archive:
            for member in archive:
                name = Path(member.name).name
                if not member.isfile() or name not in texts or texts[name][0] in seen:
                    continue
                frames = pcm16(archive.extractfile(member).read())
                if frames is None:
                    continue
                seen.add(texts[name][0])
                found.append((frames, texts[name][1]))
                total += len(frames) / 32000
                if total >= seconds:
                    return found
    return found


def write(name, parts):
    silence = b"\x00\x00" * int(16000 * GAP)
    with wave.open(str(OUT / f"{name}.wav"), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(silence.join(frames for frames, _ in parts))
    (OUT / f"{name}.txt").write_text("\n".join(text for _, text in parts) + "\n", encoding="utf-8")
    seconds = sum(len(frames) for frames, _ in parts) / 32000 + GAP * (len(parts) - 1)
    print(f"  {name}.wav: {len(parts)} sentences, {seconds / 60:.1f} minutes")


def main():
    OUT.mkdir(mode=0o700, parents=True, exist_ok=True)
    print(f"Downloading sample sentences from FLEURS into {OUT}...")
    portuguese = clips("pt_br", PURE_SECONDS + MIXED_PER_LANGUAGE)
    english = clips("en_us", PURE_SECONDS + MIXED_PER_LANGUAGE)
    split = lambda parts: next(i for i in range(len(parts) + 1)  # noqa: E731
                               if sum(len(f) for f, _ in parts[:i]) / 32000 >= PURE_SECONDS)
    pt_cut, en_cut = split(portuguese), split(english)
    write("portuguese", portuguese[:pt_cut])
    write("english", english[:en_cut])
    rest_pt, rest_en = portuguese[pt_cut:], english[en_cut:]
    write("mixed", [part for pair in zip(rest_pt, rest_en) for part in pair])
    (OUT / "ATTRIBUTION.txt").write_text(
        "Sentences from FLEURS (Conneau et al., 2022), https://huggingface.co/datasets/google/fleurs, "
        "licensed CC BY 4.0. Concatenated with short silences between sentences.\n", encoding="utf-8")
    print(f"Done. Run: python3 bench/whisper_benchmark.py {OUT}")


if __name__ == "__main__":
    main()
