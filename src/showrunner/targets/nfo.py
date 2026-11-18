# SPDX-License-Identifier: AGPL-3.0-or-later
"""NFO files: `tvshow.nfo` and one per episode, as Jellyfin 12 and Kodi 21 read them (checked on
Jellyfin 12.4 and Kodi 21.3).

The season and the episode number are always written: both media servers would otherwise take
them from the file name."""

import re
from collections.abc import Mapping
from xml.etree import ElementTree as ET

from showrunner.model.show import Episode, Show

UNIQUE_ID_TYPE = "immich"
# Characters that XML 1.0 can not hold.
_INVALID_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")


def _add(parent: ET.Element, tag: str, text: str, **attributes: str) -> ET.Element:
    element = ET.SubElement(parent, tag, attributes)
    element.text = _INVALID_XML.sub("", text)
    return element


def _render(root: ET.Element) -> bytes:
    ET.indent(root, space="  ")
    body = ET.tostring(root, encoding="unicode", short_empty_elements=False)
    return f'<?xml version="1.0" encoding="utf-8" standalone="yes"?>\n{body}\n'.encode()


def show_nfo(show: Show, season_posters: Mapping[int, str] | None = None) -> bytes:
    """`season_posters` maps seasons to the paths of their posters as the media server sees
    them (Kodi takes the posters of seasons from here; a `seasonNNNN-poster.jpg` would make it
    count thousands of empty seasons)."""
    root = ET.Element("tvshow")
    _add(root, "title", show.title)
    _add(root, "sorttitle", show.sort_title)
    if show.plot:
        _add(root, "plot", show.plot)
    _add(root, "uniqueid", str(show.album_id), type=UNIQUE_ID_TYPE, default="true")
    for season, path in sorted((season_posters or {}).items()):
        _add(root, "thumb", path, aspect="poster", type="season", season=str(season))
    return _render(root)


def episode_nfo(episode: Episode) -> bytes:
    root = ET.Element("episodedetails")
    _add(root, "title", episode.title)
    if episode.plot:
        _add(root, "plot", episode.plot)
    _add(root, "aired", f"{episode.filmed_at:%Y-%m-%d}")
    _add(root, "season", str(episode.season))
    _add(root, "episode", str(episode.number))
    _add(root, "uniqueid", str(episode.asset_id), type=UNIQUE_ID_TYPE, default="true")
    for person in episode.people:
        actor = ET.SubElement(root, "actor")
        _add(actor, "name", person.name)
        _add(actor, "type", "Actor")
    return _render(root)
