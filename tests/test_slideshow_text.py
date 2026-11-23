# SPDX-License-Identifier: AGPL-3.0-or-later
"""The text of a slideshow: the months of a part by name in the language chosen, the places where
its photos were taken under the title, and slideshows drawn before not made again for nothing."""

from dataclasses import replace
from datetime import datetime

import numpy as np
import pytest
from test_slideshow_plan import day, photo

from fake_immich import album_id
from showrunner.artwork.paint import Frame
from showrunner.artwork.render import render
from showrunner.artwork.style import OutputKind, builtin_styles
from showrunner.model.naming import WHOLE_ALBUM
from showrunner.slideshow.plan import Clip, PlanPhoto, places_of, plan_album
from showrunner.slideshow.words import LANGUAGES, MONTHS, MUSIC, language_of, months, music_line


def clip(year: int = 2024, part: int = 0, **kw: object) -> Clip:
    values: dict[str, object] = {
        "album_id": album_id(1),
        "year": year,
        "part": part,
        "first": datetime(2024, 3, 2),
        "last": datetime(2024, 7, 30),
        "shots": (),
        "left_out": 0,
        "title": "Dacha",
        "credits": True,
    }
    return Clip(**(values | kw))  # type: ignore[arg-type]


def at(n: int, city: str = "", country: str = "") -> PlanPhoto:
    return replace(photo(n, n * 20), city=city, country=country)


# --- the words --------------------------------------------------------------------------------


def test_every_language_of_the_page_has_its_months_and_its_word_for_the_music() -> None:
    assert LANGUAGES == ("en", "de", "fr", "it", "ru")
    for language in LANGUAGES:
        assert len(MONTHS[language]) == 12 and len(set(MONTHS[language])) == 12
        assert "{}" in MUSIC[language]
    assert language_of("es") == language_of(None) == "en"


def test_months_are_named_with_the_year_after_them() -> None:
    assert months(3, 7, 2024, "en") == "March\N{EN DASH}July 2024"
    assert months(3, 7, 2024, "ru") == "март\N{EN DASH}июль 2024"
    assert months(12, 12, 2024, "de") == "Dezember 2024", "one month once"
    assert music_line("“Piece”", "fr") == "Musique : “Piece”"


# --- the title --------------------------------------------------------------------------------


def test_the_date_is_a_line_of_its_own_under_the_title() -> None:
    assert clip().under_title == ("2024",), "the title is the album alone"
    assert clip(part=1).under_title == ("March\N{EN DASH}July 2024",)
    assert clip(part=1, language="ru").when == "март\N{EN DASH}июль 2024"
    one = clip(part=2, first=datetime(2024, 8, 1), last=datetime(2024, 8, 20), language="it")
    assert one.when == "agosto 2024", "one month once"
    assert clip(language="ru").when == "2024", "a year: no months"
    whole = clip(year=WHOLE_ALBUM, part=1, first=datetime(2019, 5, 1))
    assert whole.when == "2019\N{EN DASH}2024", "the whole album: its years"
    named = clip(places=("Nice", "Monaco"))
    assert named.under_title == ("2024", "Nice · Monaco"), "the places last, smallest"


def test_the_language_and_the_places_are_in_the_cut_list() -> None:
    plain = clip().to_dict()
    assert not {"language", "places"} & plain.keys(), "only when there is something to say"
    assert clip(language="de").version != clip().version
    assert clip(places=("Nice",)).version != clip().version
    again = Clip.from_dict(clip(part=1, language="ru", places=("Nice", "Monaco")).to_dict())
    assert (again.language, again.places) == ("ru", ("Nice", "Monaco"))


# --- the places -------------------------------------------------------------------------------


def test_the_places_are_the_cities_in_the_order_they_come() -> None:
    photos = [at(1, "Rome", "Italy"), at(2, "Tivoli", "Italy"), at(3, "Rome", "Italy")]
    assert places_of(photos) == ("Rome", "Tivoli")
    assert places_of([at(1, "", "Italy"), at(2)]) == ("Italy",), "the country without a city"
    assert places_of([at(1), at(2)]) == (), "no coordinates, no places"


