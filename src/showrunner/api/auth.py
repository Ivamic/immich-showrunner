# SPDX-License-Identifier: AGPL-3.0-or-later
"""Signing in to the web page.

Only the Immich user of the app may sign in: the owner of the API key the sync reads with.

With the email and password of that user, the app checks them with Immich, opens a short Immich
session and creates (or keeps) its own Immich key with the few permissions that what the user
does on the page needs: naming people and accepting invitations. The password is never stored;
the key is stored encrypted. The sync never uses that key: it reads with its own, read-only one.

An API key can be given instead, for an Immich that signs in only through OAuth. The page can
then change things in Immich only if that key has the permissions."""

import hashlib
import logging
import secrets
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Cookie, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from showrunner.api.errors import ApiError
from showrunner.config import Settings
from showrunner.crypto import SecretBox, hash_token
from showrunner.immich.client import (
    ImmichAuthError,
    ImmichClient,
    ImmichError,
    ImmichUnreachableError,
)
from showrunner.immich.models import ImmichUser
from showrunner.store.models import UiSession, UiUser

log = logging.getLogger(__name__)

SESSION_COOKIE = "showrunner_session"
KEY_NAME_PREFIX = "immich-showrunner"
# What the page does in Immich, and nothing else.
WRITE_PERMISSIONS = (
    "clusterGroupRequest.create",
    "clusterGroupRequest.read",
    "person.read",
    "person.update",
    "user.read",
)
SUPPORTED_MAJOR = 3
# Sessions are extended at most this often, to avoid a database write on every request.
EXTEND_SESSION_AFTER = timedelta(days=1)

ImmichFactory = Callable[[str | None], ImmichClient]


# --- dependencies -----------------------------------------------------------------------------


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


async def db_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.sessions() as session:
        yield session


def get_immich_factory(request: Request) -> ImmichFactory:
    """Makes Immich clients for a key, or without one; tests plug in a fake Immich here."""
    settings = get_settings(request)
    transport = getattr(request.app.state, "immich_transport", None)

    def make(api_key: str | None) -> ImmichClient:
        return ImmichClient(settings.immich_url, api_key, transport=transport)

    return make


def get_box(settings: Annotated[Settings, Depends(get_settings)]) -> SecretBox:
    if settings.secret_key is None:
        raise ApiError(503, "secret_key_missing")
    return SecretBox(settings.secret_key.get_secret_value())


SettingsDep = Annotated[Settings, Depends(get_settings)]
DbDep = Annotated[AsyncSession, Depends(db_session)]
ImmichFactoryDep = Annotated[ImmichFactory, Depends(get_immich_factory)]
BoxDep = Annotated[SecretBox, Depends(get_box)]


async def current_user(
    db: DbDep, token: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None
) -> UiUser:
    if not token:
        raise ApiError(401, "not_authenticated")
    user = await db.scalar(
        select(UiUser)
        .join(UiSession, UiSession.immich_user_id == UiUser.immich_user_id)
        .where(UiSession.token_hash == hash_token(token))
        .where(UiSession.expires_at > datetime.now(UTC))
    )
    if user is None:
        raise ApiError(401, "not_authenticated")
    return user


CurrentUser = Annotated[UiUser, Depends(current_user)]


# --- the steps of signing in ------------------------------------------------------------------


@dataclass(frozen=True)
class Verified:
    user: ImmichUser
    write_key: str
    can_write: bool


async def app_user_id(immich: ImmichFactory, settings: Settings) -> UUID:
    """The owner of the key the sync reads with: the only user who may sign in."""
    async with immich(settings.immich_api_key.get_secret_value()) as client:
        return (await client.current_user()).id


async def check_version(client: ImmichClient) -> None:
    version = await client.server_version()
    if version.major != SUPPORTED_MAJOR:
        raise ApiError(400, "immich_unsupported_version", version=str(version))


def key_name(secret_key: str) -> str:
    """Tells the keys of installations that share one Immich apart."""
    tag = hashlib.sha256(b"api-key-name:" + secret_key.encode()).hexdigest()[:8]
    return f"{KEY_NAME_PREFIX} {tag}"


async def key_can_write(client: ImmichClient) -> bool:
    info = await client.api_key_info()
    return "all" in info.permissions or set(WRITE_PERMISSIONS) <= set(info.permissions)


async def with_password(
    immich: ImmichFactory,
    settings: Settings,
    box: SecretBox,
    stored_key: str | None,
    email: str,
    password: str,
) -> Verified:
    try:
        async with immich(None) as client:
            await check_version(client)
            try:
                login = await client.login(email, password)
            except ImmichAuthError as exc:
                raise ApiError(401, "immich_invalid_credentials") from exc
            except ImmichError as exc:
                # For example, password sign-in is turned off in Immich (OAuth only).
                raise ApiError(400, "immich_password_login_failed") from exc
            try:
                if login.user_id != await app_user_id(immich, settings):
                    raise ApiError(403, "not_the_app_user")
                key = await _usable_key(immich, stored_key)
                if key is None:
                    assert settings.secret_key is not None
                    name = key_name(settings.secret_key.get_secret_value())
                    for old in await client.api_keys(login.access_token):
                        if old.name == name:  # its secret is lost, it is of no use
                            await client.delete_api_key(login.access_token, old.id)
                    key = await client.create_api_key(
                        login.access_token, name, sorted(WRITE_PERMISSIONS)
                    )
                async with immich(key) as keyed:
                    user = await keyed.current_user()
            finally:
                try:
                    await client.logout(login.access_token)
                except ImmichError as exc:
                    log.warning("could not close the Immich session: %s", exc)
    except ImmichUnreachableError as exc:
        raise ApiError(502, "immich_unreachable") from exc
    except ImmichError as exc:
        raise ApiError(502, "immich_error") from exc
    return Verified(user, key, can_write=True)


