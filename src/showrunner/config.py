# SPDX-License-Identifier: AGPL-3.0-or-later
"""Application settings, read from environment variables with the ``SHOWRUNNER_`` prefix."""

from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import NamedTuple

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_PREFIX = "SHOWRUNNER_"
MIN_SECRET_KEY_LENGTH = 32


class PathMapping(NamedTuple):
    """A folder as Immich reports it and the same folder as the media server sees it."""

    source: PurePosixPath
    target: PurePosixPath


def parse_path_map(value: str) -> tuple[PathMapping, ...]:
    """Parse ``/data=/srv/immich;/mnt/ext=/srv/ext`` into mappings, longest source first.

    Both sides must be absolute POSIX paths: links are created for a Linux media server."""
    mappings: list[PathMapping] = []
    for raw in value.split(";"):
        part = raw.strip()
        if not part:
            continue
        source, sep, target = part.partition("=")
        if not sep:
            raise ValueError(f"path mapping {part!r} must look like /from=/to")
        pair = PathMapping(PurePosixPath(source.strip()), PurePosixPath(target.strip()))
        for side in pair:
            if not side.is_absolute() or ".." in side.parts:
                raise ValueError(f"path {str(side)!r} in a path mapping must be absolute")
        mappings.append(pair)
    return tuple(sorted(mappings, key=lambda m: len(m.source.parts), reverse=True))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix=ENV_PREFIX, env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://showrunner:showrunner@localhost:5432/showrunner"

    # Immich: the server and the API key of the user that albums are shared with.
    immich_url: str
    immich_api_key: SecretStr

    # The folders of links and metadata that the media servers scan, one per target; the app
    # writes only there. At least one is needed. SHOWRUNNER_OUTPUT_DIR is the name the Jellyfin
    # folder had before 0.2 and is read when SHOWRUNNER_JELLYFIN_OUTPUT_DIR is not set.
    jellyfin_output_dir: Path | None = None
    output_dir: Path | None = None
    kodi_output_dir: Path | None = None

    # Where the media server sees the folders of the Immich library, as `/from=/to` pairs
    # separated by `;`. A video in a folder without a mapping is skipped.
    path_map: str = ""

    # Jellyfin: the server, an API key (Dashboard, API keys) and the output folder as Jellyfin
    # sees it, when that differs from SHOWRUNNER_JELLYFIN_OUTPUT_DIR. Without a URL and a key the
    # app only writes the folder, and changes show up in Jellyfin late or not at all.
    jellyfin_url: str = ""
    jellyfin_api_key: SecretStr = SecretStr("")
    jellyfin_output_path: str = ""

    # Kodi: its address with the web server on (Settings, Services, Control), the user name and
    # password set there, and the output folder as Kodi sees it, usually a network share such as
    # `smb://server/share/kodi`. Without a URL the app only writes the folder, and Kodi shows
    # changes only after an update of its library, changed titles not at all.
    kodi_url: str = ""
    kodi_username: str = "kodi"
    kodi_password: SecretStr = SecretStr("")
    kodi_output_path: str = ""

    # A short mark before the title of a show and before the name of a person. Empty: no mark.
    # Both are in the fonts of every client, Kodi included.
    show_prefix: str = "§ "
    person_prefix: str = "• "

    # The first line of a video description is its title when it is not longer than this.
    title_max_length: int = Field(default=80, ge=1)

    # The title of a video without a usable description: its time of filming in this strftime
    # format.
    title_date_format: str = "%Y-%m-%d %H:%M"

    sync_interval_seconds: int = Field(default=300, ge=30)
    # Pictures drawn from the frames of the videos: poster, landscape, backdrop and logo of a
    # show, poster of a season. Off: the poster is the cover of the album, as before.
    artwork: bool = True
    # Time a pass may spend looking at new videos for artwork; the rest waits for the next one.
    artwork_budget_seconds: int = Field(default=240, ge=10)
    # Slideshows of the photos of an album (in the making: so far its photos are only looked at).
    slideshow: bool = False
    # Time a pass may spend looking at new photos; the rest waits for the next one.
    slideshow_budget_seconds: int = Field(default=240, ge=10)

    # The web page. The secret encrypts the Immich key the app keeps for what the user does on the
    # page; changing it signs everybody out. Without it the page can not be signed in to.
    secret_key: SecretStr | None = None
    session_ttl_days: int = Field(default=90, ge=1)
    # Set when the page is served over HTTPS (a reverse proxy).
    cookie_secure: bool = False
    # The built web page; without it only the API is served.
    static_dir: Path | None = None

    @field_validator("immich_url")
    @classmethod
    def _check_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        if not value.startswith(("http://", "https://")):
            raise ValueError("must start with http:// or https://")
        return value

    @field_validator("secret_key")
    @classmethod
    def _check_secret(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None or not value.get_secret_value():
            return None
        if len(value.get_secret_value()) < MIN_SECRET_KEY_LENGTH:
            raise ValueError(f"must be at least {MIN_SECRET_KEY_LENGTH} characters long")
        return value

    @field_validator("jellyfin_output_dir", "output_dir", "kodi_output_dir", mode="before")
    @classmethod
    def _empty_is_none(cls, value: object) -> object:
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("path_map")
    @classmethod
    def _check_path_map(cls, value: str) -> str:
        parse_path_map(value)
        return value

    @property
    def jellyfin_dir(self) -> Path | None:
        """The output folder for Jellyfin, under its name or the name it had before."""
        return self.jellyfin_output_dir or self.output_dir

    @property
    def path_mappings(self) -> tuple[PathMapping, ...]:
        return parse_path_map(self.path_map)


@lru_cache
def get_settings() -> Settings:
    return Settings()  # required values come from the environment
