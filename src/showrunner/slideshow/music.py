# SPDX-License-Identifier: AGPL-3.0-or-later
"""Looking at a piece of music for slideshows: is it music at all, where its sound starts and
ends, how loud it is, its tempo, beats and bars, its louder and quieter parts, its key and the
mood that follows from them.

No model is needed (D-099): the beats are found the classic way — an envelope of the attacks,
the tempo by its autocorrelation, the beats by dynamic programming (Ellis, 2007), the first beat
of the bar by where the low notes fall. Loudness is measured by the ebur128 filter of FFmpeg
(EBU R128, through PyAV). Blocking: run it in the worker."""

from __future__ import annotations

import itertools
import math
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import av
import av.filter
import numpy as np

ANALYSIS_VERSION = 1
"""Raised when music is looked at differently, so kept analyses are made again."""
MIN_SECONDS, MAX_SECONDS = 30.0, 15 * 60.0
MAX_BYTES = 50 * 1024 * 1024
RATE = 22050
FFT, HOP = 1024, 441
FPS = RATE / HOP  # 50 frames a second
SILENCE_DB = -45.0
TEMPO_RANGE = (60.0, 180.0)
TEMPO_PRIOR = 110.0
"""Tempos near this are preferred when the music could be read at half or twice the speed."""
TIGHTNESS = 100.0
SECTION_MIN_SECONDS = 12.0

MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
"""Krumhansl-Kessler key profiles."""
KEYS = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


class MusicError(ValueError):
    """The file is not music the app can use, with the reason."""


@dataclass(frozen=True)
class MusicAnalysis:
    seconds: float
    """The whole length of the file."""
    start: float
    end: float
    """Where the sound starts and ends (silence at either end left out)."""
    loudness: float
    """Integrated loudness, LUFS."""
    true_peak: float
    """dBTP."""
    tempo: float
    beats: tuple[float, ...]
    downbeats: tuple[float, ...]
    meter: int
    """Beats in a bar: 3 or 4."""
    sections: tuple[float, ...]
    """Where a new part begins (on a first beat of a bar), the start not included."""
    energy: tuple[float, ...]
    """Loudness of each second, dB below full scale."""
    key: str
    mode: str
    """"major" or "minor"."""
    mood: str
    """"calm", "bright", "upbeat" or "solemn"."""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        for name in ("beats", "downbeats", "sections"):
            data[name] = [round(v, 3) for v in data[name]]
        data["energy"] = [round(v, 1) for v in data["energy"]]
        for name in ("seconds", "start", "end", "loudness", "true_peak", "tempo"):
            data[name] = round(data[name], 3)
        return {"v": ANALYSIS_VERSION, **data}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MusicAnalysis | None:
        if data.get("v") != ANALYSIS_VERSION:
            return None
        fields = {k: v for k, v in data.items() if k != "v"}
        for name in ("beats", "downbeats", "sections", "energy"):
            fields[name] = tuple(float(v) for v in fields[name])
        return cls(**fields)


def analyse(path: Path) -> MusicAnalysis:
    """Look at a piece of music. Raises MusicError."""
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise MusicError(f"it can not be read: {exc}") from exc
    if size > MAX_BYTES:
        raise MusicError(f"it is larger than {MAX_BYTES >> 20} MB")
    loudness, true_peak = measure_loudness(path)
    mono = decode(path, RATE, "mono")[0]
    seconds = len(mono) / RATE
    if seconds < MIN_SECONDS or seconds > MAX_SECONDS:
        raise MusicError(
            f"it lasts {seconds:.0f} s; music for slideshows lasts "
            f"{MIN_SECONDS:.0f} s to {MAX_SECONDS / 60:.0f} min"
        )
    start, end = sounding(mono)
    if end - start < MIN_SECONDS:
        raise MusicError("it is mostly silence")
    spectrum = magnitudes(mono)
    flux, low = onset_envelopes(spectrum)
    tempo = estimate_tempo(flux)
    beats = track_beats(flux, tempo)
    beats = beats[(beats >= start - 0.05) & (beats <= end)]
    meter, downbeats = find_downbeats(beats, low)
    energy = energy_per_second(mono)
    sections = find_sections(spectrum, downbeats, start, end)
    key, mode = estimate_key(spectrum)
    mean_energy = float(np.mean(energy[int(start) : max(int(start) + 1, int(end))]))
    return MusicAnalysis(
        seconds=seconds,
        start=start,
        end=end,
        loudness=loudness,
        true_peak=true_peak,
        tempo=tempo,
        beats=tuple(float(b) for b in beats),
        downbeats=tuple(float(b) for b in downbeats),
        meter=meter,
        sections=tuple(float(s) for s in sections),
        energy=tuple(float(e) for e in energy),
        key=key,
        mode=mode,
        mood=mood_of(tempo, mean_energy - loudness, mode),
    )


