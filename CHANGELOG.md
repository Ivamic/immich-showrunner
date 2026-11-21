# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/). While the version is 0.x, anything may change
between releases.

## [Unreleased]

### Added

- **Slideshows of the photos** (off until switched on on the new Slideshows page): the photos of an
  album become videos with music, one for each year ("Photos 2024", parts of 3 to 5 minutes of whole
  days for a long year, at most half an hour a year; for an album of one season, all its years
  together, "Photos 2019–2024"), among the specials (Season 0) of its show, placed after the episodes of their year in
  Jellyfin and Kodi. An album of photos only becomes a show of slideshows only.
- **A cut list made with care**: the photos in the order they were taken, cut into scenes by pauses
  and moves; near copies become their best photo; a day gives all of a few photos, else about twice
  the square root of them (a busy day more, but not all), shared among its scenes; screenshots, documents and receipts are left out
  by a CLIP image model (OpenCLIP ViT-B/32, MIT, downloaded on first use, run by OpenCV on the CPU).
  The camera moves slowly towards the faces (or what draws the eye), a standing photo is shown
  whole over a blurred copy of itself, a panorama is travelled along; dissolves within a scene,
  fades through black between scenes; the title and the credits in the style of the album.
- **Music**: a set of 28 free pieces (Kevin MacLeod, CC BY 4.0; Chopin recorded for Musopen, CC0;
  Jason Shaw, CC BY 3.0 US), downloaded on first use from a release of this project, and your own
  pieces, added on the page with an optional title, author, licence, link and mood. Every piece is
  looked at once (loudness by EBU R128, tempo, beats, bars, parts, key); the photos change on the
  beats, a scene on the first beat of a bar, and a slideshow ends at the end of a phrase. The mood of
  the music follows what the photos show (calm, bright, upbeat; wistful and solemn by choice). The
  music is named in the description of every slideshow and in its end credits
  (`SHOWRUNNER_SLIDESHOW_CREDITS`, or on the page).
- **On the page of an album**: slideshows off for this album, the mood of its music, "Other music",
  and its slideshows with their state, to watch on the page or download under the name of the show.
  Why photos were left out (near copies, over the share of a day, screenshots and documents, poor
  quality), in all and day by day. The cards of the albums count their slideshows.
- **The slideshow being drawn** is shown on the page: which one, how far, and how many wait.
- **A trash for slideshows**: a slideshow drawn again or removed is kept for
  `SHOWRUNNER_SLIDESHOW_TRASH_DAYS` (90) days in `.trash` in the folder of slideshows (in the data
  volume without one), listed on the page of its album to download, then deleted.
- **A folder for the slideshows** (`SHOWRUNNER_SLIDESHOW_LOCATION`, optional): the output folders then
  get links to them, one file for Jellyfin and Kodi alike; without it each output folder gets a copy.
- **Drawn in the background**: photos are looked at within `SHOWRUNNER_SLIDESHOW_BUDGET_SECONDS`
  (240) per sync and slideshows drawn within `SHOWRUNNER_SLIDESHOW_RENDER_BUDGET_SECONDS` (600), the
  newest years first, on `SHOWRUNNER_SLIDESHOW_THREADS` (2) threads, in a process of their own. A
  slideshow keeps its file name and is drawn again only when its photos, music or style change; the
  one drawn before stays in the library meanwhile, with its watched mark.
- **The albums page** shows the picture the app drew for each show, or its cover in Immich.

### Changed

- **A volume for the app's own data** (`/data`, `app-data` in `compose.yaml`): the downloaded model and
  music, your music, and the work of drawing.
- **The database changes** (migrations 0013–0015): what was learned about the photos, the choices for
  the slideshows and the music switched off.

### Fixed

- **Cards of the albums line up**: a tall cover no longer stretches its card.
- **A walk of alike photos is no longer one series** (0.4.0-rc.1): each photo was compared with the
  one before it, so a day of slowly changing views became a single photo; now it is compared with
  the first of the series.
- **A choice for an album no longer waits for the drawing** (0.4.0-rc.1): saving the mood or "Other
  music" while slideshows were drawn hung until the end of the sync.

### Security

- No new dependency: slideshows are drawn with OpenCV, NumPy, Pillow and PyAV, already in the image.
- The dependencies that ship were checked for known vulnerabilities before the release: none found
  (a moderate one in `minimatch` is only in the tools that build the page, not in the image).

## [0.3.0] - 2026-11-18

### Added

- **Drawn pictures for every show** (on by default; `SHOWRUNNER_ARTWORK=false` turns them off): the
  poster, landscape picture, backdrop and logo of a show and a poster for every season, drawn from
  frames of the album's videos. No AI image generation: everything runs on the CPU.
- **Frames chosen with care**: a few frames are read from every video over HTTP, without fetching
  the whole file, scored for sharpness, exposure, contrast and color, and searched for faces
  (YuNet). The best frames, unlike each other and from different videos, come first; they are
  cropped to keep the faces whole and clear of the title and of slanted, round or diamond edges.
- **Nine styles**: Mosaic, Polaroid, Film, Playbill, Watercolor, Pinboard, Diamonds, Diagonals and
  Editorial. A style is chosen for each album at random and kept. A style is a folder with a
  declarative `style.yaml`, its fonts and pictures.
- **Drawn once**: new videos are looked at in the background of the syncs, at most
  `SHOWRUNNER_ARTWORK_BUDGET_SECONDS` (240) per sync, so a large library gets its pictures over a
  few syncs; until a show has frames it keeps the cover of its album. A picture is drawn again only
  when what it is made of changes. Looking at videos and drawing run in a process of their own, so
  the page stays free meanwhile.
- **Pictures on the page of an album**: the pictures the media servers have now; "Another style",
  a style chosen by name, "Other frames" for all the pictures or for one, and "Album cover as the
  poster", each shown side by side with the pictures of now before it is applied. A picture can be
  pinned (or all of them), and then stays as it is whatever happens to the album. The page shows
  when pictures are being drawn and how many videos are still to look at.
- **A Styles page**: switch styles on or off; albums in a style switched off get another one.
- **Kodi** gets the posters of the seasons through the NFO of the show, and forgets the pictures it
  cached for a changed show, so a new picture shows at once.
- **`asset.download`** for the Immich API key is recommended: the frames are then read from the
  original videos. Without it they come from the videos Immich converted for playing; `check` tells
  which.

### Changed

- **In the Jellyfin folder the drawn poster is `folder.jpg`**; the cover of the album, when it is
  used, stays `poster.jpg`. Jellyfin keeps the size of a picture by its path, and would show a 2:3
  poster written over a 16:9 cover cut to 16:9.
- **The image is larger** (about 600 MB instead of 230 MB): it holds the libraries that read videos
  and find faces.
- **The database changes** (migrations 0009–0012): it keeps what was learned about the frames, the
  style and the choices of each album. Going back to 0.2 needs a copy made before the update.

### Fixed

- **An album with a date in its name** (`2026-06_07 - Trip`) became one episode with every video as
  a version of it: Jellyfin reads a date with separators anywhere in the path of an episode, the
  folder of the show too. Folders of shows now write dates without separators, as file names
  already did; an existing folder with such a date is renamed once (the database migration does
  it, the next sync moves the files), and Jellyfin and Kodi are made to find the show in its new
  folder. Watched marks of such a show start anew in Kodi, and in Jellyfin if it keeps them by path.
- **Moving folders is not a mass removal**: links that move to a new folder for the same videos are
  no longer counted as removed. A real loss of most links still holds the sync.

### Security

- The dependencies that ship were checked for known vulnerabilities before the release: none found.

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
