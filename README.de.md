<p align="center">
  <img src="docs/images/logo.svg" width="96" height="96" alt="Logo von Showrunner for Immich">
</p>

<h1 align="center">Showrunner for Immich</h1>

<p align="center">
  Ihre Immich-Alben als Serien in Jellyfin – jedes Video eine Folge, keine Datei kopiert.
</p>

<p align="center">
  <a href="https://github.com/Ivamic/immich-showrunner/releases"><img src="https://img.shields.io/github/v/release/Ivamic/immich-showrunner?include_prereleases&sort=semver" alt="Release"></a>
  <a href="https://github.com/Ivamic/immich-showrunner/actions/workflows/ci.yml"><img src="https://github.com/Ivamic/immich-showrunner/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/github/license/Ivamic/immich-showrunner" alt="Lizenz: AGPL-3.0"></a>
  <img src="https://img.shields.io/badge/self--hosted-Docker%20Compose-2496ED?logo=docker&logoColor=white" alt="Selbst gehostet mit Docker Compose">
</p>

<p align="center">
  <a href="README.md">English</a> · <b>Deutsch</b> · <a href="README.fr.md">Français</a> · <a href="README.it.md">Italiano</a> · <a href="README.ru.md">Русский</a>
</p>

> **Status: frühe Entwicklung.** Geteilte Alben werden zu Serien in Jellyfin mit Postern, Bildern
> und Personen, folgen den Änderungen in Immich und lassen sich auf einer Webseite korrigieren.
> Rechnen Sie mit Fehlern und Änderungen zwischen den Versionen.

Funktioniert mit Immich 3 und Jellyfin 12; Jellyfin kann in Docker laufen oder als Paket
installiert sein.