# --- reading ----------------------------------------------------------------------------------


def decode(path: Path, rate: int, layout: str) -> np.ndarray:
    """The sound of the file as float32, channels by samples. Raises MusicError."""
    chunks: list[np.ndarray] = []
    try:
        with av.open(str(path)) as file:
            _check_streams(file)
            resampler = av.AudioResampler(format="fltp", layout=layout, rate=rate)
            for frame in _frames(file, file.streams.audio[0]):
                for out in resampler.resample(frame):
                    chunks.append(out.to_ndarray())
            for out in resampler.resample(None):
                chunks.append(out.to_ndarray())
    except MusicError:
        raise
    except (av.error.FFmpegError, OSError, ValueError) as exc:
        raise MusicError(f"it can not be read as sound: {exc}") from exc
    if not chunks:
        raise MusicError("it has no sound")
    return np.concatenate(chunks, axis=1).astype(np.float32)


MAX_BAD_SHARE = 0.02
"""A piece with more damaged packets than this share is refused; fewer are skipped (a short
click at worst), as players do."""


def _frames(file: Any, stream: Any) -> Iterator[Any]:
    """The decoded frames of a stream, damaged packets left out."""
    good = bad = 0
    for packet in file.demux(stream):
        try:
            frames = packet.decode()
        except av.error.InvalidDataError:
            bad += 1
            continue
        good += 1
        yield from frames
    if bad and bad > MAX_BAD_SHARE * (good + bad):
        raise MusicError(f"it is damaged: {bad} of {good + bad} packets can not be read")


def _check_streams(file: Any) -> None:
    if not file.streams.audio:
        raise MusicError("it has no sound")
    for stream in file.streams.video:
        # The cover picture of an MP3 or an M4A is a video stream too, marked as attached.
        if not stream.disposition & av.stream.Disposition.attached_pic:
            raise MusicError("it is a video, not music")


def measure_loudness(path: Path) -> tuple[float, float]:
    """Integrated loudness (LUFS) and true peak (dBTP), by FFmpeg's ebur128 filter."""
    try:
        with av.open(str(path)) as file:
            _check_streams(file)
            stream = file.streams.audio[0]
            graph = av.filter.Graph()
            source = graph.add_abuffer(template=stream)
            meter = graph.add("ebur128", "metadata=1:peak=true")
            sink = graph.add("abuffersink")
            source.link_to(meter)
            meter.link_to(sink)
            graph.configure()
            last: Any = None
            for frame in _frames(file, stream):
                graph.push(frame)
                last = _drain(graph, last)
            graph.push(None)
            last = _drain(graph, last)
    except MusicError:
        raise
    except (av.error.FFmpegError, OSError, ValueError) as exc:
        raise MusicError(f"it can not be read as sound: {exc}") from exc
    if last is None:
        raise MusicError("it has no sound")
    metadata = last.metadata
    loudness = float(metadata.get("lavfi.r128.I", "-70"))
    peak = float(metadata.get("lavfi.r128.true_peak", "0"))
    return loudness, 20 * math.log10(max(peak, 1e-9))


def _drain(graph: Any, last: Any) -> Any:
    """The last frame that carries the measurements: a short frame at the very end does not."""
    while True:
        try:
            frame = graph.pull()
        except (av.error.BlockingIOError, av.error.EOFError, BlockingIOError, EOFError):
            return last
        if "lavfi.r128.I" in frame.metadata:
            last = frame


def sounding(mono: np.ndarray) -> tuple[float, float]:
    """Where the sound starts and ends: the first and last 50 ms louder than SILENCE_DB."""
    block = RATE // 20
    count = len(mono) // block
    if count == 0:
        return 0.0, len(mono) / RATE
    rms = np.sqrt(np.mean(mono[: count * block].reshape(count, block) ** 2, axis=1) + 1e-12)
    loud = np.flatnonzero(20 * np.log10(rms) > SILENCE_DB)
    if loud.size == 0:
        return 0.0, 0.0
    return loud[0] * block / RATE, (loud[-1] + 1) * block / RATE