def test_a_stop_on_the_way_is_passed_by() -> None:
    photos = [at(i, "Village", "Russia") for i in range(40)] + [at(99, "Town", "Russia")]
    assert places_of(photos) == ("Village",)


def test_at_most_three_cities_those_with_the_most_photos() -> None:
    names = ["Rome"] * 5 + ["Tivoli"] * 2 + ["Florence"] * 6 + ["Pisa"] * 4
    photos = [at(i, name, "Italy") for i, name in enumerate(names)]
    assert places_of(photos) == ("Rome", "Florence", "Pisa")


def test_many_cities_of_several_countries_give_the_countries() -> None:
    trip = [("Nice", "France"), ("Monaco", "Monaco"), ("Genoa", "Italy"), ("Pisa", "Italy")]
    photos = [at(i * 10 + k, c, land) for i, (c, land) in enumerate(trip) for k in range(3)]
    assert places_of(photos) == ("France", "Monaco", "Italy")


def test_the_album_names_its_places_only_when_asked() -> None:
    photos = [replace(p, city="Nice", country="France") for p in day(1, 8)]
    (without,) = plan_album(album_id(1), "Trip", photos)
    assert without.places == ()
    (named,) = plan_album(album_id(1), "Trip", photos, places=True, language="fr")
    assert (named.places, named.language) == (("Nice",), "fr")


# --- the picture ------------------------------------------------------------------------------


@pytest.mark.parametrize("style_id", sorted(builtin_styles()))
def test_the_date_and_the_places_are_drawn_under_the_title_in_every_style(style_id: str) -> None:
    style = builtin_styles()[style_id]
    rng = np.random.default_rng(1)
    frames = [Frame(image=_picture(rng)) for _ in range(min(4, style.spec.max_frames))]
    title = "Dubrovnik - Rome - Tivoli"
    plain = render(style, OutputKind.LANDSCAPE, frames, title, 0)
    again = render(style, OutputKind.LANDSCAPE, frames, title, 0, ("", " "))
    assert plain.image.tobytes() == again.image.tobytes(), "nothing under: as before"
    dated = render(style, OutputKind.LANDSCAPE, frames, title, 0, ("March\N{EN DASH}July 2024",))
    named = render(
        style, OutputKind.LANDSCAPE, frames, title, 0, ("2024", "Rome · Tivoli · Florence")
    )
    assert dated.image.size == named.image.size == plain.image.size
    assert len({plain.image.tobytes(), dated.image.tobytes(), named.image.tobytes()}) == 3
    long = ("2024", "Rome · " * 40)
    assert render(style, OutputKind.LANDSCAPE, frames, title, 0, long).image.size == (1920, 1080)


def _picture(rng: np.random.Generator):  # type: ignore[no-untyped-def]
    from PIL import Image

    return Image.fromarray(rng.integers(0, 255, (300, 400, 3), dtype=np.uint8))


def test_the_lines_under_the_title_keep_off_the_frames_beside_it() -> None:
    from showrunner.artwork.render import _room_beside
    from showrunner.artwork.style import TextBlock

    spec = TextBlock(font="f", area=(0, 0, 50, 100), anchor="top", size=(10, 40))
    area = (100.0, 100.0, 400.0, 800.0)
    alone = (100.0, 100.0, 300.0, 200.0)
    below = (100.0, 600.0, 300.0, 300.0)
    room = _room_beside([below], alone, spec, area, 40, 1000)
    assert 400 < room < 500, "down to the frame below, less a gap"
    wash = (-500.0, 0.0, 620.0, 1000.0)  # a wash of colour that touches the text's edge
    assert _room_beside([wash, below], alone, spec, area, 40, 1000) == room
    under = (50.0, 50.0, 500.0, 400.0)  # the text lies on a frame: the style means it so
    assert _room_beside([under, below], alone, spec, area, 40, 1000) == area[3]
