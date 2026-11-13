# Installation

Showrunner runs with Docker Compose on the machine that holds the Immich library. The media
server (Jellyfin 12) must be able to read two folders: the Immich library and the output folder of
Showrunner. It may run in Docker or be installed as a system package.

> There is no released image yet. Until the first release, build the image from the source:
> see [Building from source](#building-from-source).

## 1. A user in Immich

1. As the Immich administrator, create a user for the media server, for example `jellyfin`.
2. Sign in as that user and create an API key (Account Settings → API Keys) with only these
   permissions: `album.read`, `asset.read`, `asset.view`, `person.read`, `user.read`.
   With such a key the app can not change anything in Immich.
3. Share an album with that user. Every video of the album becomes an episode.

## 2. The output folder

Create an empty folder for the links and metadata, for example `/srv/showrunner`. The app writes
only there. It must be on the machine where the media server can read both this folder and the
Immich library.

## 3. Settings

```sh
mkdir immich-showrunner && cd immich-showrunner
# compose.yaml and example.env come from the release (or from the source tree)
cp example.env .env
```

Set in `.env`:

| Setting | What it is |
|---|---|
| `SHOWRUNNER_IMMICH_URL` | Address of Immich as seen from this machine, e.g. `http://192.0.2.10:2283` (not `localhost`) |
| `SHOWRUNNER_IMMICH_API_KEY` | The API key from step 1 |
| `SHOWRUNNER_OUTPUT_LOCATION` | The output folder from step 2 |
| `SHOWRUNNER_PATH_MAP` | Where the media server sees the Immich library, see below |
| `PUID`, `PGID` | Owner of the created files; the media server must be able to read them |
| `SHOWRUNNER_JELLYFIN_URL`, `SHOWRUNNER_JELLYFIN_API_KEY` | Address of Jellyfin and an API key (Dashboard → API Keys) |
| `DB_PASSWORD` | Any password of letters and digits for the app's own database |

### The path mapping

Immich reports the path of a video as it is inside its container, for example
`/data/upload/…/video.mp4`. The media server sees the same file somewhere else.
`SHOWRUNNER_PATH_MAP` tells the app how to translate: `/path-in-Immich=/path-for-the-media-server`.

- The left side is the folder inside the Immich container: `/data` since Immich 3 (the
  `UPLOAD_LOCATION` of Immich is mounted there).
- The right side is the same folder as the media server sees it. With Jellyfin installed as a
  package, that is the folder on the host: the value of `UPLOAD_LOCATION`. With Jellyfin in
  Docker, it is the path where you mount the Immich library into the Jellyfin container
  (read-only is enough).

Example: Immich has `UPLOAD_LOCATION=/srv/immich/library`, Jellyfin is a system package:

```
SHOWRUNNER_PATH_MAP=/data=/srv/immich/library
```

External libraries of Immich have their own paths; add a pair for each, separated by `;`.
A video in a folder without a mapping is skipped and listed by `sync --dry-run`.

## 4. Check, try, start

```sh
docker compose run --rm app check            # settings, Immich, Jellyfin, folders
docker compose run --rm app sync --dry-run   # what would be created; nothing is written
docker compose up -d
```

## 5. The library in Jellyfin

Add a library (Dashboard → Libraries):

- Content type: **Shows**; folder: the output folder.
- Turn off every metadata downloader for shows, seasons and episodes, and every image fetcher
  that downloads from the internet; keep **Nfo** as the metadata reader.
- For episodes, keep the image fetcher **Screen Grabber**: it takes a frame of the video for the
  picture of the episode. Jellyfin keeps that picture in its own data folder, not next to the
  links.
- Turn off "Save artwork into media folders" and the NFO metadata saver: the output folder
  belongs to the app.

Run `docker compose run --rm app check` again: it tells whether Jellyfin has a library with the
output folder.

## Commands

```sh
docker compose run --rm app sync             # one full pass now
docker compose run --rm app sync --dry-run   # show what would change
docker compose run --rm app sync --force     # carry out a held mass removal
docker compose run --rm app check
```

A sync that would remove more than half of all links (and more than 20) is **held**: that looks
like a wrong API key, not like albums that are no longer shared. Nothing is changed until you run
the sync with `--force`.

`http://127.0.0.1:8790/api/health` shows the time and the result of the last sync.

## What the app will and will not do

- It writes only to the output folder, and removes there only what it created. A file you put
  there or changed by hand is left alone.
- It never opens, changes, moves or removes a file of the Immich library; the library is not even
  mounted into its container.
- When Immich does not answer, nothing is removed.
- The folder of a show keeps its name when the album is renamed; the title changes in Jellyfin.
  Watched marks survive renaming, new videos in the middle of an album, and an album that was
  unshared and shared again.

## Building from source

```sh
git clone https://github.com/Ivamic/immich-showrunner.git
cd immich-showrunner
cp .env.example .env      # then set the values as above
docker compose -f compose.yaml -f compose.build.yaml build
docker compose -f compose.yaml -f compose.build.yaml run --rm app check
docker compose -f compose.yaml -f compose.build.yaml up -d
```
