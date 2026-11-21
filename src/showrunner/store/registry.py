# SPDX-License-Identifier: AGPL-3.0-or-later
"""The registry: which shows there are and which files the app created for them."""

from collections.abc import Collection, Mapping
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from showrunner.model.naming import show_folder_name
from showrunner.model.show import EpisodeEdit, ShowEdit
from showrunner.store.models import (
    AlbumSlideshowRow,
    ArtworkRow,
    EpisodeEditRow,
    FileRow,
    FrameLookRow,
    MusicSettingRow,
    PendingRow,
    PersonDescriptionRow,
    PersonRow,
    PhotoLookRow,
    ShowRow,
    SlideshowSettingRow,
    StyleSettingRow,
)
from showrunner.sync.plan import Entry
from showrunner.targets.base import JELLYFIN, DesiredFile, FileKind


class Registry:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def shows(self) -> dict[UUID, ShowRow]:
        rows = await self._session.scalars(select(ShowRow))
        return {row.album_id: row for row in rows}

    async def add_show(self, album_id: UUID, album_name: str) -> ShowRow:
        """Record a new show and give it a folder name that no other show has."""
        folder = show_folder_name(album_name, album_id)
        taken = await self._session.scalar(select(ShowRow).where(ShowRow.folder_name == folder))
        if taken is not None:  # two albums with the same name and the same start of the id
            folder = f"{folder[:-1]}-{album_id.hex[8:16]}]"
        row = ShowRow(album_id=album_id, folder_name=folder)
        self._session.add(row)
        await self._session.flush()
        return row

    async def entries(self, target: str = JELLYFIN) -> list[Entry]:
        rows = await self._session.scalars(
            select(FileRow).where(FileRow.target == target).order_by(FileRow.path)
        )
        return [
            Entry(
                path=PurePosixPath(row.path),
                kind=FileKind(row.kind),
                album_id=row.album_id,
                asset_id=row.asset_id,
                link_target=PurePosixPath(row.link_target) if row.link_target else None,
                content_hash=row.content_hash,
                source_version=row.source_version,
            )
            for row in rows
        ]

    async def record(self, file: DesiredFile, target: str = JELLYFIN) -> None:
        """Remember that `file` now exists as described in the output folder of `target`."""
        values = {
            "kind": file.kind.value,
            "album_id": file.album_id,
            "asset_id": file.asset_id,
            "link_target": str(file.link_target) if file.link_target else None,
            "content_hash": file.content_hash,
            "source_version": file.source_version,
        }
        statement = insert(FileRow).values(target=target, path=str(file.path), **values)
        await self._session.execute(
            statement.on_conflict_do_update(
                index_elements=[FileRow.target, FileRow.path],
                set_={**values, "updated_at": statement.excluded.updated_at},
            )
        )

    async def forget(self, path: PurePosixPath, target: str = JELLYFIN) -> None:
        await self._session.execute(
            delete(FileRow).where(FileRow.target == target, FileRow.path == str(path))
        )

    async def set_stamps(
        self, album_id: UUID, album_updated_at: datetime | None, assets_modified_at: datetime | None
    ) -> None:
        row = await self._session.get(ShowRow, album_id)
        if row is not None:
            row.album_updated_at = album_updated_at
            row.assets_modified_at = assets_modified_at

    async def mark_pending(self, album_ids: Collection[UUID], target: str = JELLYFIN) -> None:
        """The media server of `target` has to be told about these shows."""
        if album_ids:
            statement = insert(PendingRow).values(
                [{"target": target, "album_id": album_id} for album_id in album_ids]
            )
            await self._session.execute(statement.on_conflict_do_nothing())

    async def pending(self, target: str = JELLYFIN) -> set[UUID]:
        rows = await self._session.scalars(
            select(PendingRow.album_id).where(PendingRow.target == target)
        )
        return set(rows)

    async def clear_pending(self, album_ids: Collection[UUID], target: str = JELLYFIN) -> None:
        if album_ids:
            await self._session.execute(
                delete(PendingRow).where(
                    PendingRow.target == target, PendingRow.album_id.in_(list(album_ids))
                )
            )

    async def remember_people(self, people: Mapping[str, UUID]) -> None:
        """Remember which person of Immich each name stands for."""
        for name, immich_id in people.items():
            statement = insert(PersonRow).values(name=name, immich_id=immich_id)
            await self._session.execute(
                statement.on_conflict_do_update(
                    index_elements=[PersonRow.name],
                    set_={"immich_id": immich_id, "seen_at": func.now()},
                )
            )

    async def people(self) -> dict[str, UUID]:
        rows = await self._session.execute(select(PersonRow.name, PersonRow.immich_id))
        return {name: immich_id for name, immich_id in rows}

    async def episode_edits(self, album_id: UUID) -> dict[UUID, EpisodeEdit]:
        rows = await self._session.scalars(
            select(EpisodeEditRow).where(EpisodeEditRow.album_id == album_id)
        )
        return {
            row.asset_id: EpisodeEdit(
                title=row.title, plot=row.plot, sort_at=row.sort_at, hidden=row.hidden
            )
            for row in rows
        }

    async def save_episode_edit(self, album_id: UUID, asset_id: UUID, edit: EpisodeEdit) -> None:
        """Keep `edit`; an edit that changes nothing is removed."""
        row = await self._session.get(EpisodeEditRow, (album_id, asset_id))
        if edit == EpisodeEdit():
            if row is not None:
                await self._session.delete(row)
            return
        if row is None:
            row = EpisodeEditRow(album_id=album_id, asset_id=asset_id)
            self._session.add(row)
        row.title, row.plot, row.sort_at, row.hidden = (
            edit.title,
            edit.plot,
            edit.sort_at,
            edit.hidden,
        )

    @staticmethod
    def show_edit(row: ShowRow) -> ShowEdit:
        return ShowEdit(title=row.title)

    async def descriptions(self) -> dict[UUID, str]:
        rows = await self._session.scalars(select(PersonDescriptionRow))
        return {row.immich_id: row.text for row in rows}

    async def set_description(self, immich_id: UUID, text: str | None) -> None:
        """Keep the description of a person; None or an empty text removes it."""
        row = await self._session.get(PersonDescriptionRow, immich_id)
        if not text or not text.strip():
            if row is not None:
                await self._session.delete(row)
            return
        if row is None:
            row = PersonDescriptionRow(immich_id=immich_id)
            self._session.add(row)
        row.text = text.strip()

    async def frame_looks(self, asset_ids: Collection[UUID]) -> dict[UUID, FrameLookRow]:
        if not asset_ids:
            return {}
        # Rows written by an upsert in this session must be read as they are now, not as the
        # session last saw them.
        rows = await self._session.scalars(
            select(FrameLookRow)
            .where(FrameLookRow.asset_id.in_(list(asset_ids)))
            .execution_options(populate_existing=True)
        )
        return {row.asset_id: row for row in rows}

    async def save_frame_looks(
        self,
        asset_id: UUID,
        checksum: str,
        version: int,
        looks: list[dict[str, Any]],
        failed: bool = False,
    ) -> None:
        values = {
            "asset_id": asset_id,
            "checksum": checksum,
            "version": version,
            "looks": looks,
            "failed": failed,
            "analysed_at": func.now(),
        }
        statement = insert(FrameLookRow).values(**values)
        await self._session.execute(
            statement.on_conflict_do_update(
                index_elements=[FrameLookRow.asset_id],
                set_={k: statement.excluded[k] for k in values if k != "asset_id"},
            )
        )

    async def photo_looks(self, asset_ids: Collection[UUID]) -> dict[UUID, PhotoLookRow]:
        if not asset_ids:
            return {}
        rows = await self._session.scalars(
            select(PhotoLookRow)
            .where(PhotoLookRow.asset_id.in_(list(asset_ids)))
            .execution_options(populate_existing=True)
        )
        return {row.asset_id: row for row in rows}

    async def save_photo_look(
        self,
        asset_id: UUID,
        checksum: str,
        version: int,
        look: dict[str, Any],
        failed: bool = False,
        embedding: bytes | None = None,
        embedding_model: str | None = None,
    ) -> None:
        values = {
            "asset_id": asset_id,
            "checksum": checksum,
            "version": version,
            "look": look,
            "failed": failed,
            "embedding": embedding,
            "embedding_model": embedding_model,
            "analysed_at": func.now(),
        }
        statement = insert(PhotoLookRow).values(**values)
        await self._session.execute(
            statement.on_conflict_do_update(
                index_elements=[PhotoLookRow.asset_id],
                set_={k: statement.excluded[k] for k in values if k != "asset_id"},
            )
        )

    async def artworks(self) -> dict[UUID, ArtworkRow]:
        rows = await self._session.scalars(
            select(ArtworkRow).execution_options(populate_existing=True)
        )
        return {row.album_id: row for row in rows}

    async def save_artwork(self, album_id: UUID, style_id: str, **values: Any) -> None:
        """Set fields of the artwork of a show (`seed`, `use_cover`, `slot_seeds`, `drawn_jobs`,
        `pinned_jobs`),
        creating its row with `style_id` if there is none."""
        statement = insert(ArtworkRow).values(album_id=album_id, style_id=style_id, **values)
        await self._session.execute(
            statement.on_conflict_do_update(
                index_elements=[ArtworkRow.album_id],
                set_={"style_id": style_id, **values},
            )
        )

    # --- slideshows (D-103) ----------------------------------------------------------------

    async def slideshow_setting(self) -> SlideshowSettingRow | None:
        return await self._session.scalar(
            select(SlideshowSettingRow).execution_options(populate_existing=True)
        )

    async def save_slideshow_setting(self, **values: bool) -> None:
        statement = insert(SlideshowSettingRow).values(id=1, **values)
        await self._session.execute(
            statement.on_conflict_do_update(index_elements=[SlideshowSettingRow.id], set_=values)
        )

    async def album_slideshows(self) -> dict[UUID, AlbumSlideshowRow]:
        rows = await self._session.scalars(
            select(AlbumSlideshowRow).execution_options(populate_existing=True)
        )
        return {row.album_id: row for row in rows}

    async def save_album_slideshow(self, album_id: UUID, **values: Any) -> None:
        """Set fields of the slideshows of an album (`enabled`, `mood`, `music_seed`,
        `auto_mood`, `planned`), creating its row if there is none."""
        statement = insert(AlbumSlideshowRow).values(album_id=album_id, **values)
        await self._session.execute(
            statement.on_conflict_do_update(
                index_elements=[AlbumSlideshowRow.album_id], set_=values
            )
        )

    async def disabled_music(self) -> set[str]:
        rows = await self._session.scalars(
            select(MusicSettingRow.track_id).where(MusicSettingRow.enabled.is_(False))
        )
        return set(rows)

    async def set_music_enabled(self, track_id: str, enabled: bool) -> None:
        statement = insert(MusicSettingRow).values(track_id=track_id, enabled=enabled)
        await self._session.execute(
            statement.on_conflict_do_update(
                index_elements=[MusicSettingRow.track_id], set_={"enabled": enabled}
            )
        )

    async def disabled_styles(self) -> set[str]:
        rows = await self._session.scalars(
            select(StyleSettingRow.style_id).where(StyleSettingRow.enabled.is_(False))
        )
        return set(rows)

    async def set_style_enabled(self, style_id: str, enabled: bool) -> None:
        statement = insert(StyleSettingRow).values(style_id=style_id, enabled=enabled)
        await self._session.execute(
            statement.on_conflict_do_update(
                index_elements=[StyleSettingRow.style_id], set_={"enabled": enabled}
            )
        )

    async def set_artwork_style(self, album_id: UUID, style_id: str) -> None:
        statement = insert(ArtworkRow).values(album_id=album_id, style_id=style_id)
        await self._session.execute(
            statement.on_conflict_do_update(
                index_elements=[ArtworkRow.album_id], set_={"style_id": style_id}
            )
        )

    async def commit(self) -> None:
        await self._session.commit()
