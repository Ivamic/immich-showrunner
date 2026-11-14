<p align="center">
  <img src="docs/images/logo.svg" width="96" height="96" alt="Logo di Showrunner for Immich">
</p>

<h1 align="center">Showrunner for Immich</h1>

<p align="center">
  I tuoi album di Immich come serie in Jellyfin — ogni video un episodio, nessun file copiato.
</p>

<p align="center">
  <a href="https://github.com/Ivamic/immich-showrunner/releases"><img src="https://img.shields.io/github/v/release/Ivamic/immich-showrunner?include_prereleases&sort=semver" alt="Versione"></a>
  <a href="https://github.com/Ivamic/immich-showrunner/actions/workflows/ci.yml"><img src="https://github.com/Ivamic/immich-showrunner/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/github/license/Ivamic/immich-showrunner" alt="Licenza: AGPL-3.0"></a>
  <img src="https://img.shields.io/badge/self--hosted-Docker%20Compose-2496ED?logo=docker&logoColor=white" alt="Self-hosted con Docker Compose">
</p>

<p align="center">
  <a href="README.md">English</a> · <a href="README.de.md">Deutsch</a> · <a href="README.fr.md">Français</a> · <b>Italiano</b> · <a href="README.ru.md">Русский</a>
</p>

> **Stato: sviluppo iniziale.** Gli album condivisi diventano serie in Jellyfin con locandine,
> immagini e persone, seguono le modifiche in Immich e si correggono su una pagina web. Aspettati
> errori e cambiamenti tra le versioni.

Funziona con Immich 3 e Jellyfin 12; Jellyfin può girare in Docker o essere installato come
pacchetto.

Un’app di accompagnamento self-hosted per [Immich](https://immich.app). Fa comparire i video dei
tuoi album di Immich in [Jellyfin](https://jellyfin.org) come normali elementi della libreria: un
album diventa una serie, ogni video un episodio, nell’ordine delle riprese. I file video restano
dove sono; il media server riceve una cartella di collegamenti con i metadati accanto.

Caso tipico: un archivio video di famiglia tenuto in Immich, guardato in TV tramite Jellyfin.

## Idea

- **Scegli in Immich, non in un’altra app.** Crea in Immich un utente per il media server e
  condividi un album con lui: i suoi video compaiono in Jellyfin. Smetti di condividerlo, e
  spariscono.
- **Album = serie, video = episodio.** Le stagioni sono gli anni delle riprese, oppure una sola
  stagione per album. Il titolo di un episodio è la prima riga della descrizione del video in
  Immich, oppure l’ora della ripresa; la locandina e le immagini degli episodi sono quelle di Immich.
- **Le persone di Immich**, con nomi propri per il media server («Mamma» può restare «Mamma» da
  te), segnate da un breve prefisso perché non si mescolino mai con gli attori della tua
  cineteca.
- **Funziona da solo**, con una pagina web per i casi in cui ha indovinato male: rinominare una
  serie o un episodio, cambiare l’ordine, nascondere un video, dare un nome e una descrizione alle
  persone. In inglese, tedesco, francese, italiano e russo.
- **Prima Jellyfin.** Kodi con l’add-on di Jellyfin vede le serie tramite Jellyfin; Kodi da solo è
  previsto come secondo obiettivo.

## Principi

- **Nessuna copia.** Nessun file video viene duplicato.
- **La libreria di Immich è in sola lettura.** L’app non modifica, sposta o elimina mai i file di
  Immich. Scrive solo nella propria cartella e lì rimuove solo ciò che ha creato.
- **Niente viene scritto in Immich da solo.** La sincronizzazione in background usa una chiave API
  in sola lettura e le tue correzioni restano nel database dell’app. Le eccezioni sono ciò che fai
  tu stesso sulla pagina per l’utente del media server: dare un nome a una persona condivisa con
  lui (solo per quell’utente) e accettare un invito in un gruppo.
- **Ricostruibile.** La cartella per il media server può essere eliminata e ricostruita.

## Installazione

Showrunner gira con Docker Compose sulla macchina che ospita la libreria di Immich; Jellyfin può
girare in Docker o essere installato come pacchetto. L’immagine è già pronta, per `amd64` e `arm64`:

```sh
mkdir immich-showrunner && cd immich-showrunner
curl -L -o compose.yaml https://github.com/Ivamic/immich-showrunner/releases/latest/download/compose.yaml
curl -L -o example.env https://github.com/Ivamic/immich-showrunner/releases/latest/download/example.env
cp example.env .env      # indirizzi e chiavi di Immich e Jellyfin, cartelle
docker compose run --rm app check
docker compose run --rm app sync --dry-run
docker compose up -d
```

Aggiornamento: `docker compose pull && docker compose up -d`. [Installazione passo
passo](docs/install.md) (in inglese): l’utente e la chiave API in Immich, la mappatura dei percorsi,
la libreria in Jellyfin, la pagina web, le persone.

## Architettura

- Python (FastAPI), PostgreSQL; un container per l’app e uno per il suo database.
- La pagina web è un’app SvelteKit inclusa nell’immagine e servita dall’app.
- Il container dell’app monta solo la sua cartella di output. Legge Immich tramite l’API con una
  chiave in sola lettura e non vede mai i file della libreria.
- Una sincronizzazione prima prepara un piano da ciò che riporta Immich e dal registro dei file
  creati dall’app, poi lo esegue; `sync --dry-run` si ferma dopo il piano.

## Sostieni il progetto

Showrunner è gratuito e sviluppato nel tempo libero. Se ti è utile, puoi sostenerne lo sviluppo
con una donazione in criptovaluta. Una stella al repository, le segnalazioni di errori e il
passaparola aiutano anche loro.

| Valuta | Rete | Indirizzo |
|---|---|---|
| USDT | TRON (TRC-20) | `TAqGEvmDTw2ro4BKQmcPPtqK5xEMfNaiSX` |
| ETH, USDT e altri token | Ethereum e reti EVM (Base, Polygon, Arbitrum…) | `0x783C192d69fE5E9DAfa1dC2c41FeE272122AE031` |
| SOL | Solana | `38gidbL2ocv5c6CK7zP7c3QWVHisYyqhnrMV3tuaYpgp` |
| BTC | Bitcoin | `bc1qsdys5hvx7vlxp25mz77hfgz2l35x8klc8z2npx` |

Controlla la rete prima di inviare: i fondi inviati su un’altra rete possono andare persi.

## Licenza

Copyright (C) 2026 Ivamic.

[GNU Affero General Public License v3.0 o successiva](LICENSE) (`AGPL-3.0-or-later`).

**Nome e logo.** Il nome «Showrunner for Immich» e il suo logo (`docs/images/logo.svg`,
`frontend/src/lib/assets/favicon.svg` e il marchio disegnato in `frontend/src/lib/ui/Brand.svelte`)
non sono concessi con la licenza AGPL; tutti i diritti sono riservati all’autore. Puoi usarli per
fare riferimento a questo progetto. Fork e versioni modificate devono usare un nome e un logo
diversi.

## Assistenza dell’IA

Questo progetto è sviluppato con l’aiuto di strumenti di IA (Claude di Anthropic). Tutto il codice
è revisionato e mantenuto da un autore umano.

## Avvertenza

Questo è un progetto indipendente della comunità. Non è affiliato né approvato dal progetto Immich,
da FUTO, dal progetto Jellyfin o dalla Kodi Foundation.
