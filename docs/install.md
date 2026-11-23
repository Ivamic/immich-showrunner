# Installation

Showrunner runs with Docker Compose on the machine that holds the Immich library. It writes a
folder for Jellyfin 12, a folder for Kodi 21, or both. Jellyfin may run in Docker or be installed
as a system package on the same machine, and must be able to read two folders: the Immich library
and its output folder. Kodi runs anywhere on the home network and reads its folder over SMB.

Kodi with the Jellyfin add-on needs no folder of its own: it shows what Jellyfin has.

The image is published on GitHub Container Registry (`ghcr.io/ivamic/immich-showrunner`) for
`amd64` and `arm64`. It can also be [built from the source](#building-from-source).

## 1. A user in Immich

1. As the Immich administrator, create a user for the media server, for example `jellyfin`.
2. Sign in as that user and create an API key (Account Settings → API Keys) with only these
   permissions: `album.read`, `asset.read`, `asset.view`, `asset.download`, `person.read`,
   `user.read`. With such a key the app can not change anything in Immich. `asset.download`
   lets the app read the original videos for the frames of its pictures; without it the frames
   come from the smaller videos Immich converted for playing.
3. Share an album with that user. Every video of the album becomes an episode.

## 2. The output folders

Create an empty folder for the links and metadata of each media server, for example
`/srv/showrunner/jellyfin` and `/srv/showrunner/kodi`. The app writes only there. Jellyfin and
Kodi need different file names, so each has a folder of its own; do not put one inside the other. The
folders may be on other disks than the Immich library; links work across disks. If a disk with an
output folder is not mounted, the app finds the empty folder under it without its hidden file
`.showrunner`, writes nothing there and says so on the Status page.

For [slideshows](#9-slideshows) you may also create a folder for the videos the app draws, for example
`/srv/showrunner/slideshows`: the output folders then get links to them, one file for Jellyfin and
Kodi alike. Without it, each output folder gets a copy of every slideshow.

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
| `SHOWRUNNER_PATH_MAP` | Where the media server sees the Immich library, see below |
| `PUID`, `PGID` | Owner of the created files; the media server must be able to read them |
| `DB_PASSWORD` | Any password of letters and digits for the app's own database |
| `SHOWRUNNER_SECRET_KEY` | At least 32 random characters, for signing in to the web page (see below) |
| `SHOWRUNNER_BIND` | `0.0.0.0` to open the web page to your home network; by default only this machine reaches it |

For Jellyfin:

| Setting | What it is |
|---|---|
| `SHOWRUNNER_JELLYFIN_OUTPUT_LOCATION` | The Jellyfin folder from step 2. Called `SHOWRUNNER_OUTPUT_LOCATION` before 0.2; that name still works |
| `SHOWRUNNER_JELLYFIN_URL`, `SHOWRUNNER_JELLYFIN_API_KEY` | Address of Jellyfin and an API key (Dashboard → API Keys) |
| `SHOWRUNNER_JELLYFIN_OUTPUT_PATH` | Only with Jellyfin in Docker: where its container sees the folder |

For Kodi (see [The library in Kodi](#6-the-library-in-kodi)):

| Setting | What it is |
|---|---|
| `SHOWRUNNER_KODI_OUTPUT_LOCATION` | The Kodi folder from step 2 |
| `SHOWRUNNER_KODI_URL` | Address of the web server of Kodi, e.g. `http://192.0.2.20:8080` |
| `SHOWRUNNER_KODI_USERNAME`, `SHOWRUNNER_KODI_PASSWORD` | The user name and password set for that web server in Kodi |
| `SHOWRUNNER_KODI_OUTPUT_PATH` | The folder as Kodi sees it: the path of the source in Kodi, e.g. `smb://192.0.2.10/showrunner-kodi` |

Without a URL the app still writes the folder, and the media server shows the changes only after
a scan of its library (changed titles not at all).

### The path mapping

Immich reports the path of a video as it is inside its container, for example
`/data/upload/…/video.mp4`. The media server sees the same file somewhere else.
`SHOWRUNNER_PATH_MAP` tells the app how to translate: `/path-in-Immich=/path-for-the-media-server`.

- The left side is the folder inside the Immich container: `/data` since Immich 3 (the
  `UPLOAD_LOCATION` of Immich is mounted there).
- The right side is the same folder as the media server sees it. With Jellyfin installed as a
  package, and for Kodi, that is the folder on the host: the value of `UPLOAD_LOCATION` (Samba
  follows the links on the host, see [step 6](#6-the-library-in-kodi)). With Jellyfin in Docker,
  it is the path where you mount the Immich library into the Jellyfin container (read-only is
  enough). Jellyfin in Docker together with Kodi needs the Immich library mounted in the Jellyfin
  container at the same path as on the host.

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
| `SHOWRUNNER_SHOW_PREFIX`, `SHOWRUNNER_PERSON_PREFIX` | `§ `, `• ` | A short mark before the title of a show and the name of a person. Use characters that are in the fonts of every client: the default skin of Kodi, for one, shows `◈` as a box |
| `SHOWRUNNER_TITLE_DATE_FORMAT` | `%Y-%m-%d %H:%M` | The title of a video without a description, e.g. `%d.%m.%Y, %H:%M` |
| `SHOWRUNNER_SYNC_INTERVAL_SECONDS` | `300` | Seconds between syncs; a full pass runs once an hour |
| `SHOWRUNNER_ARTWORK` | `true` | Pictures drawn from the frames of the videos: the poster, landscape picture, backdrop and logo of a show and the poster of each season, in one of several styles. `false`: the poster is the cover of the album |
| `SHOWRUNNER_ARTWORK_BUDGET_SECONDS` | `240` | Time a sync may spend looking at new videos for the pictures (about a second a video). A large library is looked at over several syncs; until then a show keeps the cover of its album |
| `SHOWRUNNER_SLIDESHOW_LOCATION` | — | The folder of the slideshows on the server (see [Slideshows](#9-slideshows)); without it each output folder gets a copy |
| `SHOWRUNNER_SLIDESHOW_PATH` | the location | Where the media servers see that folder, if not at the same path (Jellyfin in a container) |
| `SHOWRUNNER_SLIDESHOW_THREADS` | `2` | Threads a slideshow is drawn with: few, so that Immich and the media server keep theirs |
| `SHOWRUNNER_SLIDESHOW_RENDER_BUDGET_SECONDS` | `600` | Time a sync may spend drawing slideshows (a minute or two each); the rest are drawn in later syncs, the newest years first |
| `SHOWRUNNER_SLIDESHOW_BUDGET_SECONDS` | `240` | Time a sync may spend looking at new photos (about a second a photo) |
| `SHOWRUNNER_SLIDESHOW_CREDITS` | `true` | The credits at the end of a slideshow, until changed on the page |
| `SHOWRUNNER_SLIDESHOW_TRASH_DAYS` | `90` | Days a slideshow drawn again or removed is kept in the trash |
| `SHOWRUNNER_VERSION` | `0` | The version of the image; see [Updating](#updating) |

After changing a setting: `docker compose up -d`, then `docker compose run --rm app sync`, so that
every album is written again at once.

## 4. Check, try, start

```sh
docker compose run --rm app check            # settings, Immich, Jellyfin, Kodi, folders
docker compose run --rm app sync --dry-run   # what would be created; nothing is written
docker compose up -d
```

## 5. The library in Jellyfin

Add a library (Dashboard → Libraries) of the content type **Shows** with the Jellyfin folder, and
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

## 6. The library in Kodi

Checked on Kodi 21.

### Share the folder over SMB

Kodi reads the folder over the network. The folder holds links into the Immich library, and Samba
has to follow them on the server, outside the share. In `/etc/samba/smb.conf`:

```ini
[global]
   allow insecure wide links = yes

[showrunner-kodi]
   path = /srv/showrunner/kodi
   read only = yes
   follow symlinks = yes
   wide links = yes
```

Then `sudo systemctl restart smbd`. The user Kodi signs in with must be able to read the Immich
library on the server, as the user of Jellyfin does. `wide links` lets the share follow any link
in it; the folder holds only the links of the app, and the share is read-only. NFS does not work:
there the client follows the links, and Kodi can not reach the paths of the server.

### Add the source

In Kodi: Videos → Files → Add videos → the share, e.g. `smb://192.0.2.10/showrunner-kodi`. Then
set the content of the source:

| Setting | Value |
|---|---|
| This directory contains | TV shows |
| Choose information provider | Local information only |
| Selected folder contains a single TV show | off |

Every title, number, picture and face comes from the files of the app; Kodi looks nothing up on
the internet. Set `SHOWRUNNER_KODI_OUTPUT_PATH` to the path of the source exactly as Kodi shows it.

### Let the app tell Kodi

Kodi does not read the files of a known episode again by itself: a new title or a removed video
reaches it only when the app tells it. In Kodi: Settings → Services → Control → Allow remote
control via HTTP: on, with a user name and a password. The app talks to that web server (port 8080
by default) from another machine; "Allow remote control from applications on other systems" is not
needed for it. A firewall on the machine of Kodi has to let the app reach that port.

Set `SHOWRUNNER_KODI_URL`, `_USERNAME` and `_PASSWORD` in `.env` and run `check`. Kodi on a TV box
is often off: the app keeps the changes until it answers (`kodi_pending` on the Status page).
Every device with Kodi has its own library; the app tells one of them.

### Names of files

The files are named by the time of filming and an id, `2024-07-15 143211 [1898906754].mp4`; the
season and the episode number are in the NFO file next to it. The name never holds the number:
Kodi keeps its watched marks by file, and numbers move when a video is filmed between two others.

## 7. The web page

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

- **Albums**: every shared album, as it will be a show. Give a show its own title, one season
  instead of a season per year of filming, or leave it out of the media server. Rename the
  episodes, give them a description, move them up and down within their season, or hide them.
  Every change reaches Jellyfin and Kodi within a minute, and can be reset to what Immich says.
- **People**: the people shared with the user of the app (see below), their names for the media
  server and their descriptions.
- **Slideshows**: slideshows on (by default) or off, the end credits, the places on the title, the language of
  the text in the slideshows, your own music and the music set (see below). On the page of an
  album: slideshows off for this album, the mood of its music, the places on its titles, other
  music, and its slideshows to watch.
- **Status**: the last sync, what it could not do, and a button to sync now.

If Immich signs in only through OAuth, sign in with an API key of the user of the app instead.
To name people from the page, that key needs `person.update`, `clusterGroup.read`,
`clusterGroupRequest.read` and `clusterGroupRequest.create`.

## 8. People

People in Immich belong to the owner of the videos. To have them in the media server under names of
their own ("Mum" can stay "Mum" in the owner's library):

1. The owner invites the user of the app into their group: Account Settings → Sharing.
2. On the People page of Showrunner, accept the invitation.
3. The owner shares people with the user of the app: People → a person → Manage access.
4. On the People page, give each of them a name for the media server. The name is written to
   Immich for the user of the app only.

A person without such a name is not in the media server. People appear with the prefix
(`SHOWRUNNER_PERSON_PREFIX`) and with their face from Immich. In Jellyfin they are locked, so that
it does not fill them in with a namesake from TMDB; Kodi with "Local information only" looks
nothing up. The descriptions of people reach Jellyfin only.

> **One group only.** An Immich user is in one group at a time. Accepting the invitation of
> another group takes the user of the app out of the current one, and the people shared there are
> lost for the media server; in our tests they did not come back by joining again. All owners whose people
> should be in the media server have to be in the same group. The page accepts an invitation only while the
> user of the app is alone in its group.

## 9. Slideshows

On unless you switch them off on the Slideshows page (before 0.4.1 they were off until switched
on; a choice saved on the page stays). The photos of every album become videos with music, one for each year: "Photos 2024" among the specials (Season 0) of its show, placed after
the episodes of that year in Jellyfin and Kodi. A year needs at least six photos. A year is meant
to be watched at one sitting: at most twenty minutes, in parts of three to five minutes, cut
between days where they can be and else at the longest pauses and moves of a busy day (a
wedding, a match). An album
set to one season on its page gets slideshows of all its years together ("Photos 2019–2024"),
placed after that season. An album of photos only becomes a show of slideshows only.

- **What goes in**: the photos in the order they were taken, cut into scenes by pauses and by moves
  of the camera. Near copies become their best photo; screenshots, documents and receipts are left
  out (never a photo with a face). All the photos left are shown while twenty minutes hold them (about
  300); beyond that each day gives a share by the square root of its photos (a day of a few gives
  them all, a busy day more but not in proportion), spread over its whole time, the photos chosen
  unlike each other. The parts of a year go on with the next
  piece of music. The camera moves slowly towards the faces; a standing photo is shown whole over a blurred
  copy of itself. The title and the credits are drawn in the style of the album.
- **The title**: the name of the album, and under it, smaller, the date on a line of its own, so
  that it is never mistaken for a date in the name: the year ("2024"), the months of a part
  ("March–July 2024"), the years of an album of one season ("2019–2024"). Under the date, smaller
  still, where the photos were taken: up to three cities with the most photos, or the countries of
  a long journey, as Immich names them from the coordinates (on by default; off on the Slideshows
  page or for an album). The months and the word before the music in the credits are in the
  language chosen on the Slideshows page (English by default).
- **What became of the photos**: the page of the
  album says why photos were left out, in all and day by day; "How it was chosen" shows every
  photo of a slideshow, scene by scene: those shown, each group of near copies beside the photo it
  gave way to, those that did not fit in the twenty minutes of the season, and apart the
  screenshots and documents.
- **Music**: a set of 35 free pieces (CC BY and public domain, listed in
  [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md)) and your own, added on the page. The music of
  an album follows what its photos show (calm, bright, upbeat, cinematic for landscapes and views
  from above; wistful and solemn only when you choose them for an album); the photos change on the beats. The music is named in the description of every
  slideshow and, unless you switch it off, in its end credits. The rights to music you add are yours.
- **Downloads on first use**: an image model (CLIP, 351 MB, MIT) from Hugging Face, to tell what a
  photo shows, and the music set (213 MB) from a release of this project, both into the data
  volume of the app and checked by SHA-256. Without a network, slideshows are made without them. Your
  photos never leave the server.
- **Time**: drawing takes a minute or two for a few minutes of video, on two threads. The first
  time, a large library takes hours: slideshows appear one by one, the newest years first. A slideshow
  is drawn again when its photos, its music or the style of the album change; the one drawn before
  stays in the library meanwhile, with its watched mark. The page shows the slideshow being drawn,
  how far it is and how many wait.
- **The trash**: a slideshow drawn again or removed is moved to `.trash` in the folder of slideshows
  (in the data volume without one) and deleted after `SHOWRUNNER_SLIDESHOW_TRASH_DAYS` (90) days. The
  page of the album lists the versions there, to download; every slideshow can be downloaded there
  too.
- **The folder of slideshows** (`SHOWRUNNER_SLIDESHOW_LOCATION`, optional): Jellyfin must be able to
  read it, as it reads the Immich library; Kodi reaches it through the links in its share, as it
  reaches the videos of Immich. With full-size photos (`asset.download` on the key, and "Full-size
  image" on in the image settings of Immich for HEIC and RAW) the camera has more to move over.

## Updating

```sh
docker compose pull
docker compose up -d
```

`compose.yaml` pulls the newest release of the major version (`0` for now), so these two commands
are all an update needs; the database is brought to the new version when the app starts. To stay
on one version, set `SHOWRUNNER_VERSION=0.2.1` in `.env`. Read the release notes before an update:
they say when anything else is needed.

## Commands

```sh
docker compose run --rm app sync             # one full pass now
docker compose run --rm app sync --dry-run   # show what would change
docker compose run --rm app sync --force     # carry out a held mass removal
docker compose run --rm app check
docker compose run --rm app preview-titles --out /data/titles   # the titles of the slideshows
```

`preview-titles` draws the title of every slideshow as a picture, in minutes, to look over the
names, dates and places in the style of each album (`--album <text>`: only albums with that in
their name). An album already planned gets the titles of its plan; any other one title a year.
It writes nothing else; the pictures are in the data volume of the app
(`docker compose cp app:/data/titles ./titles` copies them out).

A sync that would remove more than half of all links (and more than 20) is **held**: that looks
like a wrong API key, not like albums that are no longer shared. Nothing is changed until you run
the sync with `--force`.

`http://127.0.0.1:8790/api/health` shows the time and the result of the last sync.

## What the app will and will not do

- It writes only to its output folders, the folder of slideshows and its data volume, and removes
  there only what it created. A file you put there or changed by hand is left alone.
- It never opens, changes, moves or removes a file of the Immich library; the library is not even
  mounted into its container.
- When Immich does not answer, nothing is removed.
- With slideshows on, it downloads an image model from Hugging Face and the music set from this
  project's releases, once. It sends nothing about your library anywhere.
- The folder of a show keeps its name when the album is renamed; the title changes in the media
  server.
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
| Kodi shows many seasons, or every video twice | The source points at the Jellyfin folder; Kodi needs its own folder (`SHOWRUNNER_KODI_OUTPUT_LOCATION`) |
| Kodi lists the files, but the videos do not play | Samba does not follow the links: `follow symlinks` and `wide links` in the share, `allow insecure wide links` in `[global]`, and the Samba user must be able to read the Immich library |
| `check` says Kodi did not answer | The web server of Kodi is off, a firewall on its machine blocks the port, or Kodi is asleep; changes wait in `kodi_pending` |
| `check` says Kodi can not open the folder | `SHOWRUNNER_KODI_OUTPUT_PATH` must be the path of the source exactly as Kodi shows it |
| New titles do not reach Kodi | Kodi reads the files of a known episode again only when it is told: set `SHOWRUNNER_KODI_URL`, or refresh the show in Kodi (Information → Refresh) |
| The page says "Signing in is not set up" | Set `SHOWRUNNER_SECRET_KEY` in `.env` and run `docker compose up -d` |
| People do not appear in the media server | They need a name on the People page; see [People](#8-people) |

## Building from source

```sh
git clone https://github.com/Ivamic/immich-showrunner.git
cd immich-showrunner
cp .env.example .env      # then set the values as above
docker compose -f compose.yaml -f compose.build.yaml build
docker compose -f compose.yaml -f compose.build.yaml run --rm app check
docker compose -f compose.yaml -f compose.build.yaml up -d
```
