import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import Any

import firebase_admin
from fastapi import Request, Response
from firebase_admin import auth as firebase_auth
from firebase_admin import credentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.tables import AuthIdentity, AuthSession, User, UserApp

_FIREBASE_APP_NAME = "amo-auth"


class AuthError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message

    def to_detail(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


@dataclass
class VerifiedIdentity:
    identity_uid: str
    provider: str
    provider_user_id: str
    email: str
    email_verified: bool
    display_name: str | None
    photo_url: str | None
    claims: dict[str, Any]


@dataclass
class ActiveUserSession:
    user: User
    providers: list[str]
    expires_at: datetime
    session_row: AuthSession


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def normalize_email(value: str) -> str:
    return value.strip().lower()


def _build_firebase_credentials():
    if settings.identity_platform_service_account_json:
        info = json.loads(settings.identity_platform_service_account_json)
        return credentials.Certificate(info)
    if settings.identity_platform_service_account_path:
        return credentials.Certificate(settings.identity_platform_service_account_path)
    return credentials.ApplicationDefault()


def get_firebase_app():
    try:
        return firebase_admin.get_app(_FIREBASE_APP_NAME)
    except ValueError:
        options = {}
        if settings.identity_platform_project_id:
            options["projectId"] = settings.identity_platform_project_id
        return firebase_admin.initialize_app(
            credential=_build_firebase_credentials(),
            options=options or None,
            name=_FIREBASE_APP_NAME,
        )


def _extract_provider_user_id(
    provider: str,
    claims: dict[str, Any],
    identities: dict[str, Any],
) -> str:
    provider_values = identities.get(provider)
    if isinstance(provider_values, list):
        for item in provider_values:
            text = str(item).strip()
            if text:
                return text
    if provider_values:
        text = str(provider_values).strip()
        if text:
            return text

    for key in ("uid", "user_id", "sub"):
        value = claims.get(key)
        if value:
            return str(value)

    raise AuthError(401, "identity_uid_missing", "Identity token does not include a stable user id.")


def verify_identity_token(id_token: str) -> VerifiedIdentity:
    if not settings.auth_enabled:
        raise AuthError(503, "auth_disabled", "Authentication is disabled.")

    try:
        claims = firebase_auth.verify_id_token(
            id_token,
            check_revoked=False,
            app=get_firebase_app(),
        )
    except Exception as exc:  # noqa: BLE001
        raise AuthError(401, "invalid_identity_token", "Identity token verification failed.") from exc

    email = str(claims.get("email") or "").strip()
    if not email:
        raise AuthError(400, "email_missing", "The identity token does not contain an email address.")

    provider_claims = claims.get("firebase") or {}
    provider = str(provider_claims.get("sign_in_provider") or "unknown").strip() or "unknown"
    identities = provider_claims.get("identities") or {}
    provider_user_id = _extract_provider_user_id(provider, claims, identities)
    email_verified = bool(claims.get("email_verified"))
    if settings.auth_require_verified_email and not email_verified:
        raise AuthError(403, "email_not_verified", "Please verify your email address before signing in.")

    identity_uid = str(claims.get("uid") or claims.get("user_id") or claims.get("sub") or "").strip()
    if not identity_uid:
        raise AuthError(401, "identity_uid_missing", "Identity token does not include a stable user id.")

    return VerifiedIdentity(
        identity_uid=identity_uid,
        provider=provider,
        provider_user_id=provider_user_id,
        email=email,
        email_verified=email_verified,
        display_name=str(claims.get("name") or "").strip() or None,
        photo_url=str(claims.get("picture") or "").strip() or None,
        claims=claims,
    )


async def _list_user_providers(db: AsyncSession, user_id: str) -> list[str]:
    result = await db.scalars(
        select(AuthIdentity.provider)
        .where(AuthIdentity.user_id == user_id)
        .order_by(AuthIdentity.provider.asc())
    )
    return [value for value in result.all() if value]


async def sync_verified_identity(db: AsyncSession, identity: VerifiedIdentity) -> tuple[User, list[str]]:
    normalized_email = normalize_email(identity.email)
    now = utcnow()

    auth_identity = await db.scalar(
        select(AuthIdentity).where(
            AuthIdentity.provider == identity.provider,
            AuthIdentity.provider_user_id == identity.provider_user_id,
        )
    )

    user: User | None = None
    if auth_identity:
        user = await db.get(User, auth_identity.user_id)
    if user is None:
        user = await db.scalar(select(User).where(User.email_normalized == normalized_email))

    if user is None:
        user = User(
            primary_email=identity.email,
            email_normalized=normalized_email,
            email_verified=identity.email_verified,
            display_name=identity.display_name,
            photo_url=identity.photo_url,
            last_login_at=now,
        )
        db.add(user)
        await db.flush()
    else:
        user.primary_email = identity.email
        user.email_normalized = normalized_email
        user.email_verified = identity.email_verified
        user.last_login_at = now
        if identity.display_name:
            user.display_name = identity.display_name
        if identity.photo_url:
            user.photo_url = identity.photo_url

    if not user.is_active:
        raise AuthError(403, "user_disabled", "This account has been disabled.")

    if auth_identity is None:
        auth_identity = AuthIdentity(
            user_id=user.id,
            provider=identity.provider,
            provider_user_id=identity.provider_user_id,
            email=identity.email,
            last_login_at=now,
        )
        db.add(auth_identity)
    else:
        auth_identity.email = identity.email
        auth_identity.last_login_at = now

    user_app = await db.scalar(
        select(UserApp).where(
            UserApp.user_id == user.id,
            UserApp.app_code == settings.app_code,
        )
    )
    if user_app is None:
        db.add(
            UserApp(
                user_id=user.id,
                app_code=settings.app_code,
                last_login_at=now,
            )
        )
    else:
        user_app.last_login_at = now

    await db.flush()
    return user, await _list_user_providers(db, user.id)


def _hash_session_token(raw_token: str) -> str:
    return hmac.new(
        settings.auth_session_secret.encode("utf-8"),
        raw_token.encode("utf-8"),
        sha256,
    ).hexdigest()


def _request_ip_address(request: Request) -> str | None:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip() or None
    if request.client:
        return request.client.host
    return None


def serialize_user(user: User, providers: list[str]) -> dict[str, Any]:
    return {
        "id": user.id,
        "email": user.primary_email,
        "email_verified": user.email_verified,
        "display_name": user.display_name,
        "photo_url": user.photo_url,
        "providers": providers,
    }


async def create_session_record(
    db: AsyncSession,
    *,
    user: User,
    provider: str,
    request: Request,
) -> tuple[str, datetime]:
    raw_session_token = secrets.token_urlsafe(32)
    expires_at = utcnow() + timedelta(days=max(settings.auth_session_ttl_days, 1))
    db.add(
        AuthSession(
            user_id=user.id,
            provider=provider,
            session_token_hash=_hash_session_token(raw_session_token),
            user_agent=request.headers.get("user-agent"),
            ip_address=_request_ip_address(request),
            expires_at=expires_at,
            last_seen_at=utcnow(),
        )
    )
    await db.flush()
    return raw_session_token, expires_at


def attach_session_cookie(response: Response, raw_session_token: str, expires_at: datetime) -> None:
    response.set_cookie(
        key=settings.auth_session_cookie_name,
        value=raw_session_token,
        max_age=settings.auth_cookie_max_age_seconds,
        expires=expires_at,
        httponly=True,
        secure=settings.auth_session_cookie_secure,
        samesite="lax",
        path="/",
        domain=settings.auth_session_cookie_domain,
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.auth_session_cookie_name,
        path="/",
        domain=settings.auth_session_cookie_domain,
        secure=settings.auth_session_cookie_secure,
        samesite="lax",
    )


async def get_active_user_session(db: AsyncSession, request: Request) -> ActiveUserSession | None:
    raw_session_token = request.cookies.get(settings.auth_session_cookie_name)
    if not raw_session_token:
        return None

    session_row = await db.scalar(
        select(AuthSession).where(
            AuthSession.session_token_hash == _hash_session_token(raw_session_token),
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > utcnow(),
        )
    )
    if session_row is None:
        return None

    user = await db.get(User, session_row.user_id)
    if user is None or not user.is_active:
        return None

    session_row.last_seen_at = utcnow()
    providers = await _list_user_providers(db, user.id)
    return ActiveUserSession(
        user=user,
        providers=providers,
        expires_at=session_row.expires_at,
        session_row=session_row,
    )


async def revoke_session(db: AsyncSession, request: Request) -> None:
    raw_session_token = request.cookies.get(settings.auth_session_cookie_name)
    if not raw_session_token:
        return

    session_row = await db.scalar(
        select(AuthSession).where(
            AuthSession.session_token_hash == _hash_session_token(raw_session_token),
            AuthSession.revoked_at.is_(None),
        )
    )
    if session_row is not None:
        session_row.revoked_at = utcnow()