def energy_per_second(mono: np.ndarray) -> np.ndarray:
    count = max(1, len(mono) // RATE)
    padded = np.zeros(count * RATE, np.float32)
    padded[: min(len(mono), count * RATE)] = mono[: count * RATE]
    rms = np.sqrt(np.mean(padded.reshape(count, RATE) ** 2, axis=1) + 1e-12)
    return 20 * np.log10(rms)


# --- beats ------------------------------------------------------------------------------------


def magnitudes(mono: np.ndarray) -> np.ndarray:
    """Short-time spectrum, frames by bins, 50 frames a second."""
    padded = np.pad(mono, FFT // 2, mode="reflect")
    window = (0.5 - 0.5 * np.cos(2 * np.pi * np.arange(FFT) / FFT)).astype(np.float32)
    frames = 1 + (len(padded) - FFT) // HOP
    out = np.empty((frames, FFT // 2 + 1), np.float32)
    step = 2048
    for first in range(0, frames, step):
        idx = np.arange(FFT)[None, :] + HOP * np.arange(first, min(frames, first + step))[:, None]
        out[first : first + len(idx)] = np.abs(np.fft.rfft(padded[idx] * window, axis=1))
    return out


def onset_envelopes(spectrum: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """How much new sound starts in each frame: over all bins, and in the low ones (bass,
    kick drum), which mark the first beat of a bar more often."""
    log = np.log1p(1000 * spectrum)
    rise = np.maximum(0.0, np.diff(log, axis=0, prepend=log[:1]))
    low_bins = max(2, int(200 / (RATE / FFT)))
    return _normalized(rise.sum(axis=1)), _normalized(rise[:, :low_bins].sum(axis=1))


def _normalized(envelope: np.ndarray) -> np.ndarray:
    # Minus a local mean, so that a loud passage does not count as many attacks.
    width = int(FPS)
    kernel = np.ones(width) / width
    local = np.convolve(envelope, kernel, mode="same")
    result = np.maximum(0.0, envelope - local)
    top = float(result.std()) or 1.0
    normalized: np.ndarray = result / top
    return normalized


def estimate_tempo(envelope: np.ndarray) -> float:
    """Beats a minute: the lag at which the envelope is most like itself, weighed towards
    TEMPO_PRIOR."""
    centred = envelope - envelope.mean()
    size = 1 << math.ceil(math.log2(len(centred) * 2))
    spectrum = np.fft.rfft(centred, size)
    auto = np.fft.irfft(spectrum * np.conj(spectrum))[: len(centred)]
    lags = np.arange(1, len(auto))
    bpm = 60 * FPS / lags
    useful = (bpm >= TEMPO_RANGE[0]) & (bpm <= TEMPO_RANGE[1])
    prior = np.exp(-0.5 * (np.log2(bpm / TEMPO_PRIOR) / 0.9) ** 2)
    score = np.where(useful, auto[1:] * prior, -np.inf)
    best = int(np.argmax(score))
    # Refine between neighbouring lags.
    lag = float(lags[best])
    if 0 < best < len(score) - 1 and np.isfinite(score[best - 1]) and np.isfinite(score[best + 1]):
        a, b, c = score[best - 1], score[best], score[best + 1]
        denominator = a - 2 * b + c
        if denominator != 0:
            lag += 0.5 * (a - c) / denominator
    return float(60 * FPS / lag)


def track_beats(envelope: np.ndarray, tempo: float) -> np.ndarray:
    """Beat times in seconds: the path through the attacks that keeps closest to the tempo."""
    period = 60 * FPS / tempo
    n = len(envelope)
    score = envelope.astype(np.float64).copy()
    back = np.full(n, -1, dtype=np.int64)
    window = np.arange(-round(2 * period), -round(period / 2) + 1)
    penalty = -TIGHTNESS * np.log(-window / period) ** 2
    for i in range(n):
        previous = i + window
        valid = previous >= 0
        if not valid.any():
            continue
        candidates = score[previous[valid]] + penalty[valid]
        best = int(np.argmax(candidates))
        if candidates[best] > 0:
            score[i] += candidates[best]
            back[i] = previous[valid][best]
    # The end of the path: the best score in the last beat.
    tail = max(0, n - round(period))
    beat = tail + int(np.argmax(score[tail:]))
    path = [beat]
    while back[path[-1]] >= 0:
        path.append(int(back[path[-1]]))
    return np.array(path[::-1], dtype=np.float64) / FPS


def find_downbeats(beats: np.ndarray, low: np.ndarray) -> tuple[int, np.ndarray]:
    """The meter (3 or 4) and the first beats of the bars: the phase where the low notes are
    strongest."""
    if len(beats) < 8:
        return 4, beats[:1]

    # The strongest low attack within two frames of each beat: the beat may be found a frame
    # before the bass, whose attack is slower.
    def near(at: float) -> float:
        i = round(at * FPS)
        return float(low[max(0, i - 2) : min(len(low), i + 3)].max(initial=0.0))

    strength = np.array([near(b) for b in beats])
    best: tuple[float, int, int] = (-np.inf, 4, 0)
    for meter in (4, 3):
        for phase in range(meter):
            on = strength[phase::meter].mean()
            off = np.delete(strength, np.arange(phase, len(strength), meter)).mean()
            contrast = float(on - off) * (1.0 if meter == 4 else 0.9)  # 4/4 is far more common
            if contrast > best[0]:
                best = (contrast, meter, phase)
    _, meter, phase = best
    return meter, beats[phase::meter]


def find_sections(
    spectrum: np.ndarray, downbeats: np.ndarray, start: float, end: float
) -> list[float]:
    """Where a new part begins: first beats of bars where the sound changes most (a novelty
    curve over a coarse spectrum, Foote's checkerboard kernel), at least SECTION_MIN_SECONDS
    apart."""
    if len(downbeats) < 8:
        return []
    bands = np.array_split(np.log1p(1000 * spectrum), 16, axis=1)
    coarse = np.stack([b.mean(axis=1) for b in bands], axis=1)
    per_bar = []
    edges = [round(d * FPS) for d in downbeats] + [len(coarse)]
    for a, b in itertools.pairwise(edges):
        per_bar.append(coarse[a : max(a + 1, b)].mean(axis=0))
    features = np.array(per_bar)
    features = features - features.mean(axis=0)
    norms = np.linalg.norm(features, axis=1, keepdims=True)
    features = features / np.maximum(norms, 1e-9)
    similar = features @ features.T
    half = 4  # bars on either side
    kernel = np.kron(np.array([[1, -1], [-1, 1]]), np.ones((half, half)))
    novelty = np.zeros(len(features))
    for i in range(half, len(features) - half):
        novelty[i] = float((similar[i - half : i + half, i - half : i + half] * kernel).sum())
    order = np.argsort(-novelty)
    chosen: list[float] = []
    threshold = novelty.mean() + novelty.std()
    for bar in order:
        if novelty[bar] <= threshold:
            break
        at = float(downbeats[bar])
        if at - start < SECTION_MIN_SECONDS or end - at < SECTION_MIN_SECONDS:
            continue
        if all(abs(at - c) >= SECTION_MIN_SECONDS for c in chosen):
            chosen.append(at)
    return sorted(chosen)


# --- key and mood -----------------------------------------------------------------------------


def estimate_key(spectrum: np.ndarray) -> tuple[str, str]:
    """The key, by matching the pitch classes heard against the Krumhansl-Kessler profiles."""
    freqs = np.fft.rfftfreq(FFT, 1 / RATE)
    # Above the drums: a kick sweeping through 50-150 Hz says nothing of the key.
    useful = (freqs >= 100) & (freqs <= 2000)
    pitch = np.round(12 * np.log2(freqs[useful] / 440.0) + 9).astype(int) % 12
    energy = spectrum[:, useful].sum(axis=0)
    chroma = np.bincount(pitch, weights=energy, minlength=12)
    best = (-np.inf, 0, "major")
    for tonic in range(12):
        for mode, profile in (("major", MAJOR), ("minor", MINOR)):
            r = float(np.corrcoef(chroma, np.roll(profile, tonic))[0, 1])
            if r > best[0]:
                best = (r, tonic, mode)
    return KEYS[best[1]], best[2]


def mood_of(tempo: float, dynamics: float, mode: str) -> str:
    """A plain rule: slow and quiet is calm, fast is upbeat, slow in minor is solemn, the rest
    bright. `dynamics` is how much louder than its loudness the music is on average (dB)."""
    if tempo >= 120 and dynamics > -6:
        return "upbeat"
    if tempo < 90 and mode == "minor":
        return "solemn"
    if tempo < 100:
        return "calm"
    return "bright"
