<h1 align="center">Showrunner for Immich</h1>

<p align="center">
  Your Immich albums as TV shows in Jellyfin — every video an episode, no files copied.
</p>

> **Status: planning.** There is no working version yet. This page describes what the app is
> going to do; the first release will be announced here.

A self-hosted companion app for [Immich](https://immich.app). It makes the videos of your Immich
albums appear in [Jellyfin](https://jellyfin.org) as ordinary library items: an album becomes a
show, each video an episode, in the order they were filmed. The video files stay where they are;
the media server gets a folder of links with metadata next to them.

Typical use case: a family video archive kept in Immich, watched on the TV through Jellyfin.

## Idea

- **You choose in Immich, not in another app.** Create one Immich user for the media server and
  share an album with it: its videos show up in Jellyfin. Stop sharing, and they are gone.
- **Album = show, video = episode.** Seasons are the years of filming, or one season per album.
  The title of an episode is the first line of the video's description in Immich, or the date
  it was filmed.
- **People from Immich**, under names of their own for the media server ("Mum" can stay "Mum"
  in your library), marked with a short prefix so that they never mix with the actors of your
  film library.
- **Works by itself**, with a small web page for the cases where it guessed wrong: rename an
  episode, change the order, hide a video.
- **Jellyfin first.** Kodi is planned as the second target.

## Principles

- **No copies.** Not a single video file is duplicated.
- **The Immich library is read-only.** The app never changes, moves or deletes files of Immich.
  It writes only to its own folder and removes only what it created there.
- **Nothing is written to Immich on its own.** The background sync uses a read-only API key,
  and your corrections are kept in the app's own database. The one exception is what you do
  yourself on the app's page for the media server's user: naming a person shared with it.
- **Rebuildable.** The folder for the media server can be deleted and built again.

## Installation

Not available yet. The app will run with Docker Compose next to your Immich server; Jellyfin
may run in Docker or be installed as a system package.

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

**Name and logo.** The name "Showrunner for Immich" and its logo, once there is one, are not
licensed under the AGPL; all rights are reserved by the author. You may use them to refer to
this project. Forks and modified versions must use a different name and logo.

## AI assistance

This project is developed with the help of AI tools (Claude by Anthropic).
All code is reviewed and maintained by a human author.

## Disclaimer

This is an independent community project. It is not affiliated with or endorsed by the
Immich project, FUTO, the Jellyfin project or the Kodi Foundation.
