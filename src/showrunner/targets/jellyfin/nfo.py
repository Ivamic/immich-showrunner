# SPDX-License-Identifier: AGPL-3.0-or-later
"""NFO files as Jellyfin 12 reads them (checked on 12.4): `tvshow.nfo` and one per episode.

The episode number is always written. Without it Jellyfin picks a number out of the file name."""

import re
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


def show_nfo(show: Show) -> bytes:
    root = ET.Element("tvshow")
    _add(root, "title", show.title)
    _add(root, "sorttitle", show.sort_title)
    if show.plot:
        _add(root, "plot", show.plot)
    _add(root, "uniqueid", str(show.album_id), type=UNIQUE_ID_TYPE, default="true")
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
