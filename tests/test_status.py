# SPDX-License-Identifier: AGPL-3.0-or-later
"""The status of the sync on the page, and a pass on request."""

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any
from uuid import UUID

import httpx2
import pytest
from fastapi.testclient import TestClient

from showrunner import scheduler as scheduler_module
from showrunner.app import create_app
from showrunner.config import Settings
from showrunner.model.show import Skipped, SkipReason
from showrunner.scheduler import State, one_pass
from showrunner.sync.executor import Outcome, Result
from showrunner.sync.plan import Action, ActionType, Plan
from showrunner.sync.service import SyncReport
from showrunner.targets.base import FileKind
from test_auth import APP_KEY, SECRET, Immich

ALBUM = UUID(int=1)


@pytest.fixture
def client(empty_database: str) -> Iterator[TestClient]:
    immich = Immich()
    settings = Settings(
        _env_file=None,
        immich_url="http://immich.test",
        immich_api_key=APP_KEY,
        database_url=empty_database,
        secret_key=SECRET,
    )
    app = create_app(
        settings, run_scheduler=False, immich_transport=httpx2.MockTransport(immich.handler)
    )
    with TestClient(app) as test_client:
        yield test_client


def sign_in(client: TestClient) -> None:
    response = client.post(
        "/api/auth/login", json={"email": "jellyfin@lab.test", "password": "pass-jf"}
    )
    assert response.status_code == 200


def report() -> SyncReport:
    action = Action(ActionType.CREATE, PurePosixPath("Show/tvshow.nfo"), FileKind.SHOW_NFO, ALBUM)
    result = SyncReport(dry_run=False, plan=Plan(actions=(action,)), albums=3, created=5)
    result.skipped = [("Summer", Skipped(UUID(int=2), "VID_1.mp4", SkipReason.NO_PATH_MAPPING))]
    result.foreign = [Outcome(action, Result.FOREIGN, "the file was changed by somebody else")]
    result.pictures_failed = ["Show/x-thumb.jpg: not JPEG"]
    return result


def test_status_needs_sign_in(client: TestClient) -> None:
    assert client.get("/api/status").status_code == 401
    assert client.post("/api/sync", json={}).status_code == 401


def test_status_shows_the_last_pass(client: TestClient) -> None:
    sign_in(client)
    state: State = client.app.state.status  # type: ignore[attr-defined]
    state.record(report(), ["refreshed the show"])
    data: dict[str, Any] = client.get("/api/status").json()
    assert data["ok"] is True and data["shows"] == 3 and data["created"] == 5
    assert data["skipped"] == [
        {"album": "Summer", "file": "VID_1.mp4", "reason": "no_path_mapping"}
    ]
    assert data["foreign"] == [
        {"path": "Show/tvshow.nfo", "detail": "the file was changed by somebody else"}
    ]
    assert data["pictures_failed"] == ["Show/x-thumb.jpg: not JPEG"]
    assert data["sync_interval_seconds"] == 300


def test_sync_now_and_force(client: TestClient) -> None:
    sign_in(client)
    state: State = client.app.state.status  # type: ignore[attr-defined]
    assert client.post("/api/sync", json={}).status_code == 202
    assert state.wake.is_set() and state.full_next and not state.force_next
    client.post("/api/sync", json={"force": True})
    assert state.force_next


def test_a_pass_uses_and_clears_the_request(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[dict[str, bool]] = []

    async def fake_sync(
        settings: Any, sessions: Any, **kwargs: bool
    ) -> tuple[SyncReport, list[str]]:
        seen.append(kwargs)
        return report(), []

    monkeypatch.setattr(scheduler_module, "sync_once", fake_sync)
    state = State()
    state.last_full_sync_at = datetime.now(UTC)
    state.request(force=True)

    asyncio.run(one_pass(None, None, state))  # type: ignore[arg-type]
    asyncio.run(one_pass(None, None, state))  # type: ignore[arg-type]
    assert seen == [{"full": True, "force": True}, {"full": False, "force": False}]
    assert state.last_ok is True and not state.running


def test_a_failed_pass_is_shown(monkeypatch: pytest.MonkeyPatch) -> None:
    async def broken(settings: Any, sessions: Any, **kwargs: bool) -> tuple[SyncReport, list[str]]:
        raise OSError("disk full")

    monkeypatch.setattr(scheduler_module, "sync_once", broken)
    state = State()
    asyncio.run(one_pass(None, None, state))  # type: ignore[arg-type]
    assert state.last_ok is False and state.errors == ["disk full"]
    assert state.last_sync_at is not None