async def with_api_key(immich: ImmichFactory, settings: Settings, api_key: str) -> Verified:
    try:
        async with immich(api_key) as client:
            await check_version(client)
            try:
                user = await client.current_user()
            except ImmichAuthError as exc:
                raise ApiError(401, "immich_invalid_api_key") from exc
            if user.id != await app_user_id(immich, settings):
                raise ApiError(403, "not_the_app_user")
            can_write = await key_can_write(client)
    except ImmichUnreachableError as exc:
        raise ApiError(502, "immich_unreachable") from exc
    except ImmichError as exc:
        raise ApiError(502, "immich_error") from exc
    return Verified(user, api_key, can_write)


async def _usable_key(immich: ImmichFactory, stored_key: str | None) -> str | None:
    """The key kept from an earlier sign-in, if Immich still takes it with the permissions."""
    if stored_key is None:
        return None
    async with immich(stored_key) as client:
        try:
            return stored_key if await key_can_write(client) else None
        except ImmichAuthError:
            return None


async def open_session(
    db: AsyncSession, box: SecretBox, verified: Verified, ttl: timedelta
) -> tuple[UiUser, str]:
    now = datetime.now(UTC)
    user = await db.get(UiUser, verified.user.id)
    if user is None:
        user = UiUser(immich_user_id=verified.user.id)
        db.add(user)
    user.name = verified.user.name
    user.email = verified.user.email
    user.write_key_encrypted = box.encrypt(verified.write_key)
    user.can_write = verified.can_write
    user.last_login_at = now
    await db.flush()
    token = secrets.token_urlsafe(32)
    db.add(
        UiSession(
            token_hash=hash_token(token), immich_user_id=user.immich_user_id, expires_at=now + ttl
        )
    )
    await db.commit()
    return user, token


def stored_write_key(user: UiUser, box: SecretBox) -> str | None:
    if user.write_key_encrypted is None:
        return None
    try:
        return box.decrypt(user.write_key_encrypted)
    except ValueError:  # the secret key of the installation was changed
        return None


def set_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.session_ttl_days * 86400,
        httponly=True,
        samesite="strict",
        secure=settings.cookie_secure,
        path="/",
    )


# --- endpoints --------------------------------------------------------------------------------

router = APIRouter(prefix="/auth")


class PasswordLogin(BaseModel):
    email: str = Field(min_length=1, max_length=320)
    password: str = Field(min_length=1, max_length=1000)


class KeyLogin(BaseModel):
    api_key: str = Field(min_length=1, max_length=200)


class Me(BaseModel):
    name: str
    email: str
    # Whether the page can change things in Immich for the user (names of people, invitations).
    can_write: bool

    @classmethod
    def of(cls, user: UiUser) -> "Me":
        return cls(name=user.name, email=user.email, can_write=user.can_write)


@router.post("/login")
async def login(
    body: PasswordLogin,
    response: Response,
    settings: SettingsDep,
    db: DbDep,
    box: BoxDep,
    immich: ImmichFactoryDep,
) -> Me:
    previous = None
    known = await db.scalar(select(UiUser).where(UiUser.email == body.email.strip()))
    if known is not None:
        previous = stored_write_key(known, box)
    verified = await with_password(
        immich, settings, box, previous, body.email.strip(), body.password
    )
    user, token = await open_session(db, box, verified, timedelta(days=settings.session_ttl_days))
    set_cookie(response, token, settings)
    return Me.of(user)


@router.post("/login/key")
async def login_with_key(
    body: KeyLogin,
    response: Response,
    settings: SettingsDep,
    db: DbDep,
    box: BoxDep,
    immich: ImmichFactoryDep,
) -> Me:
    verified = await with_api_key(immich, settings, body.api_key.strip())
    user, token = await open_session(db, box, verified, timedelta(days=settings.session_ttl_days))
    set_cookie(response, token, settings)
    return Me.of(user)


@router.post("/logout", status_code=204)
async def logout(
    response: Response,
    db: DbDep,
    token: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> None:
    if token:
        await db.execute(delete(UiSession).where(UiSession.token_hash == hash_token(token)))
        await db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/me")
async def me(
    user: CurrentUser,
    response: Response,
    settings: SettingsDep,
    db: DbDep,
    token: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> Me:
    """The page asks this when it starts, which also keeps the session alive (sliding expiry)."""
    assert token is not None
    session = await db.get(UiSession, hash_token(token))
    ttl = timedelta(days=settings.session_ttl_days)
    now = datetime.now(UTC)
    if session is not None and session.expires_at <= now + ttl - EXTEND_SESSION_AFTER:
        session.expires_at = now + ttl
        await db.commit()
        set_cookie(response, token, settings)
    return Me.of(user)
