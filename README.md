<p align="center">
  <img src="docs/images/logo.svg" width="96" height="96" alt="Showrunner for Immich logo">
</p>

<h1 align="center">Showrunner for Immich</h1>

<p align="center">
  Your Immich albums as TV shows in Jellyfin — every video an episode, no files copied.
</p>

<p align="center">
  <a href="https://github.com/Ivamic/immich-showrunner/releases"><img src="https://img.shields.io/github/v/release/Ivamic/immich-showrunner?include_prereleases&sort=semver" alt="Release"></a>
  <a href="https://github.com/Ivamic/immich-showrunner/actions/workflows/ci.yml"><img src="https://github.com/Ivamic/immich-showrunner/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/github/license/Ivamic/immich-showrunner" alt="License: AGPL-3.0"></a>
  <img src="https://img.shields.io/badge/self--hosted-Docker%20Compose-2496ED?logo=docker&logoColor=white" alt="Self-hosted with Docker Compose">
</p>

<p align="center">
  <b>English</b> · <a href="README.de.md">Deutsch</a> · <a href="README.fr.md">Français</a> · <a href="README.it.md">Italiano</a> · <a href="README.ru.md">Русский</a>
</p>

> **Status: early development.** Shared albums become shows in Jellyfin with posters, pictures
> and people, follow the changes in Immich, and can be corrected on a web page. Expect bugs and
> changes between versions.

Works with Immich 3 and Jellyfin 12; Jellyfin may run in Docker or be installed as a package.

A self-hosted companion app for [Immich](https://immich.app). It makes the videos of your Immich
albums appear in [Jellyfin](https://jellyfin.org) as ordinary library items: an album becomes a
show, each video an episode, in the order they were filmed. The video files stay where they are;
the media server gets a folder of links with metadata next to them.

Typical use case: a family video archive kept in Immich, watched on the TV through Jellyfin.

## Idea

- **You choose in Immich, not in another app.** Create one Immich user for the media server and
  share an album with it: its videos show up in Jellyfin. Stop sharing, and they are gone.
- **Album = show, video = episode.** Seasons are the years of filming, or one season per album.
  The title of an episode is the first line of the video's description in Immich, or the time
  it was filmed; the poster and the pictures of the episodes are those of Immich.
- **People from Immich**, under names of their own for the media server ("Mum" can stay "Mum"
  in your library), marked with a short prefix so that they never mix with the actors of your
  film library.
- **Works by itself**, with a web page for the cases where it guessed wrong: rename a show or
  an episode, change the order, hide a video, name people and describe them. In English, German,
  French, Italian and Russian.
- **Jellyfin first.** Kodi with the Jellyfin add-on sees the shows through Jellyfin; Kodi on its
  own is planned as the second target.

## Principles

- **No copies.** Not a single video file is duplicated.
- **The Immich library is read-only.** The app never changes, moves or deletes files of Immich.
  It writes only to its own folder and removes only what it created there.
- **Nothing is written to Immich on its own.** The background sync uses a read-only API key,
  and your corrections are kept in the app's own database. The exceptions are what you do
  yourself on the app's page for the media server's user: naming a person shared with it, for
  that user only, and accepting an invitation into a group.
- **Rebuildable.** The folder for the media server can be deleted and built again.

## Installation

Showrunner runs with Docker Compose on the machine that holds the Immich library; Jellyfin may run
in Docker or be installed as a system package. The image is ready-made, for `amd64` and `arm64`:

```sh
mkdir immich-showrunner && cd immich-showrunner
curl -L -o compose.yaml https://github.com/Ivamic/immich-showrunner/releases/latest/download/compose.yaml
curl -L -o example.env https://github.com/Ivamic/immich-showrunner/releases/latest/download/example.env
cp example.env .env      # Immich and Jellyfin addresses and keys, folders
docker compose run --rm app check
docker compose run --rm app sync --dry-run
docker compose up -d
```

Updating is `docker compose pull && docker compose up -d`. [Installation step by step](docs/install.md):
the user and the API key in Immich, the path mapping, the library in Jellyfin, the web page, people.

## Architecture

- Python (FastAPI), PostgreSQL; one container for the app and one for its database.
- The web page is a SvelteKit app built into the image and served by the app.
- The app container mounts only its output folder. It reads Immich over the API with a read-only
  key and never sees the files of the library.
- A sync first makes a plan from what Immich reports and from the registry of the files the app
  created, then carries it out; `sync --dry-run` stops after the plan.

## Support the project

Showrunner is free and developed in spare time. If you find it useful, you can support its
development with a donation in cryptocurrency. Starring the repository, reporting bugs and
sharing the project help too.

| Currency | Network | Address |
|---|---|---|
| USDT | TRON (TRC-20) | `TAqGEvmDTw2ro4BKQmcPPtqK5xEMfNaiSX` |
| ETH, USDT and other tokens | Ethereum and EVM networks (Base, Polygon, Arbitrum…) | `0x783C192d69fE5E9DAfa1dC2c41FeE272122AE031` |
| SOL | Solana | `38gidbL2ocv5c6CK7zP7c3QWVHisYyqhnrMV3tuaYpgp` |
| BTC | Bitcoin | `bc1qsdys5hvx7vlxp25mz77hfgz2l35x8klc8z2npx` |

Please double-check the network before sending: funds sent over a different network may be lost.

## License

Copyright (C) 2026 Ivamic.

[GNU Affero General Public License v3.0 or later](LICENSE) (`AGPL-3.0-or-later`).

**Name and logo.** The name "Showrunner for Immich" and its logo (`docs/images/logo.svg`,
`frontend/src/lib/assets/favicon.svg` and the mark drawn in `frontend/src/lib/ui/Brand.svelte`) are
not licensed under the AGPL; all rights are reserved by the author. You may use them to refer to
this project. Forks and modified versions must use a different name and logo.

## AI assistance

This project is developed with the help of AI tools (Claude by Anthropic).
All code is reviewed and maintained by a human author.

## Disclaimer

This is an independent community project. It is not affiliated with or endorsed by the
Immich project, FUTO, the Jellyfin project or the Kodi Foundation.
