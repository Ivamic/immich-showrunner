# SPDX-License-Identifier: AGPL-3.0-or-later
"""The music of slideshows: the user's own pieces with what is known of them, the set downloaded
from the mirror and kept only when it is the set, each piece looked at once; and the mood of an
album from its photos."""

import hashlib
import io
import json
import zipfile
from pathlib import Path

import httpx2
import numpy as np
import pytest
from test_slideshow_music import piece, write

from showrunner.slideshow import library
from showrunner.slideshow.content import album_mood, prompts
from showrunner.slideshow.library import (
    Piece,
    ensure_set,
    own_pieces,
    pending,
    remember,
    set_pieces,
    tracks,
)
from showrunner.slideshow.music import MusicAnalysis, MusicError


def analysis(mood: str = "calm") -> MusicAnalysis:
    return MusicAnalysis(
        seconds=60.0,
        start=0.0,
        end=60.0,
        loudness=-18.0,
        true_peak=-2.0,
        tempo=100.0,
        beats=(0.6, 1.2),
        downbeats=(0.6,),
        meter=4,
        sections=(),
        energy=(-20.0,),
        key="C",
        mode="major",
        mood=mood,
    )


def test_a_credit_says_what_is_known_and_nothing_else(tmp_path: Path) -> None:
    full = Piece("x", tmp_path, "0", "Morning", "Kevin MacLeod", "CC BY 4.0", "https://x.test")
    assert full.credit == (
        "\u201cMorning\u201d by Kevin MacLeod, CC BY 4.0, https://x.test; trimmed and faded"
    )
    assert Piece("x", tmp_path, "0", title="Song").credit == "\u201cSong\u201d; trimmed and faded"
    assert Piece("x", tmp_path, "0").credit == "", "nothing known: no line at all"


def test_own_music_with_what_its_tags_and_its_yaml_say(tmp_path: Path) -> None:
    own = tmp_path / "music" / "own"
    own.mkdir(parents=True)
    write(own / "first.wav", piece(seconds=31))
    (own / "first.yaml").write_text(
        "title: Our song\nauthor: Uncle Bob\nmood: upbeat\nunknown: ignored\n", encoding="utf-8"
    )
    write(own / "second.wav", piece(seconds=31))
    (own / "second.yaml").write_text("- not a mapping\n", encoding="utf-8")
    (own / "notes.txt").write_text("not music", encoding="utf-8")
    found = {p.path.name: p for p in own_pieces(tmp_path)}
    assert set(found) == {"first.wav", "second.wav"}
    first = found["first.wav"]
    assert (first.title, first.author, first.mood) == ("Our song", "Uncle Bob", "upbeat")
    assert first.id.startswith("own/first.wav@")
    assert found["second.wav"].credit == ""