Eine selbst gehostete Begleit-App für [Immich](https://immich.app). Sie lässt die Videos Ihrer
Immich-Alben in [Jellyfin](https://jellyfin.org) als ganz normale Bibliothekseinträge erscheinen:
ein Album wird zur Serie, jedes Video zu einer Folge, in der Reihenfolge der Aufnahme. Die
Videodateien bleiben, wo sie sind; der Medienserver bekommt einen Ordner mit Verknüpfungen und
Metadaten daneben.

Typischer Einsatz: ein Familien-Videoarchiv in Immich, angeschaut auf dem Fernseher über Jellyfin.

## Idee

- **Sie wählen in Immich, nicht in einer weiteren App.** Legen Sie in Immich einen Benutzer für
  den Medienserver an und teilen Sie ein Album mit ihm: seine Videos erscheinen in Jellyfin. Teilen
  Sie es nicht mehr, verschwinden sie.
- **Album = Serie, Video = Folge.** Staffeln sind die Aufnahmejahre oder eine Staffel pro Album.
  Der Titel einer Folge ist die erste Zeile der Videobeschreibung in Immich oder der
  Aufnahmezeitpunkt; Poster und Bilder der Folgen sind die aus Immich.
- **Personen aus Immich**, unter eigenen Namen für den Medienserver („Mama“ darf bei Ihnen „Mama“
  bleiben), mit einem kurzen Präfix markiert, damit sie sich nie mit den Schauspielern Ihrer
  Filmbibliothek vermischen.
- **Läuft von selbst**, mit einer Webseite für die Fälle, in denen es falsch geraten hat: eine
  Serie oder Folge umbenennen, die Reihenfolge ändern, ein Video ausblenden, Personen benennen und
  beschreiben. Auf Englisch, Deutsch, Französisch, Italienisch und Russisch.
- **Zuerst Jellyfin.** Kodi mit dem Jellyfin-Add-on sieht die Serien über Jellyfin; Kodi allein ist
  als zweites Ziel geplant.

## Grundsätze

- **Keine Kopien.** Keine einzige Videodatei wird dupliziert.
- **Die Immich-Bibliothek ist schreibgeschützt.** Die App ändert, verschiebt oder löscht niemals
  Dateien von Immich. Sie schreibt nur in ihren eigenen Ordner und entfernt dort nur, was sie
  selbst angelegt hat.
- **Nichts wird von selbst in Immich geschrieben.** Die Synchronisierung im Hintergrund nutzt
  einen API-Schlüssel nur zum Lesen, und Ihre Korrekturen liegen in der eigenen Datenbank der App.
  Ausnahmen sind, was Sie selbst auf der Seite für den Benutzer des Medienservers tun: einer mit
  ihm geteilten Person einen Namen geben (nur für diesen Benutzer) und eine Einladung in eine
  Gruppe annehmen.
- **Wiederherstellbar.** Der Ordner für den Medienserver kann gelöscht und neu aufgebaut werden.

## Installation

Showrunner läuft mit Docker Compose auf dem Rechner, auf dem die Immich-Bibliothek liegt; Jellyfin
kann in Docker laufen oder als Paket installiert sein. Das Image ist fertig gebaut, für `amd64`
und `arm64`:

```sh
mkdir immich-showrunner && cd immich-showrunner
curl -L -o compose.yaml https://github.com/Ivamic/immich-showrunner/releases/latest/download/compose.yaml
curl -L -o example.env https://github.com/Ivamic/immich-showrunner/releases/latest/download/example.env
cp example.env .env      # Adressen und Schlüssel von Immich und Jellyfin, Ordner
docker compose run --rm app check
docker compose run --rm app sync --dry-run
docker compose up -d
```

Aktualisieren: `docker compose pull && docker compose up -d`. [Installation Schritt für
Schritt](docs/install.md) (auf Englisch): der Benutzer und der API-Schlüssel in Immich, die
Pfadzuordnung, die Bibliothek in Jellyfin, die Webseite, Personen.

## Aufbau

- Python (FastAPI), PostgreSQL; ein Container für die App und einer für ihre Datenbank.
- Die Webseite ist eine SvelteKit-App, ins Image gebaut und von der App ausgeliefert.
- Der App-Container bindet nur seinen Ausgabeordner ein. Immich liest er über die API mit einem
  Schlüssel nur zum Lesen und sieht die Dateien der Bibliothek nie.
- Eine Synchronisierung erstellt zuerst einen Plan aus dem, was Immich meldet, und aus dem
  Verzeichnis der von der App angelegten Dateien, und führt ihn dann aus; `sync --dry-run` hält
  nach dem Plan an.

## Das Projekt unterstützen

Showrunner ist kostenlos und entsteht in der Freizeit. Wenn es Ihnen nützt, können Sie die
Entwicklung mit einer Spende in Kryptowährung unterstützen. Ein Stern für das Repository,
Fehlermeldungen und das Weitererzählen helfen ebenfalls.

| Währung | Netzwerk | Adresse |
|---|---|---|
| USDT | TRON (TRC-20) | `TAqGEvmDTw2ro4BKQmcPPtqK5xEMfNaiSX` |
| ETH, USDT und andere Token | Ethereum und EVM-Netzwerke (Base, Polygon, Arbitrum…) | `0x783C192d69fE5E9DAfa1dC2c41FeE272122AE031` |
| SOL | Solana | `38gidbL2ocv5c6CK7zP7c3QWVHisYyqhnrMV3tuaYpgp` |
| BTC | Bitcoin | `bc1qsdys5hvx7vlxp25mz77hfgz2l35x8klc8z2npx` |

Prüfen Sie vor dem Senden das Netzwerk: Über ein anderes Netzwerk gesendete Beträge können
verloren gehen.

## Lizenz

Copyright (C) 2026 Ivamic.

[GNU Affero General Public License v3.0 oder neuer](LICENSE) (`AGPL-3.0-or-later`).

**Name und Logo.** Der Name „Showrunner for Immich“ und sein Logo (`docs/images/logo.svg`,
`frontend/src/lib/assets/favicon.svg` und das in `frontend/src/lib/ui/Brand.svelte` gezeichnete
Zeichen) stehen nicht unter der AGPL; alle Rechte liegen beim Autor. Sie dürfen sie verwenden, um
auf dieses Projekt zu verweisen. Forks und veränderte Versionen müssen einen anderen Namen und ein
anderes Logo verwenden.

## KI-Unterstützung

Dieses Projekt wird mit Hilfe von KI-Werkzeugen (Claude von Anthropic) entwickelt. Der gesamte
Code wird von einem menschlichen Autor geprüft und gepflegt.

## Haftungsausschluss

Dies ist ein unabhängiges Community-Projekt. Es steht in keiner Verbindung zum Immich-Projekt, zu
FUTO, zum Jellyfin-Projekt oder zur Kodi Foundation und wird von ihnen nicht unterstützt.
