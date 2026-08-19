#!/usr/bin/env python3
"""Render a short singing demo from a generated PJS browser voicebank.

This is intentionally dependency-free so it can run in GitHub Actions. It uses
simple resampling for pitch, vowel-nucleus looping for duration, and short
crossfades between mora clips.
"""

from __future__ import annotations

import argparse
import json
import math
import wave
from array import array
from pathlib import Path

SMALL_KANA = set("ゃゅょぁぃぅぇぉャュョァィゥェォ")
MORA_TO_PHONES = {
    "あ": ["a"], "い": ["i"], "う": ["u"], "え": ["e"], "お": ["o"],
    "か": ["k", "a"], "き": ["k", "i"], "く": ["k", "u"], "け": ["k", "e"], "こ": ["k", "o"],
    "が": ["g", "a"], "ぎ": ["g", "i"], "ぐ": ["g", "u"], "げ": ["g", "e"], "ご": ["g", "o"],
    "さ": ["s", "a"], "し": ["sh", "i"], "す": ["s", "u"], "せ": ["s", "e"], "そ": ["s", "o"],
    "ざ": ["z", "a"], "じ": ["j", "i"], "ず": ["z", "u"], "ぜ": ["z", "e"], "ぞ": ["z", "o"],
    "た": ["t", "a"], "ち": ["ch", "i"], "つ": ["ts", "u"], "て": ["t", "e"], "と": ["t", "o"],
    "だ": ["d", "a"], "ぢ": ["j", "i"], "づ": ["z", "u"], "で": ["d", "e"], "ど": ["d", "o"],
    "な": ["n", "a"], "に": ["n", "i"], "ぬ": ["n", "u"], "ね": ["n", "e"], "の": ["n", "o"],
    "は": ["h", "a"], "ひ": ["h", "i"], "ふ": ["f", "u"], "へ": ["h", "e"], "ほ": ["h", "o"],
    "ば": ["b", "a"], "び": ["b", "i"], "ぶ": ["b", "u"], "べ": ["b", "e"], "ぼ": ["b", "o"],
    "ぱ": ["p", "a"], "ぴ": ["p", "i"], "ぷ": ["p", "u"], "ぺ": ["p", "e"], "ぽ": ["p", "o"],
    "ま": ["m", "a"], "み": ["m", "i"], "む": ["m", "u"], "め": ["m", "e"], "も": ["m", "o"],
    "や": ["y", "a"], "ゆ": ["y", "u"], "よ": ["y", "o"],
    "ら": ["r", "a"], "り": ["r", "i"], "る": ["r", "u"], "れ": ["r", "e"], "ろ": ["r", "o"],
    "わ": ["w", "a"], "を": ["o"], "ん": ["N"], "っ": ["cl"],
    "きゃ": ["ky", "a"], "きゅ": ["ky", "u"], "きょ": ["ky", "o"],
    "しゃ": ["sh", "a"], "しゅ": ["sh", "u"], "しょ": ["sh", "o"],
    "ちゃ": ["ch", "a"], "ちゅ": ["ch", "u"], "ちょ": ["ch", "o"],
    "にゃ": ["ny", "a"], "にゅ": ["ny", "u"], "にょ": ["ny", "o"],
    "りゃ": ["ry", "a"], "りゅ": ["ry", "u"], "りょ": ["ry", "o"],
}
MELODY = [60, 62, 64, 67, 69, 67, 64, 62, 60, 64, 67, 69, 67, 64, 62, 60]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bank", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--phrase", default="きみを きりたおした")
    parser.add_argument("--bpm", type=float, default=112.0)
    return parser.parse_args()


def to_hiragana(text: str) -> str:
    chars: list[str] = []
    for char in text:
        code = ord(char)
        chars.append(chr(code - 0x60) if 0x30A1 <= code <= 0x30F6 else char)
    return "".join(chars)


def tokenize(text: str) -> list[str]:
    ignored = set(" \t\r\n、。,.!！?？「」『』（）()・…ー")
    moras: list[str] = []
    for char in to_hiragana(text):
        if char in ignored:
            continue
        if char in SMALL_KANA and moras:
            moras[-1] += char
        else:
            moras.append(char)
    return moras


def midi_hz(midi: int) -> float:
    return 440.0 * math.pow(2.0, (midi - 69) / 12.0)


def read_mono_wav(path: Path) -> tuple[int, list[float]]:
    with wave.open(str(path), "rb") as wav:
        channels = wav.getnchannels()
        width = wav.getsampwidth()
        rate = wav.getframerate()
        raw = wav.readframes(wav.getnframes())
    if width != 2:
        raise ValueError(f"Expected 16-bit WAV: {path}")
    pcm = array("h")
    pcm.frombytes(raw)
    if channels == 1:
        return rate, [sample / 32768.0 for sample in pcm]
    mono: list[float] = []
    for index in range(0, len(pcm), channels):
        frame = pcm[index:index + channels]
        mono.append(sum(frame) / (32768.0 * channels))
    return rate, mono


