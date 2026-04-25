from __future__ import annotations

import hashlib
import hmac
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.tables import (
    BillingCheckout,
    BillingCustomer,
    BillingProduct,
    BillingWebhookEvent,
    CreditLedgerEntry,
)

log = logging.getLogger("amo.billing")


class BillingError(Exception):
    def __init__(self, message: str, *, code: str, status_code: int, extra: dict | None = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.extra = extra or {}

    def to_detail(self) -> dict[str, Any]:
        detail = {"code": self.code, "message": self.message}
        detail.update(self.extra)
        return detail


def require_client_token(client_token: str | None) -> str:
    normalized = (client_token or "").strip()
    if not normalized:
        raise BillingError(
            "Missing AMO client token. Refresh the page and try again.",
            code="missing_client_token",
            status_code=400,
        )
    if len(normalized) > 96:
        raise BillingError(
            "Client token is invalid.",
            code="invalid_client_token",
            status_code=400,
        )
    return normalized


def build_authenticated_client_token(user_id: str) -> str:
    normalized = str(user_id or "").strip()
    if not normalized:
        raise BillingError(
            "Missing AMO user id.",
            code="missing_user_id",
            status_code=401,
        )
    return require_client_token(f"user:{normalized}")


def require_admin_key(admin_key: str | None) -> None:
    expected = (settings.billing_admin_key or "").strip()
    if not expected or expected != (admin_key or "").strip():
        raise BillingError(
            "Admin access is not configured for billing product management.",
            code="admin_auth_failed",
            status_code=403,
        )


def verify_creem_signature(payload: bytes, signature: str | None, secret: str | None) -> bool:
    if not signature or not secret:
        return False
    expected = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature.strip(), expected)


def _as_positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _object_id(value: Any) -> str | None:
    if isinstance(value, dict):
        raw = value.get("id")
    else:
        raw = value
    if raw is None:
        return None
    normalized = str(raw).strip()
    return normalized or None


def extract_refund_lookup(payload: dict[str, Any]) -> dict[str, Any]:
    object_data = payload.get("object") if isinstance(payload.get("object"), dict) else {}
    transaction = object_data.get("transaction") if isinstance(object_data.get("transaction"), dict) else {}
    metadata = object_data.get("metadata") if isinstance(object_data.get("metadata"), dict) else {}
    transaction_metadata = transaction.get("metadata") if isinstance(transaction.get("metadata"), dict) else {}

    order_ref = object_data.get("order") or transaction.get("order")
    checkout_ref = object_data.get("checkout") or transaction.get("checkout")

    return {
        "refund_id": _object_id(object_data.get("id")),
        "request_id": _object_id(
            object_data.get("request_id")
            or transaction.get("request_id")
            or metadata.get("request_id")
            or transaction_metadata.get("request_id")
        ),
        "checkout_id": _object_id(object_data.get("checkout_id") or transaction.get("checkout_id") or checkout_ref),
        "order_id": _object_id(object_data.get("order_id") or transaction.get("order_id") or order_ref),
        "refund_amount_cents": _as_positive_int(
            object_data.get("refund_amount") or object_data.get("amount") or object_data.get("amount_refunded")
        ),
        "transaction_amount_cents": _as_positive_int(transaction.get("amount")),
        "transaction_amount_paid_cents": _as_positive_int(transaction.get("amount_paid")),
        "transaction_status": str(transaction.get("status") or object_data.get("status") or "").strip(),
    }


def calculate_refunded_credits(
    *,
    checkout_amount_cents: int,
    credits_to_grant: int,
    refund_amount_cents: int | None = None,
    transaction_amount_cents: int | None = None,
    transaction_amount_paid_cents: int | None = None,
    transaction_status: str | None = None,
) -> int:
    if credits_to_grant <= 0:
        return 0

    basis = next(
        (
            value
            for value in (
                transaction_amount_paid_cents,
                transaction_amount_cents,
                checkout_amount_cents,
            )
            if value and value > 0
        ),
        None,
    )

    normalized_status = (transaction_status or "").strip().lower()
    if normalized_status == "refunded":
        return credits_to_grant
    if not refund_amount_cents or not basis:
        return credits_to_grant
    if refund_amount_cents >= basis:
        return credits_to_grant

    ratio = max(0.0, min(refund_amount_cents / basis, 1.0))
    return min(credits_to_grant, max(1, round(credits_to_grant * ratio)))


