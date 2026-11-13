# SPDX-License-Identifier: AGPL-3.0-or-later
"""Signing in to the web page, against a fake Immich and a real PostgreSQL."""

import json
from collections.abc import Iterator
from typing import Any

import httpx2
import pytest
from fastapi.testclient import TestClient

from showrunner.api.auth import SESSION_COOKIE, WRITE_PERMISSIONS
from showrunner.app import create_app
from showrunner.config import Settings

APP_KEY = "sync-key"
APP_USER = "f7ec234a-1f0d-4bca-9040-28e639a44668"
OWNER = "7be25f09-c8d5-437a-993a-9cfde9b73b67"
SECRET = "s" * 40


class Immich:
    """Two users: the user of the app (jellyfin@…) and an owner of albums (owner@…)."""

    def __init__(self) -> None:
        self.passwords = {
            "jellyfin@lab.test": ("pass-jf", APP_USER),
            "owner@lab.test": ("pass-o", OWNER),
        }
        self.users = {
            APP_USER: {"id": APP_USER, "name": "jellyfin", "email": "jellyfin@lab.test"},
            OWNER: {"id": OWNER, "name": "Owner", "email": "owner@lab.test"},
        }
        # api key -> (user id, permissions)
        self.keys: dict[str, tuple[str, list[str]]] = {
            APP_KEY: (
                APP_USER,
                ["album.read", "asset.read", "asset.view", "person.read", "user.read"],
            ),
            "owner-key": (OWNER, ["all"]),
            "jf-read-key": (APP_USER, ["user.read"]),
        }
        self.sessions: dict[str, str] = {}
        self.named_keys: dict[str, str] = {}  # key id -> name
        self.created = 0
        self.logged_out: list[str] = []
        self.password_login = True

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        path = request.url.path.removeprefix("/api")
        key = request.headers.get("x-api-key")
        bearer = request.headers.get("authorization", "").removeprefix("Bearer ")
        if path == "/server/version":
            return httpx2.Response(200, json={"major": 3, "minor": 4, "patch": 1})
        if path == "/auth/login":
            if not self.password_login:
                return httpx2.Response(400, json={"message": "Password login disabled"})
            body = json.loads(request.content)
            password, user = self.passwords.get(body["email"], ("", ""))
            if password != body["password"]:
                return httpx2.Response(401, json={"message": "Incorrect email or password"})
            token = f"session-{len(self.sessions)}"
            self.sessions[token] = user
            return httpx2.Response(201, json={"accessToken": token, "userId": user})
        if path == "/auth/logout":
            self.logged_out.append(bearer)
            return httpx2.Response(200, json={})
        if path == "/api-keys" and request.method == "GET":
            return httpx2.Response(
                200,
                json=[{"id": i, "name": n, "permissions": []} for i, n in self.named_keys.items()],
            )
        if path == "/api-keys" and request.method == "POST":
            body = json.loads(request.content)
            self.created += 1
            secret = f"write-key-{self.created}"
            key_id = f"00000000-0000-4000-8000-{self.created:012d}"
            self.named_keys[key_id] = body["name"]
            self.keys[secret] = (self.sessions[bearer], body["permissions"])
            return httpx2.Response(201, json={"secret": secret})
        if path.startswith("/api-keys/") and request.method == "DELETE":
            self.named_keys.pop(path.split("/")[2], None)
            return httpx2.Response(204)
        if key not in self.keys:
            return httpx2.Response(401, json={"message": "Invalid API key"})
        user, permissions = self.keys[key]
        if path == "/users/me":
            return httpx2.Response(200, json=self.users[user])
        if path == "/api-keys/me":
            return httpx2.Response(
                200,
                json={
                    "id": "00000000-0000-4000-8000-000000000000",
                    "name": "k",
                    "permissions": permissions,
                },
            )
        return httpx2.Response(404, json={"message": "not found"})


@pytest.fixture
def immich() -> Immich:
    return Immich()


