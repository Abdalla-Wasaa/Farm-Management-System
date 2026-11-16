"""Durable sandbox STK requests and independent provider-query verification.

No HTTP handler calls Daraja. A callback is only a hint, never proof of payment.
"""

from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import select

from app import daraja
from app.auth import require
from app.config import settings
from app.db import SessionLocal
from app.models import MpesaIntent, Order, Payment, now
from app.services import audit, get_or_404, notify

ACTIVE = ("queued", "submitting", "pending", "uncertain")


def request_stk(db, actor, order_id, data, key):
    require(actor, "buyer")
    order = get_or_404(db, Order, order_id, lock=True)
    if order.buyer_id != actor.id:
        raise HTTPException(403, "Only the buyer may initiate payment for this order")
    previous = db.scalar(
        select(MpesaIntent).where(
            MpesaIntent.order_id == order.id, MpesaIntent.idempotency_key == key
        )
    )
    if previous:
        if previous.phone != data.phone:
            raise HTTPException(409, "Idempotency key reused with a different phone")
        return previous
    daraja.configured()
    if (
        order.status
        not in ("pending", "confirmed", "preparing", "ready", "dispatched", "completed")
        or order.payment_status != "unpaid"
    ):
        raise HTTPException(409, "Only open, unpaid orders can request M-Pesa payment")
    if order.status == "pending" and order.expires_at <= now():
        raise HTTPException(409, "Reservation expired; place a new order before paying")
    if order.total != order.total.to_integral_value():
        raise HTTPException(
            422, "STK Push requires a whole KES total; no rounding is applied"
        )
    if db.scalar(
        select(MpesaIntent.id).where(
            MpesaIntent.order_id == order.id, MpesaIntent.status.in_(ACTIVE)
        )
    ):
        raise HTTPException(
            409, "An M-Pesa request is already active or needs reconciliation"
        )
    intent = MpesaIntent(
        order_id=order.id,
        buyer_id=actor.id,
        phone=data.phone,
        amount=order.total,
        idempotency_key=key,
    )
    db.add(intent)
    db.flush()
    audit(db, order, actor, "mpesa_sandbox_requested")
    return intent


def callback_hint(db, data):
    callback = data.Body.stkCallback
    intent = db.scalar(
        select(MpesaIntent).where(MpesaIntent.checkout_id == callback.CheckoutRequestID)
    )
    # Deliberately no settlement from anonymous callback data. Polling is authoritative.
    if intent and intent.merchant_id == callback.MerchantRequestID:
        return {
            "ResultCode": 0,
            "ResultDesc": "Received; independent verification required",
        }
    # Same response for unknown IDs to avoid exposing transaction existence.
    return {
        "ResultCode": 0,
        "ResultDesc": "Received; independent verification required",
    }


def submit_one(sender=None):
    sender = sender or daraja.initiate
    with SessionLocal.begin() as db:
        intent = db.scalar(
            select(MpesaIntent)
            .where(MpesaIntent.status == "queued")
            .order_by(MpesaIntent.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if intent is None:
            return False
        intent.status = "submitting"
        intent.next_check = now() + timedelta(minutes=2)
        intent_id = intent.id
        reference = get_or_404(db, Order, intent.order_id).reference
    # The submitting marker commits BEFORE network I/O. Never auto-repeat an
    # ambiguous request: Daraja STK initiation has no client idempotency key.
    try:
        result = sender(intent, reference)
    except daraja.ProviderError:
        result = {}
    with SessionLocal.begin() as db:
        current = get_or_404(db, MpesaIntent, intent_id, lock=True)
        if current.status != "submitting":
            return True
        checkout = result.get("CheckoutRequestID")
        merchant = result.get("MerchantRequestID")
        if (
            str(result.get("ResponseCode")) == "0"
            and isinstance(checkout, str)
            and 0 < len(checkout) <= 80
            and isinstance(merchant, str)
            and 0 < len(merchant) <= 80
        ):
            current.checkout_id = checkout
            current.merchant_id = merchant
            current.status = "pending"
            current.next_check = now() + timedelta(seconds=30)
        elif "ResponseCode" in result and str(result["ResponseCode"]) != "0":
            current.status = "failed"
            current.result_code = str(result["ResponseCode"])[:30]
        else:
            current.status = "uncertain"
    return True


def reconcile_one(query=None):
    query = query or daraja.query
    with SessionLocal.begin() as db:
        candidate = db.scalar(
            select(MpesaIntent)
            .where(
                MpesaIntent.status.in_(["pending", "submitting"]),
                MpesaIntent.next_check <= now(),
            )
            .order_by(MpesaIntent.id)
            .limit(1)
        )
        if candidate is None:
            return False
        # Consistent order-first locking with the cash receipt service.
        order = get_or_404(db, Order, candidate.order_id, lock=True)
        intent = db.scalar(
            select(MpesaIntent)
            .where(MpesaIntent.id == candidate.id)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
        if (
            intent is None
            or intent.status not in ("pending", "submitting")
            or intent.next_check > now()
        ):
            return False
        if intent.status == "submitting":
            intent.status = "uncertain"
            return True
        intent.checks += 1
        intent.next_check = now() + timedelta(
            seconds=min(300, 30 * 2 ** min(intent.checks, 4))
        )
        try:
            result = query(intent)
        except daraja.ProviderError:
            result = {}
        matches = (
            result.get("CheckoutRequestID") == intent.checkout_id
            and result.get("MerchantRequestID") == intent.merchant_id
        )
        code = str(result.get("ResultCode", ""))
        # Both identifiers must match our authenticated initiation response.
        if matches and code == "0":
            existing = db.scalar(select(Payment).where(Payment.order_id == order.id))
            if (
                existing
                or order.total != intent.amount
                or order.status in ("cancelled", "expired")
            ):
                intent.status = "uncertain"
                return True
            db.add(
                Payment(
                    order_id=order.id,
                    actor_id=intent.buyer_id,
                    amount=intent.amount,
                    method="mpesa_sandbox",
                    receipt=f"STK:{intent.checkout_id}",
                )
            )
            order.payment_status = "paid"
            intent.status = "succeeded"
            intent.result_code = "0"
            audit(db, order, None, "mpesa_sandbox_verified")
            notify(
                db,
                order,
                "paid",
                order.buyer_id,
                f"Sandbox M-Pesa simulation verified: KES {intent.amount:.2f}. No live payment.",
            )
        elif matches and code.lstrip("-").isdigit() and code != "0":
            intent.status = "failed"
            intent.result_code = code[:30]
        elif intent.checks >= 20:
            # Unresolved requests keep cash/new STK blocked until investigated.
            intent.status = "uncertain"
    return True


def tick():
    if settings.daraja_mode != "sandbox":
        return
    for _ in range(10):
        if not submit_one():
            break
    for _ in range(10):
        if not reconcile_one():
            break
