<p align="center">
  <img src="docs/images/logo.svg" width="96" height="96" alt="Логотип Showrunner for Immich">
</p>

<h1 align="center">Showrunner for Immich</h1>

<p align="center">
  Альбомы Immich — сериалы в Jellyfin: каждое видео — эпизод, ни один файл не копируется.
</p>

<p align="center">
  <a href="https://github.com/Ivamic/immich-showrunner/releases"><img src="https://img.shields.io/github/v/release/Ivamic/immich-showrunner?include_prereleases&sort=semver" alt="Выпуск"></a>
  <a href="https://github.com/Ivamic/immich-showrunner/actions/workflows/ci.yml"><img src="https://github.com/Ivamic/immich-showrunner/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/github/license/Ivamic/immich-showrunner" alt="Лицензия: AGPL-3.0"></a>
  <img src="https://img.shields.io/badge/self--hosted-Docker%20Compose-2496ED?logo=docker&logoColor=white" alt="Устанавливается у себя через Docker Compose">
</p>

<p align="center">
  <a href="README.md">English</a> · <a href="README.de.md">Deutsch</a> · <a href="README.fr.md">Français</a> · <a href="README.it.md">Italiano</a> · <b>Русский</b>
</p>

> **Статус: ранняя разработка.** Альбомы, которыми поделились, становятся сериалами в Jellyfin с
> постерами, картинками и людьми, следят за изменениями в Immich и правятся на веб-странице.
> Возможны ошибки и изменения между версиями.

Работает с Immich 3 и Jellyfin 12; Jellyfin может быть в Docker или установлен пакетом.

Приложение-компаньон для [Immich](https://immich.app), которое ставится у себя. Видео из ваших
альбомов Immich появляются в [Jellyfin](https://jellyfin.org) как обычные элементы медиатеки:
альбом становится сериалом, каждое видео — эпизодом, в порядке съёмки. Видеофайлы остаются на
месте; медиасервер получает папку ссылок с метаданными рядом.

Типичный случай: семейный видеоархив хранится в Immich, а смотрят его на телевизоре через Jellyfin.

## Идея

- **Выбор — в Immich, а не в ещё одном приложении.** Заведите в Immich пользователя для
  медиасервера и поделитесь с ним альбомом — его видео появятся в Jellyfin. Перестали делиться —
  исчезли.
- **Альбом = сериал, видео = эпизод.** Сезоны — годы съёмки или один сезон на альбом. Название
  эпизода — первая строка описания видео в Immich или время съёмки; постер и картинки эпизодов —
  те же, что в Immich.
- **Люди из Immich** — под своими именами для медиасервера («мама» у вас останется «мамой») и с
  коротким префиксом, чтобы не смешиваться с актёрами вашей фильмотеки.
- **Работает само**, а для случаев, где угадало не так, есть веб-страница: переименовать сериал
  или эпизод, поменять порядок, скрыть видео, дать людям имена и описания. На английском,
  немецком, французском, итальянском и русском.
- **Сначала Jellyfin.** Kodi с дополнением Jellyfin видит сериалы через Jellyfin; Kodi без
  Jellyfin запланирован второй целью.

## Принципы

- **Без копий.** Ни один видеофайл не дублируется.
- **Библиотека Immich только для чтения.** Приложение никогда не меняет, не перемещает и не
  удаляет файлы Immich. Оно пишет только в свою папку и удаляет там только созданное им самим.
- **Само ничего не пишет в Immich.** Фоновая синхронизация работает с ключом только на чтение, а
  ваши правки хранятся в базе приложения. Исключения — то, что вы сами делаете на странице для
  пользователя медиасервера: имя человека, которым с ним поделились (только для этого
  пользователя), и принятие приглашения в группу.
- **Можно пересобрать.** Папку для медиасервера можно удалить и собрать заново.

## Установка

Showrunner запускается через Docker Compose на машине, где лежит библиотека Immich; Jellyfin
может работать в Docker или быть установлен пакетом. Образ готовый, для `amd64` и `arm64`:

```sh
mkdir immich-showrunner && cd immich-showrunner
curl -L -o compose.yaml https://github.com/Ivamic/immich-showrunner/releases/latest/download/compose.yaml
curl -L -o example.env https://github.com/Ivamic/immich-showrunner/releases/latest/download/example.env
cp example.env .env      # адреса и ключи Immich и Jellyfin, папки
docker compose run --rm app check
docker compose run --rm app sync --dry-run
docker compose up -d
```

Обновление — `docker compose pull && docker compose up -d`. [Установка по шагам](docs/install.md)
(на английском): пользователь и API-ключ в Immich, сопоставление путей, медиатека в Jellyfin,
веб-страница, люди.

## Устройство

- Python (FastAPI), PostgreSQL; один контейнер для приложения и один для его базы.
- Веб-страница — приложение SvelteKit, собранное в образ и отдаваемое приложением.
- Контейнер приложения монтирует только свою папку вывода. Immich он читает через API ключом
  только на чтение и файлов библиотеки не видит.
- Синхронизация сначала составляет план по тому, что сообщает Immich, и по реестру созданных
  файлов, а потом выполняет его; `sync --dry-run` останавливается на плане.

## Поддержать проект

Showrunner бесплатный и делается в свободное время. Если он вам пригодился, можно поддержать
разработку пожертвованием в криптовалюте. Звезда репозиторию, сообщения об ошибках и рассказ о
проекте тоже помогают.

| Валюта | Сеть | Адрес |
|---|---|---|
| USDT | TRON (TRC-20) | `TAqGEvmDTw2ro4BKQmcPPtqK5xEMfNaiSX` |
| ETH, USDT и другие токены | Ethereum и EVM-сети (Base, Polygon, Arbitrum…) | `0x783C192d69fE5E9DAfa1dC2c41FeE272122AE031` |
| SOL | Solana | `38gidbL2ocv5c6CK7zP7c3QWVHisYyqhnrMV3tuaYpgp` |
| BTC | Bitcoin | `bc1qsdys5hvx7vlxp25mz77hfgz2l35x8klc8z2npx` |

Перед отправкой проверьте сеть: средства, отправленные по другой сети, могут потеряться.

## Лицензия

Copyright (C) 2026 Ivamic.

[GNU Affero General Public License v3.0 или новее](LICENSE) (`AGPL-3.0-or-later`).

**Название и логотип.** Название «Showrunner for Immich» и логотип (`docs/images/logo.svg`,
`frontend/src/lib/assets/favicon.svg` и знак в `frontend/src/lib/ui/Brand.svelte`) не входят в
лицензию AGPL; все права принадлежат автору. Ими можно пользоваться, чтобы сослаться на этот
проект. Форки и изменённые версии должны использовать другое название и логотип.

## Помощь ИИ

Проект разрабатывается с помощью инструментов ИИ (Claude от Anthropic). Весь код проверяет и
сопровождает человек — автор.

## Оговорка

Это независимый проект сообщества. Он не связан с проектом Immich, FUTO, проектом Jellyfin и
Kodi Foundation и не одобрен ими.
