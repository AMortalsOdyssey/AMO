import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.connections import get_pg
from app.schemas.responses import (
    BillingCatalogOut,
    BillingCheckoutCreateRequest,
    BillingCheckoutDetailOut,
    BillingCheckoutOut,
    BillingMockCompleteRequest,
    BillingProductOut,
    BillingProductUpdateRequest,
    BillingSummaryOut,
    BillingWebhookAckOut,
)
from app.services import auth as auth_service
from app.services import billing as billing_service

router = APIRouter(prefix="/billing", tags=["billing"])
log = logging.getLogger("amo.billing.api")


def _raise_billing_error(exc: billing_service.BillingError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.to_detail())


def _build_catalog_response(
    *,
    product_payload: dict,
    summary: billing_service.BillingSummary,
) -> BillingCatalogOut:
    return BillingCatalogOut(
        provider="creem",
        mode=settings.billing_checkout_mode,
        support_email=settings.support_email,
        free_allowance_credits=settings.billing_free_credits,
        pack=BillingProductOut(**product_payload),
        summary=BillingSummaryOut(**summary.to_dict()),
    )


async def _resolve_billing_client(
    *,
    db: AsyncSession,
    request: Request,
    x_amo_client_token: str | None,
    require_user: bool = False,
) -> tuple[str, str | None]:
    active_session = await auth_service.get_active_user_session(db, request)
    if active_session is not None:
        return (
            billing_service.build_authenticated_client_token(active_session.user.id),
            active_session.user.primary_email,
        )

    if require_user:
        raise HTTPException(
            status_code=401,
            detail={
                "code": "login_required",
                "message": "Please sign in before purchasing AMO credits.",
            },
        )

    return billing_service.require_client_token(x_amo_client_token), None


@router.get("/catalog", response_model=BillingCatalogOut)
async def get_catalog(
    request: Request,
    x_amo_client_token: str | None = Header(default=None, alias="X-AMO-Client-Token"),
    db: AsyncSession = Depends(get_pg),
):
    try:
        client_token, _ = await _resolve_billing_client(
            db=db,
            request=request,
            x_amo_client_token=x_amo_client_token,
        )
        product = await billing_service.get_product(db)
        summary = await billing_service.get_billing_summary(db, client_token)
        await db.commit()
        return _build_catalog_response(
            product_payload=billing_service.serialize_product(product),
            summary=summary,
        )
    except billing_service.BillingError as exc:
        await db.rollback()
        _raise_billing_error(exc)


@router.get("/me", response_model=BillingSummaryOut)
async def get_me(
    request: Request,
    x_amo_client_token: str | None = Header(default=None, alias="X-AMO-Client-Token"),
    db: AsyncSession = Depends(get_pg),
):
    try:
        client_token, _ = await _resolve_billing_client(
            db=db,
            request=request,
            x_amo_client_token=x_amo_client_token,
        )
        summary = await billing_service.get_billing_summary(db, client_token)
        await db.commit()
        return BillingSummaryOut(**summary.to_dict())
    except billing_service.BillingError as exc:
        await db.rollback()
        _raise_billing_error(exc)


@router.post("/checkouts", response_model=BillingCheckoutOut)
async def create_checkout(
    request: Request,
    body: BillingCheckoutCreateRequest,
    x_amo_client_token: str | None = Header(default=None, alias="X-AMO-Client-Token"),
    db: AsyncSession = Depends(get_pg),
):
    try:
        client_token, account_email = await _resolve_billing_client(
            db=db,
            request=request,
            x_amo_client_token=x_amo_client_token,
            require_user=True,
        )
        checkout = await billing_service.create_checkout(db, client_token, email=account_email or body.email)
        await db.commit()
        return BillingCheckoutOut(**billing_service.serialize_checkout(checkout))
    except billing_service.BillingError as exc:
        await db.rollback()
        _raise_billing_error(exc)


