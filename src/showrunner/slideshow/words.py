# SPDX-License-Identifier: AGPL-3.0-or-later
"""The words a slideshow shows, in the language chosen for its text: the months on the title of
a part, and the word before the music in the credits and in the description of the episode.

English unless another is chosen. The names of places come from Immich as they are."""

from __future__ import annotations

LANGUAGES = ("en", "de", "fr", "it", "ru")
DEFAULT_LANGUAGE = "en"

MONTHS: dict[str, tuple[str, ...]] = {
    "en": (
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
    ),
    "de": (
        "Januar",
        "Februar",
        "März",
        "April",
        "Mai",
        "Juni",
        "Juli",
        "August",
        "September",
        "Oktober",
        "November",
        "Dezember",
    ),
    "fr": (
        "janvier",
        "février",
        "mars",
        "avril",
        "mai",
        "juin",
        "juillet",
        "août",
        "septembre",
        "octobre",
        "novembre",
        "décembre",
    ),
    "it": (
        "gennaio",
        "febbraio",
        "marzo",
        "aprile",
        "maggio",
        "giugno",
        "luglio",
        "agosto",
        "settembre",
        "ottobre",
        "novembre",
        "dicembre",
    ),
    # The months as named on their own (nominative), not in a date ("марта").
    "ru": (
        "январь",
        "февраль",
        "март",
        "апрель",
        "май",
        "июнь",
        "июль",
        "август",
        "сентябрь",
        "октябрь",
        "ноябрь",
        "декабрь",
    ),
}

MUSIC: dict[str, str] = {
    "en": "Music: {}",
    "de": "Musik: {}",
    "fr": "Musique : {}",
    "it": "Musica: {}",
    "ru": "Музыка: {}",
}


def language_of(language: str | None) -> str:
    """The language given when it is one of the slideshow's, else English."""
    return language if language in LANGUAGES else DEFAULT_LANGUAGE


def months(first: int, last: int, year: int, language: str) -> str:
    """`March-July 2024` (with an en dash), or `March 2024` when both are one month."""
    names = MONTHS[language_of(language)]
    if first == last:
        return f"{names[first - 1]} {year}"
    return f"{names[first - 1]}\N{EN DASH}{names[last - 1]} {year}"


def music_line(line: str, language: str) -> str:
    """`Music: “Water Lily” — …`, in the language of the slideshow."""
    return MUSIC[language_of(language)].format(line)


__all__ = ["DEFAULT_LANGUAGE", "LANGUAGES", "language_of", "months", "music_line"]
