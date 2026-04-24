from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.connections import get_pg
from app.schemas.responses import AuthSessionCreateRequest, AuthSessionOut, AuthUserOut
from app.services import auth as auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


def _raise_auth_error(exc: auth_service.AuthError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.to_detail())


@router.get("/session", response_model=AuthSessionOut)
async def get_session(
    request: Request,
    db: AsyncSession = Depends(get_pg),
):
    active_session = await auth_service.get_active_user_session(db, request)
    await db.commit()
    if active_session is None:
        return AuthSessionOut(authenticated=False)

    return AuthSessionOut(
        authenticated=True,
        session_expires_at=active_session.expires_at,
        user=AuthUserOut(**auth_service.serialize_user(active_session.user, active_session.providers)),
    )


@router.post("/session", response_model=AuthSessionOut)
async def create_session(
    body: AuthSessionCreateRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_pg),
):
    try:
        identity = auth_service.verify_identity_token(body.id_token)
        user, providers = await auth_service.sync_verified_identity(db, identity)
        raw_session_token, expires_at = await auth_service.create_session_record(
            db,
            user=user,
            provider=identity.provider,
            request=request,
        )
        await db.commit()
        auth_service.attach_session_cookie(response, raw_session_token, expires_at)
        return AuthSessionOut(
            authenticated=True,
            session_expires_at=expires_at,
            user=AuthUserOut(**auth_service.serialize_user(user, providers)),
        )
    except auth_service.AuthError as exc:
        await db.rollback()
        _raise_auth_error(exc)


@router.delete("/session", response_model=AuthSessionOut)
async def delete_session(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_pg),
):
    await auth_service.revoke_session(db, request)
    await db.commit()
    auth_service.clear_session_cookie(response)
    return AuthSessionOut(authenticated=False)


@router.post("/logout", response_model=AuthSessionOut)
async def logout(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_pg),
):
    await auth_service.revoke_session(db, request)
    await db.commit()
    auth_service.clear_session_cookie(response)
    return AuthSessionOut(authenticated=False)
