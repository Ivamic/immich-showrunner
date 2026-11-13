# SPDX-License-Identifier: AGPL-3.0-or-later
"""People on the page: the people shared with the user of the app, their names for Jellyfin and
their descriptions, and the invitations into a cluster group.

Reading is done with the read-only key of the sync. The two things that change Immich, a name and
accepting an invitation, are done with the key the app keeps for the signed-in user, and only on
its action. A name is always written for that user only, never for the owner of the person."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from showrunner.api.auth import (
    BoxDep,
    CurrentUser,
    DbDep,
    ImmichFactory,
    ImmichFactoryDep,
    SettingsDep,
    stored_write_key,
)
from showrunner.api.errors import ApiError
from showrunner.crypto import SecretBox
from showrunner.immich.client import (
    ImmichAuthError,
    ImmichClient,
    ImmichError,
    ImmichPermissionError,
    ImmichUnreachableError,
)
from showrunner.scheduler import State
from showrunner.store.models import UiUser
from showrunner.store.registry import Registry

router = APIRouter(prefix="/people")


class PersonOut(BaseModel):
    id: UUID
    # The name for Jellyfin: the one the user of the app gave. Empty: not in Jellyfin.
    name: str
    # What the owners call this person, for recognising them.
    owner_names: list[str]
    shared_by: list[str]
    description: str


class InvitationOut(BaseModel):
    id: UUID
    # The members of the group that invites.
    from_users: list[str]


class PeopleOut(BaseModel):
    people: list[PersonOut]
    # Whether the page can name people and accept invitations for the user.
    can_write: bool
    # Members of the cluster group of the user of the app, without it; None when not known.
    group: list[str] | None
    invitations: list[InvitationOut]
    # The user is alone in its group, so accepting an invitation loses nothing.
    can_accept: bool


class PersonPatch(BaseModel):
    """A field that is sent changes. An empty name takes the person out of Jellyfin."""

    name: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=5000)


def immich_errors(exc: ImmichError) -> ApiError:
    if isinstance(exc, ImmichUnreachableError):
        return ApiError(502, "immich_unreachable")
    if isinstance(exc, ImmichAuthError | ImmichPermissionError):
        # The key from the last sign-in has lost permissions, or lacks new ones.
        return ApiError(403, "sign_in_again")
    return ApiError(502, "immich_error")


@asynccontextmanager
async def writer(
    user: UiUser, box: SecretBox, immich: ImmichFactory
) -> AsyncIterator[ImmichClient]:
    key = stored_write_key(user, box) if user.can_write else None
    if key is None:
        raise ApiError(403, "cannot_write")
    async with immich(key) as client:
        yield client


@router.get("")
async def list_people(
    user: CurrentUser,
    db: DbDep,
    box: BoxDep,
    settings: SettingsDep,
    immich: ImmichFactoryDep,
) -> PeopleOut:
    try:
        async with immich(settings.immich_api_key.get_secret_value()) as client:
            people = await client.people()
    except ImmichError as exc:
        raise immich_errors(exc) from exc
    descriptions = await Registry(db).descriptions()

    group: list[str] | None = None
    invitations: list[InvitationOut] = []
    can_accept = False
    key = stored_write_key(user, box) if user.can_write else None
    if key is not None:
        try:
            async with immich(key) as client:
                me = await client.current_user()
                if me.cluster_group_id is not None:
                    members = await client.group_users(me.cluster_group_id)
                    group = [u.name for u in members if u.id != me.id]
                    can_accept = not group
                for request in await client.group_requests():
                    users = await client.group_users(request.cluster_group_id)
                    invitations.append(
                        InvitationOut(id=request.id, from_users=[u.name for u in users])
                    )
        except ImmichError as exc:
            raise immich_errors(exc) from exc

    shown = [p for p in people if not p.is_hidden and (p.name or p.shared_by)]
    return PeopleOut(
        people=sorted(
            (
                PersonOut(
                    id=p.id,
                    name=p.name,
                    owner_names=[o.name for o in p.other_people if o.name],
                    shared_by=[u.name for u in p.shared_by],
                    description=descriptions.get(p.id, ""),
                )
                for p in shown
            ),
            key=lambda p: (not p.name, p.name.casefold()),
        ),
        can_write=user.can_write,
        group=group,
        invitations=invitations,
        can_accept=can_accept,
    )


@router.patch("/{person_id}")
async def edit_person(
    person_id: UUID,
    body: PersonPatch,
    request: Request,
    user: CurrentUser,
    db: DbDep,
    box: BoxDep,
    immich: ImmichFactoryDep,
) -> dict[str, bool]:
    sent = body.model_fields_set
    if "name" in sent:
        try:
            async with writer(user, box, immich) as client:
                await client.rename_person(
                    person_id, (body.name or "").strip(), user.immich_user_id
                )
        except ImmichError as exc:
            raise immich_errors(exc) from exc
    if "description" in sent:
        registry = Registry(db)
        await registry.set_description(person_id, body.description)
        await registry.commit()
    state: State = request.app.state.status
    state.request()
    return {"saved": True}


@router.post("/invitations/{request_id}/accept")
async def accept_invitation(
    request_id: UUID,
    request: Request,
    user: CurrentUser,
    box: BoxDep,
    immich: ImmichFactoryDep,
) -> dict[str, bool]:
    try:
        async with writer(user, box, immich) as client:
            me = await client.current_user()
            if me.cluster_group_id is not None:
                members = await client.group_users(me.cluster_group_id)
                if any(u.id != me.id for u in members):
                    # Joining another group takes the user out of this one, and the people of
                    # its members are lost (checked on Immich 3.4).
                    raise ApiError(409, "already_in_a_group")
            await client.accept_group_request(request_id)
    except ImmichError as exc:
        raise immich_errors(exc) from exc
    state: State = request.app.state.status
    state.request()
    return {"accepted": True}


@router.get("/{person_id}/face")
async def face(
    person_id: UUID, user: CurrentUser, settings: SettingsDep, immich: ImmichFactoryDep
) -> Response:
    try:
        async with immich(settings.immich_api_key.get_secret_value()) as client:
            content = await client.person_picture(person_id)
    except ImmichError as exc:
        raise ApiError(404, "picture_not_found") from exc
    return Response(
        content=content, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"}
    )
