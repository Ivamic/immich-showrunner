# SPDX-License-Identifier: AGPL-3.0-or-later
"""People of the app in Jellyfin.

Jellyfin keeps one list of people for all libraries and looks every new one up on TMDB, the
prefix notwithstanding: a person named after somebody famous gets that person's birthplace,
biography and photo (checked on 12.4). So after a sync the app takes care of every person whose
name starts with its prefix and that it has not taken care of yet: it clears what came from
outside, sets the face from Immich and locks the person, so that Jellyfin does not fill it in
again. Locked means taken care of. People of other libraries are never touched."""

import logging
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from showrunner.immich.client import ImmichClient, ImmichError
from showrunner.targets.jellyfin.client import JellyfinClient

log = logging.getLogger(__name__)


def cleaned(item: dict[str, Any], description: str = "") -> dict[str, Any]:
    """The item of a person with what Jellyfin found elsewhere removed, our description, and
    locked."""
    result = dict(item)
    result["ProviderIds"] = {key: "" for key in item.get("ProviderIds") or {}}
    result["ProductionLocations"] = []
    result["Overview"] = description
    result["PremiereDate"] = None
    result["EndDate"] = None
    result["LockData"] = True
    return result


async def tend_people(
    jellyfin: JellyfinClient,
    immich: ImmichClient,
    prefix: str,
    people: Mapping[str, UUID],
    descriptions: Mapping[UUID, str] | None = None,
) -> list[str]:
    """Take care of the new people of the app. `people` maps every name the app wrote into
    metadata (with the prefix) to the person in Immich. A person with the prefix that the app did
    not write is left alone. Returns notes for the log."""
    if not prefix.strip():
        return []
    descriptions = descriptions or {}
    notes: list[str] = []
    user_id: str | None = None
    for person in await jellyfin.persons():
        name = str(person.get("Name", ""))
        immich_id = people.get(name)
        if not name.startswith(prefix) or immich_id is None:
            continue
        if user_id is None:
            user_id = await jellyfin.admin_user_id()
        item = await jellyfin.item(str(person["Id"]), user_id)
        description = descriptions.get(immich_id, "")
        if item.get("LockData"):
            # Taken care of earlier; only a description changed on the page is written again.
            if (item.get("Overview") or "") != description:
                await jellyfin.update_item(str(person["Id"]), {**item, "Overview": description})
                notes.append(f"wrote the description of {name}")
            continue
        try:
            face = await immich.person_picture(immich_id)
        except ImmichError as exc:
            log.warning("no face for %s from Immich: %s", name, exc)
        else:
            # Replaces the photo Jellyfin may have taken from TMDB for a namesake.
            await jellyfin.set_primary_image(str(person["Id"]), face)
        await jellyfin.update_item(str(person["Id"]), cleaned(item, description))
        notes.append(f"took care of the person {name}")
    return notes
