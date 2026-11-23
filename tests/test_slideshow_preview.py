# SPDX-License-Identifier: AGPL-3.0-or-later
"""The titles alone, to look over: one a year before a pass plans the slideshows, the planned
ones after; the name of the show, the places, an album switched off left out; nothing written
but the pictures."""

import json
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession
from test_slideshow_sync import photo_album

from fake_immich import album_id, asset_id
from showrunner.artwork.style import builtin_styles
from showrunner.slideshow.preview import preview_titles
from showrunner.store.registry import Registry
from showrunner.sync.specials import plan_file


@pytest.mark.anyio
async def test_titles_are_drawn_one_a_year_before_a_plan_and_as_planned_after(
    session: AsyncSession, tmp_path: Path
) -> None:
    immich = photo_album(years=(2023, 2024))
    album = next(iter(immich.albums))
    for item in immich.photos[album]:
        item["exifInfo"] |= {"city": "Nice", "country": "France"}
    out, data = tmp_path / "titles", tmp_path / "data"
    out.mkdir()
    lines: list[str] = []
    registry = Registry(session)
    async with immich.client() as client:
        written = await preview_titles(
            client, registry, builtin_styles(), out, data_dir=data, say=lines.append
        )
    assert sorted(p.name for p in written) == ["Holidays - 2023.jpg", "Holidays - 2024.jpg"]
    assert all("one a year" in line for line in lines)
    with Image.open(written[0]) as picture:
        assert picture.size == (1920, 1080)

    # A pass planned the year 2024 in two parts.
    first, second = [str(asset_id(n)) for n in (17, 18)], [str(asset_id(n)) for n in (19, 20)]

    def photos(ids: list[str], day: int) -> list[dict[str, str]]:
        return [
            {"id": i, "taken": f"2024-0{day}-01T09:0{k}:00", "fate": "shown"}
            for k, i in enumerate(ids)
        ]

    plan = {
        "slideshows": [
            {"year": 2024, "part": 1, "title": "Photos 2024 (1/2)", "photos": photos(first, 3)},
            {"year": 2024, "part": 2, "title": "Photos 2024 (2/2)", "photos": photos(second, 7)},
        ]
    }
    plan_file(data, album_id(1)).parent.mkdir(parents=True)
    plan_file(data, album_id(1)).write_text(json.dumps(plan), encoding="utf-8")
    await registry.add_show(album_id(1), "Holidays")
    await registry.commit()
    lines.clear()
    again = tmp_path / "again"
    again.mkdir()
    async with immich.client() as client:
        written = await preview_titles(
            client, registry, builtin_styles(), again, data_dir=data, say=lines.append
        )
    assert sorted(p.name for p in written) == [
        "Holidays - 2024 part 1.jpg",
        "Holidays - 2024 part 2.jpg",
    ]
    assert all("as planned" in line for line in lines)


@pytest.mark.anyio
async def test_an_album_switched_off_or_not_asked_for_gets_no_title(
    session: AsyncSession, tmp_path: Path
) -> None:
    immich = photo_album()
    registry = Registry(session)
    await registry.add_show(album_id(1), "Holidays")
    await registry.save_album_slideshow(album_id(1), enabled=False)
    await registry.commit()
    async with immich.client() as client:
        assert await preview_titles(client, registry, builtin_styles(), tmp_path, say=print) == []
        await registry.save_album_slideshow(album_id(1), enabled=None)
        await registry.commit()
        found = await preview_titles(
            client, registry, builtin_styles(), tmp_path, only="nothing", say=print
        )
        assert found == []
    assert list(tmp_path.iterdir()) == []