def test_a_piece_is_looked_at_once_and_a_bad_one_left_out(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    good = Piece("own/a", tmp_path / "a.mp3", "a" * 64, title="A")
    bad = Piece("own/b", tmp_path / "b.mp3", "b" * 64)
    assert pending([good, bad], cache) == [good, bad]
    remember(good, cache, analysis("bright"))
    remember(bad, cache, MusicError("it is a video, not music"))
    assert pending([good, bad], cache) == []
    (track,) = tracks([good, bad], cache)
    assert (track.id, track.mood, track.credit) == (
        "own/a",
        "bright",
        "\u201cA\u201d; trimmed and faded",
    )
    # Looked at by another version: looked at again.
    record = json.loads((cache / f"{'b' * 64}.json").read_text(encoding="utf-8"))
    (cache / f"{'b' * 64}.json").write_text(json.dumps({**record, "v": 0}), encoding="utf-8")
    assert pending([good, bad], cache) == [bad]


def set_of(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, licence: str = "CC0 1.0") -> bytes:
    """A manifest of two pieces in an archive; returns the archive."""
    files = {"one.ogg": b"first piece", "two.ogg": b"second piece"}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zipped:
        for name, content in files.items():
            zipped.writestr(f"set/{name}", content)
        zipped.writestr("../../escape.ogg", b"never")
    archive = buffer.getvalue()
    manifest = {
        "version": 1,
        "archive": {
            "url": "https://mirror.test/set.zip",
            "sha256": hashlib.sha256(archive).hexdigest(),
        },
        "tracks": [
            {
                "id": name.split(".")[0],
                "file": name,
                "sha256": hashlib.sha256(content).hexdigest(),
                "title": name,
                "author": "Someone",
                "license": licence,
                "mood": "calm",
            }
            for name, content in files.items()
        ],
    }
    path = tmp_path / "music_set.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(library, "SET_MANIFEST", path)
    return archive


def serve(body: bytes) -> httpx2.MockTransport:
    return httpx2.MockTransport(lambda request: httpx2.Response(200, content=body))


@pytest.mark.anyio
async def test_the_set_is_downloaded_and_kept_only_when_it_is_the_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = set_of(tmp_path, monkeypatch)
    data = tmp_path / "data"
    assert await ensure_set(data, transport=serve(b"something else")) == 0
    assert await ensure_set(data, transport=serve(archive)) == 2
    assert sorted(p.id for p in set_pieces(data)) == ["set/one", "set/two"]
    assert not (tmp_path / "escape.ogg").exists() and not (data / "escape.ogg").exists()
    assert set_pieces(data)[0].credit.endswith("CC0 1.0"), "nothing was changed that CC0 minds"
    # A piece changed on the disk is not the set any more.
    (data / "music" / "set" / "one.ogg").write_bytes(b"tampered")
    assert [p.id for p in set_pieces(data)] == ["set/two"]


def test_the_set_holds_no_licence_but_cc0_public_domain_and_cc_by(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    set_of(tmp_path, monkeypatch, licence="CC BY-SA 4.0")
    with pytest.raises(ValueError, match="BY-SA"):
        library.set_manifest()


def test_the_set_shipped_is_valid() -> None:
    manifest = library.set_manifest()
    assert manifest["version"] == 2
    moods = {t["mood"] for t in manifest["tracks"]}
    assert moods == set(library.MOODS), "every mood has pieces of the set"


def word(text: str) -> np.ndarray:
    words = prompts()
    row: np.ndarray = words.vectors[words.texts.index(text)]
    return row


def test_the_mood_of_an_album_follows_its_photos() -> None:
    mountains = [word("a photo of mountains")] * 5 + [word("a landscape photo")] * 3
    assert album_mood(mountains) == "cinematic"
    from_above = [word("an aerial photo of a landscape from above")] * 3 + [word("a selfie")] * 2
    assert album_mood(from_above) == "cinematic"
    winter = [word("a photo of snow in winter")] * 4 + [word("a photo of flowers and plants")]
    assert album_mood(winter) == "calm"
    family = [word("a family photo")] * 4 + [word("a photo of mountains")]
    assert album_mood(family) == "bright"
    party = [word("a group photo at a party")] * 3 + [word("a family photo")] * 4
    assert album_mood(party) == "upbeat"
    assert album_mood([]) == "calm"


def test_the_set_credits_cc_by_with_the_licence_and_names_every_piece() -> None:
    manifest = library.set_manifest()
    assert len(manifest["tracks"]) >= 10
    assert manifest["archive"]["url"].startswith("https://github.com/")
    notices = (Path(__file__).parents[1] / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    for entry in manifest["tracks"]:
        assert entry["title"] in notices, entry["id"]
        piece = Piece(
            entry["id"],
            Path(entry["file"]),
            entry["sha256"],
            entry["title"],
            entry["author"],
            entry["license"],
            entry["license_url"] if entry["license"].startswith("CC BY") else "",
        )
        if entry["license"].startswith("CC BY"):
            assert entry["license_url"] in piece.credit and "trimmed and faded" in piece.credit
    assert {e["mood"] for e in manifest["tracks"]} >= {"calm", "wistful", "bright", "upbeat"}