@router.get("/checkouts/{request_id}", response_model=BillingCheckoutDetailOut)
async def get_checkout(
    request: Request,
    request_id: str,
    x_amo_client_token: str | None = Header(default=None, alias="X-AMO-Client-Token"),
    db: AsyncSession = Depends(get_pg),
):
    try:
        client_token, _ = await _resolve_billing_client(
            db=db,
            request=request,
            x_amo_client_token=x_amo_client_token,
            require_user=True,
        )
        checkout = await billing_service.get_checkout_for_client(db, client_token, request_id)
        summary = await billing_service.get_billing_summary(db, client_token)
        await db.commit()
        return BillingCheckoutDetailOut(
            checkout=BillingCheckoutOut(**billing_service.serialize_checkout(checkout)),
            summary=BillingSummaryOut(**summary.to_dict()),
        )
    except billing_service.BillingError as exc:
        await db.rollback()
        _raise_billing_error(exc)


@router.post("/checkouts/{request_id}/mock-complete", response_model=BillingCheckoutDetailOut)
async def complete_mock_checkout(
    request: Request,
    request_id: str,
    body: BillingMockCompleteRequest,
    x_amo_client_token: str | None = Header(default=None, alias="X-AMO-Client-Token"),
    db: AsyncSession = Depends(get_pg),
):
    try:
        client_token, _ = await _resolve_billing_client(
            db=db,
            request=request,
            x_amo_client_token=x_amo_client_token,
            require_user=True,
        )
        checkout, summary = await billing_service.complete_mock_checkout(
            db,
            client_token,
            request_id,
            outcome=body.outcome,
        )
        resolved_summary = summary or await billing_service.get_billing_summary(db, client_token)
        await db.commit()
        return BillingCheckoutDetailOut(
            checkout=BillingCheckoutOut(**billing_service.serialize_checkout(checkout)),
            summary=BillingSummaryOut(**resolved_summary.to_dict()),
        )
    except billing_service.BillingError as exc:
        await db.rollback()
        _raise_billing_error(exc)


@router.put("/products/{product_key}", response_model=BillingProductOut)
async def update_product(
    product_key: str,
    body: BillingProductUpdateRequest,
    x_amo_admin_key: str | None = Header(default=None, alias="X-AMO-Admin-Key"),
    db: AsyncSession = Depends(get_pg),
):
    try:
        billing_service.require_admin_key(x_amo_admin_key)
        product = await billing_service.update_product(
            db,
            product_key,
            display_name=body.display_name,
            description=body.description,
            price_cents=body.price_cents,
            currency=body.currency,
            credits_per_unit=body.credits_per_unit,
            is_active=body.is_active,
            creem_product_id=body.creem_product_id,
        )
        await db.commit()
        return BillingProductOut(**billing_service.serialize_product(product))
    except billing_service.BillingError as exc:
        await db.rollback()
        _raise_billing_error(exc)


@router.post("/webhooks/creem", response_model=BillingWebhookAckOut)
async def creem_webhook(
    request: Request,
    creem_signature: str | None = Header(default=None, alias="creem-signature"),
    db: AsyncSession = Depends(get_pg),
):
    body = await request.body()
    if not billing_service.verify_creem_signature(body, creem_signature, settings.creem_webhook_secret):
        raise HTTPException(
            status_code=401,
            detail={"code": "invalid_creem_signature", "message": "Webhook signature verification failed."},
        )

    try:
        event_id, event_type, payload = billing_service.parse_webhook_payload(body)
        status = "ignored"
        if event_type == "checkout.completed":
            await billing_service.process_checkout_completed(
                db,
                event_id=event_id,
                event_type=event_type,
                payload=payload,
                provider="creem",
            )
            status = "processed"
        elif event_type == "refund.created":
            await billing_service.process_refund_created(
                db,
                event_id=event_id,
                event_type=event_type,
                payload=payload,
                provider="creem",
            )
            status = "processed"
        else:
            log.info("ignored creem event type=%s", event_type)
        await db.commit()
        return BillingWebhookAckOut(event_id=event_id, event_type=event_type, status=status)
    except billing_service.BillingError as exc:
        await db.rollback()
        _raise_billing_error(exc)
