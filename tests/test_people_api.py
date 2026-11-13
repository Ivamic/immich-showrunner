# SPDX-License-Identifier: AGPL-3.0-or-later
"""The people page: names written to Immich for the user of the app only, descriptions kept by the
app, and invitations accepted only when nothing is lost."""

import json
from collections.abc import Iterator
from typing import Any
from uuid import UUID

import httpx2
import pytest
from fastapi.testclient import TestClient

from showrunner.app import create_app
from showrunner.config import Settings
from test_auth import APP_KEY, APP_USER, OWNER, SECRET, Immich

ANNA = "9a47f746-0000-4000-8000-000000000001"
DAD = "9a47f746-0000-4000-8000-000000000002"
OWN_GROUP = "1e6bede3-2593-4b09-b893-30370f7baacb"
OTHER_GROUP = "7d7f4d6a-dec4-48f9-b427-1984326009a7"
INVITATION = "4809a034-1b27-4dc4-a9e4-cb42ad92ba48"


class PeopleImmich(Immich):
    def __init__(self) -> None:
        super().__init__()
        self.people: dict[str, dict[str, Any]] = {
            ANNA: {
                "id": ANNA,
                "name": "",
                "isHidden": False,
                "otherPeople": [{"sharedById": OWNER, "name": "мама"}],
                "sharedBy": [{"id": OWNER, "name": "Owner"}],
            },
        }
        self.renames: list[dict[str, Any]] = []
        self.group_members = {OWN_GROUP: [APP_USER, OWNER], OTHER_GROUP: [OWNER]}
        self.my_group = OWN_GROUP
        self.requests = [{"id": INVITATION, "clusterGroupId": OTHER_GROUP, "userId": APP_USER}]
        self.accepted: list[str] = []

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        path = request.url.path.removeprefix("/api")
        key = request.headers.get("x-api-key")
        if path == "/users/me" and key in self.keys:
            user = dict(self.users[self.keys[key][0]])
            if user["id"] == APP_USER:
                user["clusterGroupId"] = self.my_group
            return httpx2.Response(200, json=user)
        if path == "/people" and request.method == "GET":
            return httpx2.Response(
                200, json={"people": list(self.people.values()), "total": 1, "hasNextPage": False}
            )
        if path.startswith("/people/") and path.endswith("/thumbnail"):
            return httpx2.Response(200, content=b"face", headers={"content-type": "image/jpeg"})
        if path.startswith("/people/") and request.method == "PUT":
            body = json.loads(request.content)
            self.renames.append({"key": key, **body})
            self.people[path.split("/")[2]]["name"] = body["name"]
            return httpx2.Response(200, json={})
        if path == "/cluster-groups/requests":
            return httpx2.Response(200, json=self.requests)
        if path.startswith("/cluster-groups/") and path.endswith("/users"):
            members = self.group_members[path.split("/")[2]]
            return httpx2.Response(200, json=[self.users[m] for m in members])
        if path.startswith("/cluster-groups/requests/") and path.endswith("/accept"):
            self.accepted.append(path.split("/")[3])
            return httpx2.Response(204)
        return super().handler(request)


@pytest.fixture
def immich() -> PeopleImmich:
    return PeopleImmich()


@pytest.fixture
def client(empty_database: str, immich: PeopleImmich) -> Iterator[TestClient]:
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
    assert response.status_code == 200, response.text


def test_people_list(client: TestClient) -> None:
    sign_in(client)
    data = client.get("/api/people").json()
    assert data["people"] == [
        {"id": ANNA, "name": "", "owner_names": ["мама"], "shared_by": ["Owner"], "description": ""}
    ]
    assert data["can_write"] is True
    assert data["group"] == ["Owner"]
    assert data["invitations"] == [{"id": INVITATION, "from_users": ["Owner"]}]
    assert data["can_accept"] is False


def test_a_name_is_written_for_the_user_of_the_app_only(
    client: TestClient, immich: PeopleImmich
) -> None:
    sign_in(client)
    response = client.patch(f"/api/people/{ANNA}", json={"name": "  Anna Ivanova "})
    assert response.status_code == 200, response.text
    assert immich.renames == [{"key": "write-key-1", "name": "Anna Ivanova", "userId": APP_USER}]
    assert client.app.state.status.wake.is_set()  # type: ignore[attr-defined]
    # The read-only key of the sync is never used to write.
    assert all(r["key"] != APP_KEY for r in immich.renames)


def test_description_is_kept_by_the_app(client: TestClient, immich: PeopleImmich) -> None:
    sign_in(client)
    client.patch(f"/api/people/{ANNA}", json={"description": "Grandmother. Loves apples."})
    assert client.get("/api/people").json()["people"][0]["description"] == (
        "Grandmother. Loves apples."
    )
    assert immich.renames == []  # nothing written to Immich
    client.patch(f"/api/people/{ANNA}", json={"description": ""})
    assert client.get("/api/people").json()["people"][0]["description"] == ""


def test_an_invitation_is_not_accepted_when_people_would_be_lost(
    client: TestClient, immich: PeopleImmich
) -> None:
    sign_in(client)
    response = client.post(f"/api/people/invitations/{INVITATION}/accept")
    assert response.status_code == 409 and response.json()["code"] == "already_in_a_group"
    assert immich.accepted == []


def test_an_invitation_is_accepted_when_alone(client: TestClient, immich: PeopleImmich) -> None:
    immich.group_members[OWN_GROUP] = [APP_USER]
    sign_in(client)
    assert client.get("/api/people").json()["can_accept"] is True
    response = client.post(f"/api/people/invitations/{INVITATION}/accept")
    assert response.status_code == 200
    assert immich.accepted == [INVITATION]


def test_signed_in_with_a_read_only_key_the_page_only_shows(
    client: TestClient, immich: PeopleImmich
) -> None:
    assert client.post("/api/auth/login/key", json={"api_key": "jf-read-key"}).status_code == 200
    data = client.get("/api/people").json()
    assert data["can_write"] is False and data["group"] is None
    response = client.patch(f"/api/people/{ANNA}", json={"name": "Anna"})
    assert response.status_code == 403 and response.json()["code"] == "cannot_write"
    assert immich.renames == []


def test_face(client: TestClient) -> None:
    sign_in(client)
    response = client.get(f"/api/people/{UUID(ANNA)}/face")
    assert response.status_code == 200 and response.content == b"face"