def build_public_url(path: str, **query: str) -> str:
    base = settings.public_app_url.rstrip("/")
    suffix = f"?{urlencode(query)}" if query else ""
    return f"{base}{path}{suffix}"


def build_mock_checkout_url(request_id: str) -> str:
    return build_public_url("/pricing", mock_checkout_request_id=request_id)


def build_success_url(request_id: str) -> str:
    return build_public_url("/pricing", payment="success", checkout_request_id=request_id)


@dataclass
class BillingSummary:
    client_token: str
    remaining_credits: int
    free_credits_granted: int
    paid_credits_granted: int
    used_credits: int
    free_credits_remaining: int
    paid_credits_remaining: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "client_token": self.client_token,
            "remaining_credits": self.remaining_credits,
            "free_credits_granted": self.free_credits_granted,
            "paid_credits_granted": self.paid_credits_granted,
            "used_credits": self.used_credits,
            "free_credits_remaining": self.free_credits_remaining,
            "paid_credits_remaining": self.paid_credits_remaining,
        }


def _build_summary(customer: BillingCustomer) -> BillingSummary:
    free_used = min(customer.free_credits_granted, customer.total_used_credits)
    paid_used = max(customer.total_used_credits - free_used, 0)
    return BillingSummary(
        client_token=customer.client_token,
        remaining_credits=customer.credit_balance,
        free_credits_granted=customer.free_credits_granted,
        paid_credits_granted=customer.paid_credits_granted,
        used_credits=customer.total_used_credits,
        free_credits_remaining=max(customer.free_credits_granted - free_used, 0),
        paid_credits_remaining=max(customer.paid_credits_granted - paid_used, 0),
    )


async def ensure_default_product(db: AsyncSession) -> BillingProduct:
    stmt = select(BillingProduct).where(BillingProduct.product_key == settings.billing_pack_product_key)
    product = (await db.execute(stmt)).scalar_one_or_none()
    if product:
        desired_fields = {
            "display_name": settings.billing_pack_display_name,
            "description": settings.billing_pack_description,
            "price_cents": settings.billing_pack_price_cents,
            "currency": settings.billing_pack_currency.upper(),
            "credits_per_unit": settings.billing_pack_credit_amount,
            "creem_product_id": settings.creem_product_id,
            "is_active": True,
        }
        changed = False
        for field_name, desired_value in desired_fields.items():
            if desired_value is not None and getattr(product, field_name) != desired_value:
                setattr(product, field_name, desired_value)
                changed = True
        if changed:
            await db.flush()
        return product

    product = BillingProduct(
        product_key=settings.billing_pack_product_key,
        display_name=settings.billing_pack_display_name,
        description=settings.billing_pack_description,
        price_cents=settings.billing_pack_price_cents,
        currency=settings.billing_pack_currency.upper(),
        credits_per_unit=settings.billing_pack_credit_amount,
        creem_product_id=settings.creem_product_id,
        is_active=True,
    )
    db.add(product)
    await db.flush()
    return product


async def get_product(db: AsyncSession, product_key: str | None = None) -> BillingProduct:
    key = product_key or settings.billing_pack_product_key
    stmt = select(BillingProduct).where(BillingProduct.product_key == key)
    product = (await db.execute(stmt)).scalar_one_or_none()
    if product is None:
        product = await ensure_default_product(db)
    return product


async def get_or_create_customer(
    db: AsyncSession,
    client_token: str,
    *,
    lock: bool = False,
    email: str | None = None,
) -> BillingCustomer:
    stmt = select(BillingCustomer).where(BillingCustomer.client_token == client_token)
    if lock:
        stmt = stmt.with_for_update()
    customer = (await db.execute(stmt)).scalar_one_or_none()
    if customer:
        if email and not customer.email:
            customer.email = email
        return customer

    customer = BillingCustomer(
        client_token=client_token,
        email=email,
        credit_balance=0,
        free_credits_granted=0,
        paid_credits_granted=0,
        total_used_credits=0,
    )
    db.add(customer)
    await db.flush()

    if settings.billing_free_credits > 0:
        await apply_credit_delta(
            db,
            customer,
            delta=settings.billing_free_credits,
            reason="free_grant",
            description="Initial free AMO dialogue credits.",
            metadata={"grant_type": "default_free_allowance"},
        )
        customer.free_credit_granted_at = datetime.now(UTC)

    return customer


