# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/). While the version is 0.x, anything may change
between releases.

## [Unreleased]

### Added

- **Albums as shows.** Every album shared with the Immich user of the app becomes a show in the
  output folder: a link per video and NFO files with the titles, for a Jellyfin library of the type
  "Shows". Seasons are the years of filming, episodes are numbered in the order of filming.
- **Titles.** The first line of a video's description is its title, the rest is the plot; without
  a description the title is the time of filming.
- **Sync on a schedule**, a quick pass that leaves unchanged albums alone and a full pass every
  hour. Jellyfin is told about every change through its API; when Jellyfin is down, the app
  keeps trying on every pass until it answers (`jellyfin_pending` in `/api/health`).
- **Pictures from Immich.** The cover of the album becomes the poster of the show, and the preview
  of every video the picture of its episode: the same pictures as in Immich. A picture is
  downloaded only when it is new or changed in Immich, and one you replaced by hand stays.
- **People.** The people on a video are the cast of its episode, under the names the Immich
  user of the app gave them, marked with the prefix. Jellyfin looks every new person up on
  TMDB; the app removes what it found there for a namesake, sets the face from Immich and
  locks the person. People of your other libraries are never touched.
- **Commands**: `sync`, `sync --dry-run`, `check`, `migrate`, and `serve` with `GET /api/health`.
- **Safety.** The app writes only to its output folder and removes only what it created; a file
  changed by hand is left alone. Nothing is removed when Immich does not answer, and a sync that
  would remove most of the links is held until it is forced.
- Docker image, `compose.yaml` and an example `.env`; [installation](docs/install.md).
