#!/usr/bin/env python3
"""Build a compact browser voicebank from the PJS singing corpus.

The builder uses PJS singing WAV files and the human-corrected HTK labels from
UtaUtaUtau/pjs-manual-labels. It chooses one long, stable occurrence for each
Japanese CV phoneme unit and writes short WAV clips plus a browser manifest.

PJS and the manual labels are CC BY-SA 4.0. Generated clips remain derivative
material and are emitted with matching attribution metadata.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import statistics
import wave
from array import array
from dataclasses import dataclass
from pathlib import Path

HTK_UNITS_PER_SECOND = 10_000_000
VOWELS = {"a", "i", "u", "e", "o"}
SPECIAL = {"N", "cl"}
SILENCE = {"pau", "sil", "sp"}


@dataclass
class Label:
    start: float
    end: float
    phone: str

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass
class Candidate:
    key: str
    corpus_id: int
    wav_path: Path
    segment_start: float
    segment_end: float
    voiced_start: float
    voiced_end: float
    score: float
    phones: list[str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--max-units", type=int, default=160)
    return parser.parse_args()


def read_labels(path: Path) -> list[Label]:
    labels: list[Label] = []
    with path.open("r", encoding="utf-8") as handle:
        for raw in handle:
            parts = raw.strip().split()
            if len(parts) < 3:
                continue
            start, end, phone = parts[:3]
            labels.append(
                Label(
                    int(start) / HTK_UNITS_PER_SECOND,
                    int(end) / HTK_UNITS_PER_SECOND,
                    phone,
                )
            )
    return labels


def corpus_id_from_label(path: Path) -> int | None:
    match = re.search(r"pjs(\d{3})", path.stem, re.I)
    return int(match.group(1)) if match else None


def build_wav_index(root: Path) -> dict[int, Path]:
    index: dict[int, Path] = {}
    wavs = list(root.rglob("*.wav"))
    for wav_path in wavs:
        lower = wav_path.name.lower()
        if "song" not in lower:
            continue
        text = str(wav_path).replace("\\", "/")
        matches = re.findall(r"(?<!\d)(\d{3})(?!\d)", text)
        if not matches:
            continue
        corpus_id = int(matches[-1])
        index.setdefault(corpus_id, wav_path)
    return index


def unit_candidates(labels: list[Label], corpus_id: int, wav_path: Path) -> list[Candidate]:
    candidates: list[Candidate] = []
    for idx, label in enumerate(labels):
        phone = label.phone
        if phone in SILENCE:
            continue

        # Standalone nasal and closure units.
        if phone in SPECIAL:
            if label.duration >= 0.035:
                candidates.append(
                    Candidate(
                        key=phone,
                        corpus_id=corpus_id,
                        wav_path=wav_path,
                        segment_start=max(0.0, label.start - 0.015),
                        segment_end=label.end + 0.015,
                        voiced_start=label.start,
                        voiced_end=label.end,
                        score=label.duration,
                        phones=[phone],
                    )
                )
            continue

        # Vowel-only unit.
        if phone in VOWELS:
            if label.duration >= 0.07:
                candidates.append(
                    Candidate(
                        key=phone,
                        corpus_id=corpus_id,
                        wav_path=wav_path,
                        segment_start=max(0.0, label.start - 0.018),
                        segment_end=label.end + 0.018,
                        voiced_start=label.start,
                        voiced_end=label.end,
                        score=label.duration,
                        phones=[phone],
                    )
                )
            continue

        # CV unit: consonant immediately followed by a vowel.
        if idx + 1 >= len(labels):
            continue
        nxt = labels[idx + 1]
        if nxt.phone not in VOWELS:
            continue
        if label.duration < 0.015 or nxt.duration < 0.07:
            continue
        key = f"{phone}+{nxt.phone}"
        # Prefer longer vowel nuclei while avoiding excessively long phrases.
        score = nxt.duration + min(label.duration, 0.16) * 0.25
        candidates.append(
            Candidate(
                key=key,
                corpus_id=corpus_id,
                wav_path=wav_path,
                segment_start=max(0.0, label.start - 0.018),
                segment_end=nxt.end + 0.020,
                voiced_start=nxt.start,
                voiced_end=nxt.end,
                score=score,
                phones=[phone, nxt.phone],
            )
        )
    return candidates


def read_wave_mono(path: Path) -> tuple[int, int, list[float]]:
    with wave.open(str(path), "rb") as wav:
        channels = wav.getnchannels()
        sample_width = wav.getsampwidth()
        rate = wav.getframerate()
        frames = wav.readframes(wav.getnframes())

    if sample_width != 2:
        raise ValueError(f"Unsupported sample width {sample_width} for {path}")

    pcm = array("h")
    pcm.frombytes(frames)
    if channels == 1:
        values = [sample / 32768.0 for sample in pcm]
    else:
        values = []
        for i in range(0, len(pcm), channels):
            frame = pcm[i : i + channels]
            values.append(sum(frame) / (32768.0 * channels))
    return rate, channels, values


def estimate_f0(samples: list[float], rate: int, start: float, end: float) -> float:
    # Analyse a stable middle window of the vowel nucleus.
    duration = max(0.0, end - start)
    if duration <= 0:
        return 220.0
    mid_start = start + duration * 0.32
    mid_end = start + duration * 0.78
    a = max(0, int(mid_start * rate))
    b = min(len(samples), int(mid_end * rate))
    segment = samples[a:b]
    if len(segment) < int(rate * 0.04):
        return 220.0

    # Downsample for cheap autocorrelation.
    step = max(1, rate // 12_000)
    data = segment[::step]
    ds_rate = rate / step
    mean = statistics.fmean(data)
    data = [x - mean for x in data]
    energy = sum(x * x for x in data)
    if energy < 1e-8:
        return 220.0

    min_lag = max(1, int(ds_rate / 520.0))
    max_lag = min(len(data) // 2, int(ds_rate / 70.0))
    best_lag = 0
    best_corr = -1.0
    for lag in range(min_lag, max_lag + 1):
        left = data[:-lag]
        right = data[lag:]
        dot = sum(x * y for x, y in zip(left, right))
        denom_l = math.sqrt(sum(x * x for x in left))
        denom_r = math.sqrt(sum(y * y for y in right))
        corr = dot / (denom_l * denom_r + 1e-12)
        if corr > best_corr:
            best_corr = corr
            best_lag = lag
    if best_lag <= 0 or best_corr < 0.18:
        return 220.0
    f0 = ds_rate / best_lag
    return float(min(520.0, max(70.0, f0)))


def write_clip(candidate: Candidate, out_path: Path) -> dict:
    with wave.open(str(candidate.wav_path), "rb") as src:
        channels = src.getnchannels()
        sample_width = src.getsampwidth()
        rate = src.getframerate()
        compression = src.getcomptype()
        compression_name = src.getcompname()
        start_frame = max(0, int(candidate.segment_start * rate))
        end_frame = min(src.getnframes(), int(candidate.segment_end * rate))
        src.setpos(start_frame)
        frames = src.readframes(max(0, end_frame - start_frame))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out_path), "wb") as dst:
        dst.setparams((channels, sample_width, rate, 0, compression, compression_name))
        dst.writeframes(frames)

    mono_rate, _channels, mono = read_wave_mono(candidate.wav_path)
    f0 = estimate_f0(mono, mono_rate, candidate.voiced_start, candidate.voiced_end)
    voiced_start_local = max(0.0, candidate.voiced_start - candidate.segment_start)
    voiced_end_local = max(voiced_start_local + 0.02, candidate.voiced_end - candidate.segment_start)
    nucleus = max(0.02, voiced_end_local - voiced_start_local)
    loop_start = voiced_start_local + nucleus * 0.38
    loop_end = voiced_start_local + nucleus * 0.78
    if loop_end - loop_start < 0.035:
        loop_start = voiced_start_local + nucleus * 0.25
        loop_end = voiced_start_local + nucleus * 0.85

    return {
        "file": out_path.name,
        "phones": candidate.phones,
        "source_id": candidate.corpus_id,
        "source_f0_hz": round(f0, 3),
        "clip_duration": round(candidate.segment_end - candidate.segment_start, 5),
        "voiced_start": round(voiced_start_local, 5),
        "voiced_end": round(voiced_end_local, 5),
        "loop_start": round(loop_start, 5),
        "loop_end": round(loop_end, 5),
    }


def safe_filename(key: str) -> str:
    return key.replace("+", "_").replace("/", "_") + ".wav"


def main() -> None:
    args = parse_args()
    corpus_root = args.corpus.resolve()
    labels_root = args.labels.resolve()
    out_root = args.out.resolve()

    wav_index = build_wav_index(corpus_root)
    if not wav_index:
        raise RuntimeError(f"No singing WAV files found under {corpus_root}")

    best: dict[str, Candidate] = {}
    for label_path in sorted(labels_root.glob("pjs*.lab")):
        corpus_id = corpus_id_from_label(label_path)
        if corpus_id is None or corpus_id not in wav_index:
            continue
        labels = read_labels(label_path)
        for candidate in unit_candidates(labels, corpus_id, wav_index[corpus_id]):
            previous = best.get(candidate.key)
            if previous is None or candidate.score > previous.score:
                best[candidate.key] = candidate

    # Keep all discovered Japanese units unless a safety cap is requested.
    selected = sorted(best.items(), key=lambda item: item[0])[: args.max_units]
    if not selected:
        raise RuntimeError("No usable phoneme units found")

    if out_root.exists():
        shutil.rmtree(out_root)
    out_root.mkdir(parents=True, exist_ok=True)

    units: dict[str, dict] = {}
    for key, candidate in selected:
        filename = safe_filename(key)
        units[key] = write_clip(candidate, out_root / filename)

    manifest = {
        "format": "songsmith-realvoice-v1",
        "name": "PJS RealVoice Prototype",
        "sample_base": "./voicebank/pjs/",
        "license": "CC BY-SA 4.0",
        "source": {
            "title": "PJS: Phoneme-balanced Japanese Singing-voice corpus",
            "authors": ["Junya Koguchi", "Shinnosuke Takamichi"],
            "project_url": "https://sites.google.com/site/shinnosuketakamichi/research-topics/pjs_corpus",
            "manual_labels": "https://github.com/UtaUtaUtau/pjs-manual-labels",
        },
        "unit_count": len(units),
        "units": units,
    }
    with (out_root / "manifest.json").open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)

    attribution = """PJS RealVoice Prototype voicebank\n\nDerived from:\nPJS: Phoneme-balanced Japanese Singing-voice corpus\nJunya Koguchi and Shinnosuke Takamichi\nhttps://sites.google.com/site/shinnosuketakamichi/research-topics/pjs_corpus\n\nManual labels:\nUtaUtaUtau/pjs-manual-labels\nhttps://github.com/UtaUtaUtau/pjs-manual-labels\n\nOriginal corpus and manual labels are licensed under CC BY-SA 4.0.\nThis derivative voicebank is distributed under CC BY-SA 4.0.\nhttps://creativecommons.org/licenses/by-sa/4.0/\n"""
    (out_root / "ATTRIBUTION.txt").write_text(attribution, encoding="utf-8")

    print(f"Built {len(units)} voice units at {out_root}")
    print("Keys:", ", ".join(units.keys()))


if __name__ == "__main__":
    main()
