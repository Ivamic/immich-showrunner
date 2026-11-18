# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/). While the version is 0.x, anything may change
between releases.

## [Unreleased]

### Added

- **Artwork styles** (groundwork, not used by the sync yet): a style is a folder with a declarative
  `style.yaml`, its fonts and pictures. A renderer draws from it, out of video frames and the
  title, the poster, landscape picture, backdrop and logo of a show and the poster of a season.
  The first style, Mosaic, ships with the app.
- **Frames for artwork** (groundwork): frames are read from a video over HTTP without fetching
  the whole file, scored for sharpness, exposure, contrast and color, searched for faces (YuNet,
  on the CPU) and cropped to keep the faces whole. The best frames, unlike each other and from
  different videos, are chosen first.
- **Five more artwork styles**: Polaroid, Film, Playbill, Watercolor and Pinboard, next to Mosaic.
  Styles can now strew prints at random (from a seed), pin and tape them, put film strips and other
  decor under or over the frames, darken the edges, space and turn the title and lay it on paper
  with a torn edge.
- **Three more artwork styles**: Diamonds, Diagonals and Editorial.
- **Faces stay clear of the title**: a frame under the title is cropped so that the faces land in
  the part the title leaves free, enlarged a little when it cannot be moved enough.
  The same is done for the part of a slanted, round or diamond frame that is wholly seen.
- **Shows get drawn pictures** (on by default; `SHOWRUNNER_ARTWORK=false` turns them off): the poster,
  landscape picture, backdrop and logo of a show and a poster for every season, drawn from frames
  of the album's videos in a style chosen for the album. New videos are looked at in the background
  of the syncs, at most `SHOWRUNNER_ARTWORK_BUDGET_SECONDS` (240) per sync; until a show has frames
  it keeps the cover of its album. A picture is drawn again only when what it is made of changes.
  Kodi gets the posters of seasons through the NFO of the show, and forgets its cached pictures of a
  changed show.
- **In the Jellyfin folder the drawn poster is `folder.jpg`** (the cover of the album stays
  `poster.jpg`): Jellyfin keeps the size of a picture by its path, so a 2:3 poster written over a
  16:9 cover would be shown cut to 16:9.
- **`asset.download`** for the Immich API key is recommended: the frames are then read from the
  original videos. Without it they come from the videos Immich converted for playing.

### Fixed

- **An album with a date in its name** (`2026-06_07 - Trip`) became one episode with every video as
  a version of it: Jellyfin reads a date with separators anywhere in the path of an episode, the
  folder of the show too. Folders of shows now write dates without separators, as file names
  already did; an existing folder with such a date is renamed once (the database migration does
  it, the next sync moves the files), and Jellyfin and Kodi are made to find the show in its new
  folder. Watched marks of such a show start anew in Kodi, and in Jellyfin if it keeps them by path.


## [0.2.1] - 2026-11-15

### Fixed

- **Episodes on the Albums page** were counted twice when both Jellyfin and Kodi have a folder: the
  page counted the links of both. The videos are counted now. The sync itself was not affected.

### Added

- Screenshots of Jellyfin, Kodi and the web page in the READMEs.

### Security

- Dependencies that ship checked again: no known vulnerabilities.

## [0.2.0] - 2026-11-15

### Added

- **Kodi.** A folder of its own for Kodi 21 with "Local information only", next to the Jellyfin
  one or instead of it (`SHOWRUNNER_KODI_OUTPUT_LOCATION`), shared over SMB. Files are named by the
  time of filming (`2024-07-15 143211 [1898906754].mp4`), the season and the number are in the NFO,
  so watched marks stay when a video is filmed between two others. The faces of people come from
  Immich. With `SHOWRUNNER_KODI_URL` the app tells Kodi about every change over JSON-RPC, and keeps
  the changes while Kodi is off (`kodi_pending`). `check` reaches Kodi and its folder.

### Changed

- **Jellyfin is optional**: the app needs a folder for Jellyfin, for Kodi, or both. Immich is read
  once per pass for all of them.
- **The Jellyfin folder** is set with `SHOWRUNNER_JELLYFIN_OUTPUT_LOCATION` (and
  `SHOWRUNNER_JELLYFIN_OUTPUT_DIR` outside compose.yaml). The old names `SHOWRUNNER_OUTPUT_LOCATION`
  and `SHOWRUNNER_OUTPUT_DIR` still work when the new ones are not set.
- `/api/health` and the Status page show the targets and the queue of each media server.
- **The web page speaks of the media server**, not of Jellyfin: the same words fit Jellyfin, Kodi or
  both. The description of a person says that only Jellyfin shows it.
- **A quieter log**: requests that only read and succeed (the files of the page, the status it asks
  for every few seconds) are no longer logged; changes and errors are.
- The app waits at most 5 seconds for Kodi to answer, so that a TV box that is off does not hold up
  the sync.

### Fixed

- **A disk that is not mounted.** An output folder that has lost its hidden `.showrunner` file
  while the app has files there is left alone, with "is the disk mounted?" on the Status page:
  before, the app wrote into the empty mount point, on another disk.

### Security

- Dependencies that ship checked again: no known vulnerabilities. The build tools of the web page
  still have the two findings of 0.1.0, which do not reach the image.

## [0.1.1] - 2026-11-14

### Changed

- **Pictures when Immich makes WebP previews.** Such previews are now turned into JPEG, so
  posters and pictures of episodes are there without changing the preview format of Immich.
  JPEG previews are written as before, byte for byte.
- **Default marks** are now `§ ` before the title of a show and `• ` before the name of a person
  (were `◈ ` for both): the default skin of Kodi has no `◈` and showed a box. A mark you set in
  `.env` stays as it is.

### Security

- Dependencies that ship checked again, with Pillow added: no known vulnerabilities. The build
  tools of the web page still have the two findings of 0.1.0, which do not reach the image.

## [0.1.0] - 2026-11-14

The first release.

### Added

- **Albums as shows.** Every album shared with the Immich user of the app becomes a show in the
  output folder: a link per video and NFO files with the titles, for a Jellyfin library of the type
  "Shows". Seasons are the years of filming, episodes are numbered in the order of filming.
- **Titles.** The first line of a video's description is its title, the rest is the plot; without
  a description the title is the time of filming. With an own title given on the page, the whole
  description is the plot.
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
- **Web page**, signed in to as the Immich user of the app: albums as they will be shows, with
  their own titles, seasons, and episodes renamed, described, moved or hidden; people with names
  and descriptions for Jellyfin, and the invitations into a group in Immich; the status of the
  sync with a button to sync now. In English, German, French, Italian and Russian, light and dark.
- **Commands**: `sync`, `sync --dry-run`, `check`, `migrate`, and `serve` with `GET /api/health`.
- **Safety.** The app writes only to its output folder and removes only what it created; a file
  changed by hand is left alone. Nothing is removed when Immich does not answer, and a sync that
  would remove most of the links is held until it is forced.
- Docker image for `amd64` and `arm64` on ghcr.io, `compose.yaml` and an example `.env`;
  [installation](docs/install.md). README in English, German, French, Italian and Russian.

### Security

- Before every release the dependencies that ship are checked for known vulnerabilities; the
  release workflow stops on a finding. For 0.1.0: none in the Python packages and none in what
  the web page ships. The build tools of the page have two (moderate, low), which do not reach
  the image.
