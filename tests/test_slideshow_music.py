# SPDX-License-Identifier: AGPL-3.0-or-later
"""Looking at music: synthetic pieces with a known tempo, meter, key, loudness and parts, and
files that are not music."""

from pathlib import Path

import av
import numpy as np
import pytest

from showrunner.slideshow.music import MusicAnalysis, MusicError, analyse, measure_loudness

RATE = 44100
C_MAJOR = [
    (261.63, 329.63, 392.00),  # C
    (349.23, 440.00, 523.25),  # F
    (392.00, 493.88, 587.33),  # G
    (261.63, 329.63, 392.00),  # C
]


def piece(
    seconds: float = 40.0,
    bpm: float = 120.0,
    meter: int = 4,
    *,
    lead_in: float = 0.0,
    drums_from: float = 0.0,
    seed: int = 0,
) -> np.ndarray:
    """Stereo: a kick on every beat (strong on the first of a bar), a hi-hat, and chords of C
    major changing every bar; the drums only from `drums_from` on, the chords throughout."""
    rng = np.random.default_rng(seed)
    n = int(RATE * (seconds + lead_in))
    y = np.zeros(n, np.float32)
    period = 60.0 / bpm
    beat = 0
    while True:
        at = int((lead_in + beat * period) * RATE)
        if at >= n:
            break
        first = beat % meter == 0
        length = min(int(0.3 * RATE), n - at)
        t = np.arange(length) / RATE
        if beat * period >= drums_from:
            kick = np.sin(2 * np.pi * (55 + 90 * np.exp(-t * 30)) * t) * np.exp(-t * 10)
            hat = rng.standard_normal(length) * np.exp(-t * 70) * 0.12
            y[at : at + length] += ((1.0 if first else 0.35) * kick + hat).astype(np.float32)
        if first:
            chord = C_MAJOR[(beat // meter) % len(C_MAJOR)]
            bar = min(int(period * meter * RATE), n - at)
            s = np.arange(bar) / RATE
            tone = sum(np.sin(2 * np.pi * f * s) for f in chord) * np.exp(-s * 0.6) * 0.08
            y[at : at + bar] += tone.astype(np.float32)
        beat += 1
    y = y / np.abs(y).max() * 0.7
    return np.stack([y, y])


def write(path: Path, sound: np.ndarray, *, codec: str = "pcm_s16le", rate: int = RATE) -> Path:
    container = "wav" if codec.startswith("pcm") else None
    with av.open(str(path), "w", format=container) as file:
        stream = file.add_stream(codec, rate=rate)
        assert isinstance(stream, av.AudioStream)
        stream.layout = "stereo"
        step = 4096
        for i in range(0, sound.shape[1], step):
            frame = av.AudioFrame.from_ndarray(
                np.ascontiguousarray(sound[:, i : i + step]), format="fltp", layout="stereo"
            )
            frame.sample_rate = rate
            frame.pts = i
            for packet in stream.encode(frame):
                file.mux(packet)
        for packet in stream.encode():
            file.mux(packet)
    return path


@pytest.fixture(scope="module")
def steady(tmp_path_factory: pytest.TempPathFactory) -> MusicAnalysis:
    path = tmp_path_factory.mktemp("music") / "steady.wav"
    return analyse(write(path, piece(bpm=120, meter=4, lead_in=3.0)))


def test_the_tempo_and_the_beats_are_found(steady: MusicAnalysis) -> None:
    assert steady.tempo == pytest.approx(120, abs=2)
    gaps = np.diff(steady.beats)
    assert np.median(gaps) == pytest.approx(0.5, abs=0.02)
    # Every beat on a kick: 3 s of silence, then a kick every half second.
    offsets = (np.array(steady.beats) - 3.0) / 0.5
    assert np.abs(offsets - np.round(offsets)).max() * 0.5 < 0.04


def test_the_first_beats_of_the_bars_are_found(steady: MusicAnalysis) -> None:
    assert steady.meter == 4
    offsets = (np.array(steady.downbeats) - 3.0) / 2.0
    assert np.abs(offsets - np.round(offsets)).max() * 2.0 < 0.05, steady.downbeats[:5]


def test_silence_at_the_start_is_left_out(steady: MusicAnalysis) -> None:
    assert steady.start == pytest.approx(3.0, abs=0.06)
    assert steady.end == pytest.approx(steady.seconds, abs=0.4)
    assert steady.beats[0] >= steady.start - 0.06


def test_the_key_is_found(steady: MusicAnalysis) -> None:
    assert (steady.key, steady.mode) == ("C", "major")


def test_a_waltz_has_three_beats_in_a_bar(tmp_path: Path) -> None:
    found = analyse(write(tmp_path / "waltz.wav", piece(seconds=45, bpm=150, meter=3)))
    assert found.tempo == pytest.approx(150, abs=3)
    assert found.meter == 3


def test_where_the_drums_come_in_a_new_part_begins(tmp_path: Path) -> None:
    found = analyse(write(tmp_path / "parts.wav", piece(seconds=64, bpm=120, drums_from=32)))
    assert any(abs(s - 32) <= 2.1 for s in found.sections), found.sections


def test_loudness_is_measured_as_ebu_r128_says(tmp_path: Path) -> None:
    # EBU Tech 3341, test 1: a stereo sine of 1 kHz at -23 dBFS reads -23.0 LUFS.
    t = np.arange(48000 * 20) / 48000
    sine = (10 ** (-23 / 20) * np.sin(2 * np.pi * 1000 * t)).astype(np.float32)
    path = write(tmp_path / "sine.wav", np.stack([sine, sine]), codec="pcm_f32le", rate=48000)
    loudness, peak = measure_loudness(path)
    assert loudness == pytest.approx(-23.0, abs=0.1)
    assert peak == pytest.approx(-23.0, abs=0.5)
    # A length that ends in a short frame of the meter: still measured.
    odd = sine[: 44100 * 19 + 1234]
    path = write(tmp_path / "odd.wav", np.stack([odd, odd]), codec="pcm_f32le", rate=44100)
    assert measure_loudness(path)[0] == pytest.approx(-23.0, abs=0.2)


def test_compressed_music_is_read(tmp_path: Path) -> None:
    found = analyse(write(tmp_path / "steady.m4a", piece(bpm=100), codec="aac"))
    assert found.tempo == pytest.approx(100, abs=2)


def test_what_is_not_music_is_refused(tmp_path: Path) -> None:
    short = write(tmp_path / "short.wav", piece(seconds=10))
    with pytest.raises(MusicError, match="lasts"):
        analyse(short)
    text = tmp_path / "notes.mp3"
    text.write_text("not music")
    with pytest.raises(MusicError):
        analyse(text)
    video = tmp_path / "clip.mp4"
    with av.open(str(video), "w") as file:
        stream = file.add_stream("libx264", rate=10)
        stream.width, stream.height, stream.pix_fmt = 64, 64, "yuv420p"
        for _ in range(5):
            frame = av.VideoFrame.from_ndarray(np.zeros((64, 64, 3), np.uint8), format="rgb24")
            for packet in stream.encode(frame):
                file.mux(packet)
        for packet in stream.encode():
            file.mux(packet)
    with pytest.raises(MusicError):
        analyse(video)


def test_an_analysis_is_kept_as_plain_data(steady: MusicAnalysis) -> None:
    data = steady.to_dict()
    again = MusicAnalysis.from_dict(data)
    assert again is not None and again.to_dict() == data
    assert MusicAnalysis.from_dict({**data, "v": 0}) is None
