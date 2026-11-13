# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tables."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, MetaData, String, Text, false, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Names for constraints, so that migrations can refer to them.
NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


class ShowRow(Base):
    """An album that is or was a show. The row stays when the album is no longer shared: if it is
    shared again, the show comes back in the same folder and with the same settings."""

    __tablename__ = "show"

    album_id: Mapped[UUID] = mapped_column(primary_key=True)
    # Set once; renaming the album does not change it.
    folder_name: Mapped[str] = mapped_column(Text, unique=True)
    season_mode: Mapped[str] = mapped_column(String(16), default="year", server_default="year")
    # What the album looked like when its files were last brought in line; both unchanged means
    # that a quick sync may leave the album alone.
    album_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    assets_modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The files of the show changed and the media server has not yet confirmed that it knows.
    # Set together with the files, cleared only after the media server answered.
    media_server_pending: Mapped[bool] = mapped_column(default=False, server_default=false())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PersonRow(Base):
    """A person the app wrote into metadata, by the name the media server knows: its face in
    Immich is found through it, also on a pass that did not read the album again."""

    __tablename__ = "person"

    name: Mapped[str] = mapped_column(Text, primary_key=True)
    immich_id: Mapped[UUID] = mapped_column()
    seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class FileRow(Base):
    """A file the app created in the output folder. Only what is listed here is ever removed."""

    __tablename__ = "file"

    # Relative to the output folder, with forward slashes.
    path: Mapped[str] = mapped_column(Text, primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))
    album_id: Mapped[UUID] = mapped_column(ForeignKey("show.album_id"), index=True)
    asset_id: Mapped[UUID | None] = mapped_column()
    link_target: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    # For a picture: the version of the Immich picture it holds.
    source_version: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