@pytest.fixture
def client(empty_database: str, immich: Immich) -> Iterator[TestClient]:
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


def code(response: Any) -> str:
    return str(response.json()["code"])


def test_not_signed_in(client: TestClient) -> None:
    response = client.get("/api/auth/me")
    assert response.status_code == 401 and code(response) == "not_authenticated"


def test_password_sign_in_creates_a_write_key_and_keeps_no_password(
    client: TestClient, immich: Immich
) -> None:
    response = client.post(
        "/api/auth/login", json={"email": "jellyfin@lab.test", "password": "pass-jf"}
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"name": "jellyfin", "email": "jellyfin@lab.test", "can_write": True}
    cookie = response.headers["set-cookie"]
    assert SESSION_COOKIE in cookie and "HttpOnly" in cookie and "SameSite=strict" in cookie
    # A key with only the permissions the page needs; the Immich session is closed again.
    assert immich.created == 1
    assert sorted(immich.keys["write-key-1"][1]) == sorted(WRITE_PERMISSIONS)
    assert immich.logged_out == ["session-0"]
    assert client.get("/api/auth/me").json()["name"] == "jellyfin"

    # Signing in again keeps the key that still works.
    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").status_code == 401
    client.post("/api/auth/login", json={"email": "jellyfin@lab.test", "password": "pass-jf"})
    assert immich.created == 1


def test_a_lost_key_is_replaced_and_the_old_one_removed(client: TestClient, immich: Immich) -> None:
    client.post("/api/auth/login", json={"email": "jellyfin@lab.test", "password": "pass-jf"})
    del immich.keys["write-key-1"]  # removed in Immich by hand
    client.post("/api/auth/login", json={"email": "jellyfin@lab.test", "password": "pass-jf"})
    assert immich.created == 2
    # The lost key is removed from Immich before the new one is made.
    assert len(immich.named_keys) == 1


def test_only_the_user_of_the_app_may_sign_in(client: TestClient, immich: Immich) -> None:
    response = client.post(
        "/api/auth/login", json={"email": "owner@lab.test", "password": "pass-o"}
    )
    assert response.status_code == 403 and code(response) == "not_the_app_user"
    assert immich.created == 0
    assert immich.logged_out == ["session-0"]
    response = client.post("/api/auth/login/key", json={"api_key": "owner-key"})
    assert response.status_code == 403 and code(response) == "not_the_app_user"


def test_wrong_password_and_password_sign_in_turned_off(client: TestClient, immich: Immich) -> None:
    response = client.post(
        "/api/auth/login", json={"email": "jellyfin@lab.test", "password": "wrong"}
    )
    assert response.status_code == 401 and code(response) == "immich_invalid_credentials"
    immich.password_login = False
    response = client.post(
        "/api/auth/login", json={"email": "jellyfin@lab.test", "password": "pass-jf"}
    )
    assert code(response) == "immich_password_login_failed"


def test_sign_in_with_a_key(client: TestClient) -> None:
    response = client.post("/api/auth/login/key", json={"api_key": "jf-read-key"})
    assert response.status_code == 200
    assert response.json()["can_write"] is False  # the page then only shows, it does not change
    response = client.post("/api/auth/login/key", json={"api_key": "no-such-key"})
    assert response.status_code == 401 and code(response) == "immich_invalid_api_key"


def test_without_a_secret_key_nobody_signs_in(empty_database: str, immich: Immich) -> None:
    settings = Settings(
        _env_file=None,
        immich_url="http://immich.test",
        immich_api_key=APP_KEY,
        database_url=empty_database,
    )
    app = create_app(
        settings, run_scheduler=False, immich_transport=httpx2.MockTransport(immich.handler)
    )
    with TestClient(app) as c:
        response = c.post(
            "/api/auth/login", json={"email": "jellyfin@lab.test", "password": "pass-jf"}
        )
    assert response.status_code == 503 and code(response) == "secret_key_missing"


def test_health_needs_no_sign_in(client: TestClient) -> None:
    assert client.get("/api/health").status_code == 200
