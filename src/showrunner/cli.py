# SPDX-License-Identifier: AGPL-3.0-or-later
"""Commands: `showrunner serve | sync | check | migrate`."""

import argparse
import asyncio
import logging
import os
import sys
from collections import Counter

import uvicorn
from pydantic import ValidationError

from showrunner import __version__
from showrunner.config import Settings, get_settings
from showrunner.immich.client import ImmichError
from showrunner.runner import (
    SetupError,
    check_api_key,
    immich_client,
    jellyfin_client,
    jellyfin_output_path,
    sync_once,
)
from showrunner.store.db import make_engine, make_session_factory, upgrade
from showrunner.sync.plan import ActionType
from showrunner.sync.service import SyncReport
from showrunner.targets.jellyfin.client import JellyfinError

MAX_LISTED = 40


def print_report(report: SyncReport, notes: list[str]) -> None:
    plan = report.plan
    counts = Counter(a.type for a in plan.actions)
    head = "Dry run: nothing was written." if report.dry_run else "Sync finished."
    print(head)
    print(f"  albums: {report.albums} (read: {report.albums_read})")
    print(
        f"  planned: {counts[ActionType.CREATE]} to create, {counts[ActionType.REPLACE]} to "
        f"replace, {counts[ActionType.REMOVE]} to remove, {plan.unchanged} unchanged"
    )
    if not report.dry_run and not report.held:
        done = f"{report.created} created, {report.replaced} replaced, {report.removed} removed"
        print(f"  done: {done}")
    if report.dry_run:
        for action in plan.actions[:MAX_LISTED]:
            print(f"    {action.type.value:8} {action.path}")
        if len(plan.actions) > MAX_LISTED:
            print(f"    ... and {len(plan.actions) - MAX_LISTED} more")
    if report.held:
        print(
            f"HELD: the sync would remove {plan.links_removed} of {plan.links_before} links, "
            "which looks like a wrong API key or user. Nothing was changed. If it is right, run "
            "the sync again with --force."
        )
    for album, skipped in report.skipped:
        print(f"  skipped: {album} / {skipped.file_name} ({skipped.reason.value})")
    for outcome in report.foreign:
        print(f"  left alone: {outcome.action.path} ({outcome.detail})")
    for error in report.errors:
        print(f"  ERROR: {error}")
    for note in notes:
        print(f"  note: {note}")


async def cmd_sync(settings: Settings, args: argparse.Namespace) -> int:
    engine = make_engine(settings.database_url)
    try:
        report, notes = await sync_once(
            settings,
            make_session_factory(engine),
            dry_run=args.dry_run,
            full=not args.quick,
            force=args.force,
        )
    finally:
        await engine.dispose()
    print_report(report, notes)
    return 0 if report.ok else 1


async def cmd_check(settings: Settings) -> int:
    failed = False

    def line(ok: bool, text: str) -> None:
        nonlocal failed
        failed = failed or not ok
        print(("ok    " if ok else "FAIL  ") + text)

    try:
        async with immich_client(settings) as immich:
            version = await immich.server_version()
            line(version.major == 3, f"Immich {version} at {settings.immich_url}")
            for warning in await check_api_key(immich):
                print("note  " + warning)
            albums = await immich.albums()
            line(True, f"Immich: {len(albums)} album(s) visible to the API key")
    except (ImmichError, SetupError) as exc:
        line(False, f"Immich: {exc}")

    line(bool(settings.path_mappings), f"path mappings: {settings.path_map or '(none)'}")
    out = settings.output_dir
    line(out.is_dir() and os.access(out, os.W_OK), f"output folder {out} exists and is writable")

    jellyfin = jellyfin_client(settings)
    if jellyfin is None:
        print("note  Jellyfin is not configured (SHOWRUNNER_JELLYFIN_URL and _API_KEY)")
    else:
        try:
            async with jellyfin:
                line(True, f"Jellyfin {await jellyfin.version()} at {settings.jellyfin_url}")
                folder = jellyfin_output_path(settings)
                library = await jellyfin.library_id(folder)
                line(library is not None, f"Jellyfin has a library with the folder {folder}")
        except JellyfinError as exc:
            line(False, f"Jellyfin: {exc}")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="showrunner", description="Showrunner for Immich")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)

    serve = commands.add_parser("serve", help="sync on a schedule and answer /api/health")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8080)

    sync = commands.add_parser("sync", help="one pass of the sync")
    sync.add_argument(
        "--dry-run", action="store_true", help="show what would change, write nothing"
    )
    sync.add_argument("--quick", action="store_true", help="leave unchanged albums alone")
    sync.add_argument("--force", action="store_true", help="carry out a mass removal")

    commands.add_parser("check", help="check the settings, Immich, Jellyfin and the folders")
    commands.add_parser("migrate", help="bring the database to the latest version")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    # One line per request to Immich and Jellyfin is too much for the log of a scheduler.
    for noisy in ("httpx2", "httpcore2", "alembic"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    try:
        settings = get_settings()
    except ValidationError as exc:
        for error in exc.errors():
            name = "SHOWRUNNER_" + "_".join(str(part) for part in error["loc"]).upper()
            print(f"{name}: {error['msg']}", file=sys.stderr)
        return 2

    if args.command == "serve":
        uvicorn.run("showrunner.app:create_app", factory=True, host=args.host, port=args.port)
        return 0
    if args.command == "migrate":
        upgrade(settings.database_url)
        return 0
    try:
        if args.command == "check":
            return asyncio.run(cmd_check(settings))
        upgrade(settings.database_url)
        return asyncio.run(cmd_sync(settings, args))
    except (ImmichError, SetupError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
