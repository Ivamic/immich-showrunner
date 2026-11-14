# Installation

Showrunner runs with Docker Compose on the machine that holds the Immich library. The media
server (Jellyfin 12) must be able to read two folders: the Immich library and the output folder of
Showrunner. It may run in Docker or be installed as a system package.

The image is published on GitHub Container Registry (`ghcr.io/ivamic/immich-showrunner`) for
`amd64` and `arm64`. It can also be [built from the source](#building-from-source).

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
curl -L -o compose.yaml https://github.com/Ivamic/immich-showrunner/releases/latest/download/compose.yaml
curl -L -o example.env https://github.com/Ivamic/immich-showrunner/releases/latest/download/example.env
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
| `SHOWRUNNER_JELLYFIN_OUTPUT_PATH` | Only with Jellyfin in Docker: where its container sees the output folder |
| `DB_PASSWORD` | Any password of letters and digits for the app's own database |
| `SHOWRUNNER_SECRET_KEY` | At least 32 random characters, for signing in to the web page (see below) |
| `SHOWRUNNER_BIND` | `0.0.0.0` to open the web page to your home network; by default only this machine reaches it |

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
A video in a folder without a mapping is skipped and listed by `sync --dry-run` and on the
Status page.

### Other settings

`example.env` describes them all. The ones you may want to change:

| Setting | Default | What it is |
|---|---|---|
| `SHOWRUNNER_SHOW_PREFIX`, `SHOWRUNNER_PERSON_PREFIX` | `◈ ` | A short mark before the title of a show and the name of a person. The default skin of Kodi has no such character and shows a box; `• ` or `» ` work there |
| `SHOWRUNNER_TITLE_DATE_FORMAT` | `%Y-%m-%d %H:%M` | The title of a video without a description, e.g. `%d.%m.%Y, %H:%M` |
| `SHOWRUNNER_SYNC_INTERVAL_SECONDS` | `300` | Seconds between syncs; a full pass runs once an hour |
| `SHOWRUNNER_VERSION` | `0` | The version of the image; see [Updating](#updating) |

After changing a setting: `docker compose up -d`, then `docker compose run --rm app sync`, so that
every album is written again at once.

## 4. Check, try, start

```sh
docker compose run --rm app check            # settings, Immich, Jellyfin, folders
docker compose run --rm app sync --dry-run   # what would be created; nothing is written
docker compose up -d
```

## 5. The library in Jellyfin

Add a library (Dashboard → Libraries) of the content type **Shows** with the output folder, and
set it up like this:

| Setting | Value | Why |
|---|---|---|
| Enable real time monitoring | off | The app tells Jellyfin about every change itself; watching the folder only makes Jellyfin read a link before its NFO is there |
| Metadata downloaders (shows, seasons, episodes) | all off | Titles and everything else come from the NFO files |
| Automatically refresh metadata from the internet | Never | |
| Metadata savers: Nfo | off | Jellyfin would overwrite the NFO files of the app |
| Image fetchers (shows, seasons) | all off | |
| Image fetchers (episodes) | off, or only **Screen Grabber** | The app writes the preview of every video from Immich; Screen Grabber only fills in a picture that Immich could not give |
| Save artwork into media folders | off | The output folder belongs to the app |
| Automatically merge series that are spread across multiple folders | off | Two albums with the same name would become one show |
| Trickplay: save trickplay images next to media | off | Trickplay itself is up to you; it costs CPU time |
| Subtitle downloaders, save subtitles into media folders | off | |
| Prefer embedded titles over filenames, prefer embedded episode information | off | Phones write their own titles into videos |

Nothing of Jellyfin then lands in the output folder. Should something get there anyway, the app
leaves it alone: it removes only the files it created.

Run `docker compose run --rm app check` again: it tells whether Jellyfin has a library with the
output folder.

## 6. The web page

With `SHOWRUNNER_BIND=0.0.0.0` in `.env`, open `http://<your-server>:8790` from your home network
(without it, the page is reachable only on the server itself). Sign in as the Immich user of the
app (step 1), with its
Immich email and password. Only that user can sign in. The password is checked by Immich and not
stored; the app keeps its own Immich key, encrypted with `SHOWRUNNER_SECRET_KEY`, with just the
permissions to name people and accept invitations. The sync keeps reading with the read-only key.

Generate the secret with:

```sh
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

On the page:

- **Albums**: every shared album, as it will be a show in Jellyfin. Give a show its own title,
  one season instead of a season per year of filming, or leave it out of Jellyfin. Rename the
  episodes, give them a description, move them up and down within their season, or hide them.
  Every change reaches Jellyfin within a minute, and can be reset to what Immich says.
- **People**: the people shared with the user of the app (see below), their names for Jellyfin and
  their descriptions.
- **Status**: the last sync, what it could not do, and a button to sync now.

If Immich signs in only through OAuth, sign in with an API key of the user of the app instead.
To name people from the page, that key needs `person.update`, `clusterGroup.read`,
`clusterGroupRequest.read` and `clusterGroupRequest.create`.

## 7. People

People in Immich belong to the owner of the videos. To have them in Jellyfin under names of their
own ("Mum" can stay "Mum" in the owner's library):

1. The owner invites the user of the app into their group: Account Settings → Sharing.
2. On the People page of Showrunner, accept the invitation.
3. The owner shares people with the user of the app: People → a person → Manage access.
4. On the People page, give each of them a name for Jellyfin. The name is written to Immich for the
   user of the app only.

A person without such a name is not in Jellyfin. People appear with the prefix
(`SHOWRUNNER_PERSON_PREFIX`), with their face from Immich, and are locked in Jellyfin, so that it
does not fill them in with a namesake from TMDB.

> **One group only.** An Immich user is in one group at a time. Accepting the invitation of
> another group takes the user of the app out of the current one, and the people shared there are
> lost for Jellyfin; in our tests they did not come back by joining again. All owners whose people
> should be in Jellyfin have to be in the same group. The page accepts an invitation only while the
> user of the app is alone in its group.

## Updating

```sh
docker compose pull
docker compose up -d
```

`compose.yaml` pulls the newest release of the major version (`0` for now), so these two commands
are all an update needs; the database is brought to the new version when the app starts. To stay
on one version, set `SHOWRUNNER_VERSION=0.1.0` in `.env`. Read the release notes before an update:
they say when anything else is needed.

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
  Watched marks survive renaming, new videos in the middle of an album, episodes moved on the
  page, and an album that was unshared and shared again. Switching a show between seasons by year
  and one season numbers its episodes anew, and their watched marks may be lost.

## When something does not work

| What you see | What to do |
|---|---|
| `check` says FAIL for Immich | The address must be reachable from the app container: a LAN address, not `localhost`. The key needs the five permissions of step 1 |
| `sync --dry-run` lists videos as `no_path_mapping` | The left side of `SHOWRUNNER_PATH_MAP` is not where Immich keeps them: `docker inspect immich_server` shows its mounts |
| The show is in Jellyfin, but a video does not play | The media server can not read the file behind the link. With Jellyfin as a package: `sudo -u jellyfin head -c 16 <a link>`; if that fails, `namei -l` on the target shows the folder without read rights |
| The last show stays in Jellyfin after its album is unshared | Fixed since 0.1.0 (the app keeps a hidden file `.showrunner` in the output folder; do not delete it). Run a library scan in Jellyfin once |
| Changes do not reach Jellyfin | `SHOWRUNNER_JELLYFIN_URL` and `_API_KEY`; while Jellyfin is down the app keeps trying, see `jellyfin_pending` on the Status page |
| The page says "Signing in is not set up" | Set `SHOWRUNNER_SECRET_KEY` in `.env` and run `docker compose up -d` |
| People do not appear in Jellyfin | They need a name on the People page; see [People](#7-people) |

## Building from source

```sh
git clone https://github.com/Ivamic/immich-showrunner.git
cd immich-showrunner
cp .env.example .env      # then set the values as above
docker compose -f compose.yaml -f compose.build.yaml build
docker compose -f compose.yaml -f compose.build.yaml run --rm app check
docker compose -f compose.yaml -f compose.build.yaml up -d
```