async def apply_credit_delta(
    db: AsyncSession,
    customer: BillingCustomer,
    *,
    delta: int,
    reason: str,
    description: str | None = None,
    checkout: BillingCheckout | None = None,
    metadata: dict[str, Any] | None = None,
) -> CreditLedgerEntry:
    balance_after = customer.credit_balance + delta
    if balance_after < 0:
        raise BillingError(
            "No dialogue credits remaining. Purchase another $1 pack to continue chatting.",
            code="insufficient_credits",
            status_code=402,
            extra={"summary": _build_summary(customer).to_dict()},
        )

    customer.credit_balance = balance_after
    if reason == "free_grant":
        customer.free_credits_granted += max(delta, 0)
    elif reason in {"checkout_completed", "mock_checkout_completed"}:
        customer.paid_credits_granted += max(delta, 0)
    elif reason == "chat_message":
        customer.total_used_credits += max(-delta, 0)
    elif reason == "chat_refund":
        customer.total_used_credits = max(customer.total_used_credits - max(delta, 0), 0)

    entry = CreditLedgerEntry(
        customer_id=customer.id,
        checkout_id=checkout.id if checkout else None,
        delta=delta,
        balance_after=balance_after,
        reason=reason,
        description=description,
        metadata_json=metadata or {},
    )
    db.add(entry)
    await db.flush()
    return entry


async def get_billing_summary(db: AsyncSession, client_token: str) -> BillingSummary:
    customer = await get_or_create_customer(db, client_token)
    await db.flush()
    return _build_summary(customer)


async def consume_chat_credit(
    db: AsyncSession,
    client_token: str,
    *,
    message_length: int,
    character_id: int,
) -> tuple[BillingCustomer, CreditLedgerEntry, BillingSummary]:
    customer = await get_or_create_customer(db, client_token, lock=True)
    entry = await apply_credit_delta(
        db,
        customer,
        delta=-1,
        reason="chat_message",
        description="Consumed one dialogue credit.",
        metadata={"message_length": message_length, "character_id": character_id},
    )
    return customer, entry, _build_summary(customer)


async def refund_chat_credit(
    db: AsyncSession,
    client_token: str,
    *,
    usage_entry: CreditLedgerEntry,
    reason: str,
) -> BillingSummary:
    customer = await get_or_create_customer(db, client_token, lock=True)
    await apply_credit_delta(
        db,
        customer,
        delta=1,
        reason="chat_refund",
        description="Returned one dialogue credit after generation failure.",
        metadata={"source_usage_entry_id": usage_entry.id, "reason": reason},
    )
    return _build_summary(customer)