def linear_resample(samples: list[float], playback_rate: float) -> list[float]:
    playback_rate = max(0.25, min(4.0, playback_rate))
    output_length = max(1, int(len(samples) / playback_rate))
    output: list[float] = []
    for index in range(output_length):
        position = index * playback_rate
        left = int(position)
        if left >= len(samples) - 1:
            output.append(samples[-1])
            continue
        fraction = position - left
        output.append(samples[left] * (1.0 - fraction) + samples[left + 1] * fraction)
    return output


def apply_fades(samples: list[float], rate: int, seconds: float = 0.014) -> None:
    length = min(len(samples) // 2, max(1, int(rate * seconds)))
    for index in range(length):
        gain = index / length
        samples[index] *= gain
        samples[-1 - index] *= gain


def fit_unit(samples: list[float], rate: int, unit: dict, midi: int, duration: float) -> list[float]:
    source_f0 = max(70.0, float(unit.get("source_f0_hz", 220.0)))
    factor = midi_hz(midi) / source_f0
    shifted = linear_resample(samples, factor)
    target_length = max(1, int(duration * rate))
    if len(shifted) >= target_length:
        result = shifted[:target_length]
        apply_fades(result, rate)
        return result

    loop_start = int(float(unit.get("loop_start", 0.04)) * rate / factor)
    loop_end = int(float(unit.get("loop_end", 0.12)) * rate / factor)
    loop_start = max(0, min(loop_start, len(shifted) - 1))
    loop_end = max(loop_start + 1, min(loop_end, len(shifted)))
    prefix = shifted[:loop_start]
    loop = shifted[loop_start:loop_end]
    suffix = shifted[loop_end:]
    if len(loop) < 8:
        loop = shifted[max(0, len(shifted) // 3):max(1, len(shifted) * 2 // 3)] or shifted

    result = list(prefix)
    suffix_space = min(len(suffix), max(0, int(rate * 0.055)))
    body_target = max(len(result), target_length - suffix_space)
    while len(result) < body_target:
        take = min(len(loop), body_target - len(result))
        result.extend(loop[:take])
    if len(result) < target_length and suffix:
        result.extend(suffix[-min(len(suffix), target_length - len(result)):])
    if len(result) < target_length:
        result.extend([0.0] * (target_length - len(result)))
    result = result[:target_length]
    apply_fades(result, rate)
    return result


def append_crossfade(output: list[float], segment: list[float], rate: int, seconds: float = 0.018) -> None:
    if not output:
        output.extend(segment)
        return
    overlap = min(len(output), len(segment), max(1, int(rate * seconds)))
    base = len(output) - overlap
    for index in range(overlap):
        ratio = index / overlap
        output[base + index] = output[base + index] * (1.0 - ratio) + segment[index] * ratio
    output.extend(segment[overlap:])


def write_wav(path: Path, rate: int, samples: list[float]) -> None:
    peak = max((abs(value) for value in samples), default=1.0)
    gain = min(0.92 / peak, 1.4) if peak > 0 else 1.0
    pcm = array("h", (int(max(-1.0, min(1.0, value * gain)) * 32767) for value in samples))
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(pcm.tobytes())


def main() -> None:
    args = parse_args()
    bank = args.bank.resolve()
    with (bank / "manifest.json").open("r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    units: dict[str, dict] = manifest["units"]
    moras = tokenize(args.phrase)
    seconds_per_beat = 60.0 / args.bpm
    output: list[float] = []
    rate: int | None = None
    cache: dict[str, tuple[int, list[float]]] = {}
    used: list[str] = []

    for index, mora in enumerate(moras):
        duration_beats = 1.0 if index % 4 == 3 or index == len(moras) - 1 else 0.62
        duration = duration_beats * seconds_per_beat
        phones = MORA_TO_PHONES.get(mora, ["a"])
        key = "+".join(phones)
        fallback = phones[-1]
        unit = units.get(key) or units.get(fallback) or units.get("a")
        if mora == "っ" or unit is None:
            silence_rate = rate or 48000
            append_crossfade(output, [0.0] * int(duration * silence_rate), silence_rate, 0.004)
            rate = silence_rate
            used.append(f"{mora}:silence")
            continue

        filename = unit["file"]
        if filename not in cache:
            cache[filename] = read_mono_wav(bank / filename)
        unit_rate, samples = cache[filename]
        if rate is None:
            rate = unit_rate
        if unit_rate != rate:
            raise ValueError("All voicebank clips must share a sample rate")
        segment = fit_unit(samples, rate, unit, MELODY[index % len(MELODY)], duration)
        append_crossfade(output, segment, rate)
        used.append(f"{mora}:{key if key in units else fallback}")

    if rate is None:
        raise RuntimeError("No renderable units found")
    tail = [0.0] * int(rate * 0.16)
    output.extend(tail)
    write_wav(args.out.resolve(), rate, output)
    print(f"Rendered {args.out} ({len(output) / rate:.2f}s)")
    print("Units:", ", ".join(used))


if __name__ == "__main__":
    main()
