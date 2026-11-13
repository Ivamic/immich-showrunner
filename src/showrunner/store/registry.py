# SPDX-License-Identifier: AGPL-3.0-or-later
"""The registry: which shows there are and which files the app created for them."""

from collections.abc import Collection
from datetime import datetime
from pathlib import PurePosixPath
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from showrunner.model.naming import show_folder_name
from showrunner.store.models import FileRow, ShowRow
from showrunner.sync.plan import Entry
from showrunner.targets.base import DesiredFile, FileKind


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

    async def entries(self) -> list[Entry]:
        rows = await self._session.scalars(select(FileRow).order_by(FileRow.path))
        return [
            Entry(
                path=PurePosixPath(row.path),
                kind=FileKind(row.kind),
                album_id=row.album_id,
                asset_id=row.asset_id,
                link_target=PurePosixPath(row.link_target) if row.link_target else None,
                content_hash=row.content_hash,
            )
            for row in rows
        ]

    async def record(self, file: DesiredFile) -> None:
        """Remember that `file` now exists as described."""
        values = {
            "kind": file.kind.value,
            "album_id": file.album_id,
            "asset_id": file.asset_id,
            "link_target": str(file.link_target) if file.link_target else None,
            "content_hash": file.content_hash,
        }
        statement = insert(FileRow).values(path=str(file.path), **values)
        await self._session.execute(
            statement.on_conflict_do_update(
                index_elements=[FileRow.path],
                set_={**values, "updated_at": statement.excluded.updated_at},
            )
        )

    async def forget(self, path: PurePosixPath) -> None:
        await self._session.execute(delete(FileRow).where(FileRow.path == str(path)))

    async def set_stamps(
        self, album_id: UUID, album_updated_at: datetime | None, assets_modified_at: datetime | None
    ) -> None:
        row = await self._session.get(ShowRow, album_id)
        if row is not None:
            row.album_updated_at = album_updated_at
            row.assets_modified_at = assets_modified_at

    async def mark_pending(self, album_ids: Collection[UUID]) -> None:
        """The media server has to be told about these shows."""
        if album_ids:
            await self._session.execute(
                update(ShowRow)
                .where(ShowRow.album_id.in_(list(album_ids)))
                .values(media_server_pending=True)
            )

    async def pending(self) -> set[UUID]:
        rows = await self._session.scalars(
            select(ShowRow.album_id).where(ShowRow.media_server_pending)
        )
        return set(rows)

    async def clear_pending(self, album_ids: Collection[UUID]) -> None:
        if album_ids:
            await self._session.execute(
                update(ShowRow)
                .where(ShowRow.album_id.in_(list(album_ids)))
                .values(media_server_pending=False)
            )

    async def commit(self) -> None:
        await self._session.commit()