async def create_checkout(
    db: AsyncSession,
    client_token: str,
    *,
    email: str | None = None,
) -> BillingCheckout:
    customer = await get_or_create_customer(db, client_token, lock=True, email=email)
    product = await get_product(db)
    if not product.is_active:
        raise BillingError(
            "This AMO credit pack is currently unavailable.",
            code="product_inactive",
            status_code=409,
        )

    request_id = f"amochk_{uuid.uuid4().hex}"
    checkout = BillingCheckout(
        request_id=request_id,
        customer_id=customer.id,
        product_id=product.id,
        provider="creem",
        mode=settings.billing_checkout_mode,
        status="pending",
        amount_cents=product.price_cents,
        currency=product.currency,
        credits_to_grant=product.credits_per_unit,
        metadata_json={"product_key": product.product_key, "client_token": client_token},
    )
    db.add(checkout)
    await db.flush()

    if settings.billing_checkout_mode == "local_mock":
        checkout.checkout_url = build_mock_checkout_url(checkout.request_id)
        await db.flush()
        return checkout

    product_id = product.creem_product_id or settings.creem_product_id
    if not product_id:
        raise BillingError(
            "Missing Creem product configuration for this chat pack.",
            code="missing_creem_product",
            status_code=500,
        )

    payload: dict[str, Any] = {
        "product_id": product_id,
        "request_id": request_id,
        "success_url": build_success_url(request_id),
        "metadata": {
            "client_token": client_token,
            "product_key": product.product_key,
            "credits_to_grant": product.credits_per_unit,
        },
    }
    if email:
        payload["customer"] = {"email": email}

    headers = {
        "x-api-key": settings.creem_api_key or "",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=settings.creem_timeout_seconds) as client:
            response = await client.post(
                f"{settings.creem_base_url}/checkouts",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as exc:
        message = exc.response.text
        raise BillingError(
            f"Creem checkout creation failed: {message}",
            code="creem_checkout_failed",
            status_code=502,
        ) from exc
    except httpx.HTTPError as exc:
        raise BillingError(
            "Creem checkout request failed before completion.",
            code="creem_unreachable",
            status_code=502,
        ) from exc

    checkout.creem_checkout_id = data.get("id")
    checkout.checkout_url = data.get("checkout_url")
    checkout.status = data.get("status", checkout.status)
    checkout.mode = data.get("mode", checkout.mode)
    checkout.metadata_json = {**checkout.metadata_json, "creem_response": data}
    await db.flush()
    return checkout


async def get_checkout_for_client(
    db: AsyncSession,
    client_token: str,
    request_id: str,
) -> BillingCheckout:
    stmt = (
        select(BillingCheckout)
        .join(BillingCustomer, BillingCustomer.id == BillingCheckout.customer_id)
        .where(
            BillingCheckout.request_id == request_id,
            BillingCustomer.client_token == client_token,
        )
    )
    checkout = (await db.execute(stmt)).scalar_one_or_none()
    if checkout is None:
        raise BillingError(
            "Checkout session not found for this browser session.",
            code="checkout_not_found",
            status_code=404,
        )
    return checkout


async def complete_mock_checkout(
    db: AsyncSession,
    client_token: str,
    request_id: str,
    *,
    outcome: str,
) -> tuple[BillingCheckout, BillingSummary | None]:
    checkout = await get_checkout_for_client(db, client_token, request_id)
    if checkout.mode != "local_mock":
        raise BillingError(
            "This checkout is not running in local mock mode.",
            code="invalid_mock_checkout",
            status_code=409,
        )
    if checkout.status == "completed":
        customer = await get_or_create_customer(db, client_token)
        return checkout, _build_summary(customer)

    if outcome != "success":
        checkout.status = "canceled"
        await db.flush()
        customer = await get_or_create_customer(db, client_token)
        return checkout, _build_summary(customer)

    event_payload = {
        "id": f"mock_evt_{uuid.uuid4().hex}",
        "eventType": "checkout.completed",
        "object": {
            "id": f"mock_checkout_{checkout.request_id}",
            "request_id": checkout.request_id,
            "order": {"id": f"mock_order_{checkout.request_id}"},
            "customer": {"id": f"mock_customer_{checkout.customer_id}"},
        },
    }
    summary = await process_checkout_completed(
        db,
        event_id=event_payload["id"],
        event_type="checkout.completed",
        payload=event_payload,
        provider="local_mock",
    )
    refreshed = await get_checkout_for_client(db, client_token, request_id)
    return refreshed, summary


async def get_or_create_webhook_event(
    db: AsyncSession,
    *,
    event_id: str,
    event_type: str,
    payload: dict[str, Any],
    provider: str,
) -> BillingWebhookEvent:
    stmt = select(BillingWebhookEvent).where(BillingWebhookEvent.event_id == event_id)
    event = (await db.execute(stmt)).scalar_one_or_none()
    if event:
        return event

    event = BillingWebhookEvent(
        event_id=event_id,
        event_type=event_type,
        provider=provider,
        payload=payload,
        status="received",
    )
    db.add(event)
    await db.flush()
    return event


async def process_checkout_completed(
    db: AsyncSession,
    *,
    event_id: str,
    event_type: str,
    payload: dict[str, Any],
    provider: str = "creem",
) -> BillingSummary:
    event = await get_or_create_webhook_event(
        db,
        event_id=event_id,
        event_type=event_type,
        payload=payload,
        provider=provider,
    )
    if event.status == "processed":
        object_data = payload.get("object", {})
        request_id = object_data.get("request_id")
        if request_id:
            checkout_stmt = (
                select(BillingCheckout)
                .where(BillingCheckout.request_id == request_id)
                .with_for_update()
            )
            checkout = (await db.execute(checkout_stmt)).scalar_one_or_none()
            if checkout:
                customer_stmt = (
                    select(BillingCustomer)
                    .where(BillingCustomer.id == checkout.customer_id)
                    .with_for_update()
                )
                customer = (await db.execute(customer_stmt)).scalar_one_or_none()
                if customer:
                    return _build_summary(customer)
        raise BillingError(
            "Processed checkout event could not be matched to a customer.",
            code="processed_event_missing_customer",
            status_code=404,
        )

    object_data = payload.get("object", {})
    request_id = object_data.get("request_id") or payload.get("request_id")
    if not request_id:
        event.status = "failed"
        event.error_message = "Missing request_id in checkout.completed payload."
        await db.flush()
        raise BillingError(
            "Webhook payload did not include a request_id.",
            code="invalid_webhook_payload",
            status_code=400,
        )

    checkout_stmt = (
        select(BillingCheckout)
        .where(BillingCheckout.request_id == request_id)
        .with_for_update()
    )
    checkout = (await db.execute(checkout_stmt)).scalar_one_or_none()
    if checkout is None:
        event.status = "failed"
        event.error_message = f"Unknown request_id: {request_id}"
        await db.flush()
        raise BillingError(
            "Checkout session does not exist locally.",
            code="unknown_checkout",
            status_code=404,
        )

    customer_stmt = (
        select(BillingCustomer)
        .where(BillingCustomer.id == checkout.customer_id)
        .with_for_update()
    )
    customer = (await db.execute(customer_stmt)).scalar_one()

    if checkout.status != "completed":
        order_data = object_data.get("order") or {}
        customer_data = object_data.get("customer") or {}
        checkout.creem_checkout_id = object_data.get("id") or checkout.creem_checkout_id
        checkout.creem_order_id = order_data.get("id") or checkout.creem_order_id
        checkout.status = "completed"
        checkout.completed_at = datetime.now(UTC)
        checkout.metadata_json = {**checkout.metadata_json, "completion_payload": object_data}
        if customer_data.get("id"):
            customer.creem_customer_id = customer_data["id"]

        await apply_credit_delta(
            db,
            customer,
            delta=checkout.credits_to_grant,
            reason="mock_checkout_completed" if provider == "local_mock" else "checkout_completed",
            description="Granted credits after successful checkout completion.",
            checkout=checkout,
            metadata={"event_id": event_id, "provider": provider},
        )

    event.status = "processed"
    event.processed_at = datetime.now(UTC)
    event.error_message = None
    await db.flush()
    return _build_summary(customer)


async def process_refund_created(
    db: AsyncSession,
    *,
    event_id: str,
    event_type: str,
    payload: dict[str, Any],
    provider: str = "creem",
) -> BillingSummary:
    event = await get_or_create_webhook_event(
        db,
        event_id=event_id,
        event_type=event_type,
        payload=payload,
        provider=provider,
    )

    lookup = extract_refund_lookup(payload)
    if not any(lookup.get(key) for key in ("request_id", "order_id", "checkout_id")):
        event.status = "failed"
        event.error_message = "Missing checkout reference in refund.created payload."
        await db.flush()
        raise BillingError(
            "Refund webhook payload did not include a checkout reference.",
            code="invalid_refund_payload",
            status_code=400,
        )

    checkout_stmt = select(BillingCheckout).with_for_update()
    if lookup.get("request_id"):
        checkout_stmt = checkout_stmt.where(BillingCheckout.request_id == lookup["request_id"])
    elif lookup.get("order_id"):
        checkout_stmt = checkout_stmt.where(BillingCheckout.creem_order_id == lookup["order_id"])
    else:
        checkout_stmt = checkout_stmt.where(BillingCheckout.creem_checkout_id == lookup["checkout_id"])

    checkout = (await db.execute(checkout_stmt)).scalar_one_or_none()
    if checkout is None:
        event.status = "failed"
        event.error_message = f"Unknown refund reference: {lookup}"
        await db.flush()
        raise BillingError(
            "Refund event could not be matched to a local checkout.",
            code="unknown_refund_checkout",
            status_code=404,
        )

    customer_stmt = (
        select(BillingCustomer)
        .where(BillingCustomer.id == checkout.customer_id)
        .with_for_update()
    )
    customer = (await db.execute(customer_stmt)).scalar_one()

    if event.status == "processed":
        return _build_summary(customer)

    metadata = dict(checkout.metadata_json or {})
    refunds = list(metadata.get("refunds") or [])
    already_refunded_credits = sum(int(item.get("credits_requested_to_revoke") or 0) for item in refunds)
    refundable_credits = max(checkout.credits_to_grant - already_refunded_credits, 0)
    calculated_credits = calculate_refunded_credits(
        checkout_amount_cents=checkout.amount_cents,
        credits_to_grant=checkout.credits_to_grant,
        refund_amount_cents=lookup.get("refund_amount_cents"),
        transaction_amount_cents=lookup.get("transaction_amount_cents"),
        transaction_amount_paid_cents=lookup.get("transaction_amount_paid_cents"),
        transaction_status=lookup.get("transaction_status"),
    )
    credits_to_revoke = min(calculated_credits, refundable_credits)
    balance_delta = -min(customer.credit_balance, credits_to_revoke)

    if credits_to_revoke > 0:
        customer.credit_balance += balance_delta
        customer.paid_credits_granted = max(customer.paid_credits_granted - credits_to_revoke, 0)

        db.add(
            CreditLedgerEntry(
                customer_id=customer.id,
                checkout_id=checkout.id,
                delta=balance_delta,
                balance_after=customer.credit_balance,
                reason="checkout_refunded",
                description="Revoked dialogue credits after Creem refund.",
                metadata_json={
                    "event_id": event_id,
                    "provider": provider,
                    "refund_id": lookup.get("refund_id"),
                    "refund_amount_cents": lookup.get("refund_amount_cents"),
                    "credits_requested_to_revoke": credits_to_revoke,
                },
            )
        )

    total_refunded_credits = already_refunded_credits + credits_to_revoke
    checkout.status = "refunded" if total_refunded_credits >= checkout.credits_to_grant else "partially_refunded"
    refunds.append(
        {
            "event_id": event_id,
            "refund_id": lookup.get("refund_id"),
            "refund_amount_cents": lookup.get("refund_amount_cents"),
            "credits_requested_to_revoke": credits_to_revoke,
            "balance_delta": balance_delta,
            "processed_at": datetime.now(UTC).isoformat(),
        }
    )
    checkout.metadata_json = {**metadata, "refunds": refunds, "last_refund_payload": payload.get("object", {})}

    event.status = "processed"
    event.processed_at = datetime.now(UTC)
    event.error_message = None
    await db.flush()
    return _build_summary(customer)


async def update_product(
    db: AsyncSession,
    product_key: str,
    *,
    display_name: str | None = None,
    description: str | None = None,
    price_cents: int | None = None,
    currency: str | None = None,
    credits_per_unit: int | None = None,
    is_active: bool | None = None,
    creem_product_id: str | None = None,
) -> BillingProduct:
    product = await get_product(db, product_key)
    if display_name is not None:
        product.display_name = display_name.strip() or product.display_name
    if description is not None:
        product.description = description.strip() or None
    if price_cents is not None:
        product.price_cents = price_cents
    if currency is not None:
        product.currency = currency.upper()
    if credits_per_unit is not None:
        product.credits_per_unit = credits_per_unit
    if is_active is not None:
        product.is_active = is_active
    if creem_product_id is not None:
        product.creem_product_id = creem_product_id.strip() or None
    await db.flush()
    return product


def serialize_product(product: BillingProduct) -> dict[str, Any]:
    return {
        "product_key": product.product_key,
        "display_name": product.display_name,
        "description": product.description,
        "price_cents": product.price_cents,
        "currency": product.currency,
        "credits_per_unit": product.credits_per_unit,
        "is_active": product.is_active,
        "billing_type": product.billing_type,
        "creem_product_id_configured": bool(product.creem_product_id or settings.creem_product_id),
        "mode": settings.billing_checkout_mode,
    }


def serialize_checkout(checkout: BillingCheckout) -> dict[str, Any]:
    return {
        "request_id": checkout.request_id,
        "provider": checkout.provider,
        "mode": checkout.mode,
        "status": checkout.status,
        "checkout_url": checkout.checkout_url,
        "amount_cents": checkout.amount_cents,
        "currency": checkout.currency,
        "credits_to_grant": checkout.credits_to_grant,
        "completed_at": checkout.completed_at,
    }


def parse_webhook_payload(body: bytes) -> tuple[str, str, dict[str, Any]]:
    try:
        payload = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise BillingError(
            "Webhook body is not valid JSON.",
            code="invalid_json",
            status_code=400,
        ) from exc

    event_id = str(payload.get("id") or "")
    event_type = str(payload.get("eventType") or payload.get("type") or "")
    if not event_id or not event_type:
        raise BillingError(
            "Webhook payload is missing id or event type.",
            code="invalid_webhook_payload",
            status_code=400,
        )
    return event_id, event_type, payload
