"""Durable SMS results, delivery reports, diagnostics and authorized recovery."""

import re
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.auth import require
from app.config import settings
from app.models import Audit, Notification, NotificationAttempt, SmsDeliveryReport, now

ERRORS = {
    401: "provider_risk_hold",
    402: "invalid_sender",
    403: "invalid_recipient",
    404: "unsupported_number",
    405: "insufficient_balance",
    406: "recipient_opted_out",
    500: "provider_internal_error",
    501: "provider_gateway_error",
    502: "provider_rejected",
}
RETRYABLE_FAILURES = {
    "provider_configuration",
    "transactional_sender_not_approved",
    "invalid_sender",
    "insufficient_balance",
    "authentication_failed",
    "recipient_not_allowlisted",
    "retry_exhausted",
}


def safe_code(value):
    text = str(value or "")
    return text if re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", text) else None


def apply_reports(db, note):
    if not note.provider_message_id:
        return
    reports = db.scalars(
        select(SmsDeliveryReport)
        .where(SmsDeliveryReport.provider_message_id == note.provider_message_id)
        .order_by(SmsDeliveryReport.received_at)
    ).all()
    for report in reports:
        if report.phone and report.phone != note.phone:
            continue
        if report.status == "Success":
            note.status = "delivered"
            note.delivered_at = report.received_at
            note.last_error = None
        elif report.status in ("Failed", "Rejected") and note.status != "delivered":
            note.status = "failed"
            note.last_error = report.failure_reason or "carrier_delivery_failed"
        # Sent/Submitted/Buffered indicate progress, not handset delivery.


def record_attempt(db, note, result, *, retry_temporary=True):
    db.add(
        NotificationAttempt(
            notification_id=note.id,
            outcome=result.outcome,
            provider_response=result.response,
        )
    )
    note.last_error = safe_code(result.response.get("error"))
    code = result.response.get("status_code")
    if isinstance(code, int) and code not in (100, 101, 102):
        note.last_error = ERRORS.get(code, "provider_rejected")
    if result.response.get("http_status") in (401, 403):
        note.last_error = "authentication_failed"
    if result.outcome == "accepted":
        message_id = result.response.get("message_id")
        if (
            isinstance(message_id, str)
            and message_id
            and message_id != "None"
            and len(message_id) <= 120
        ):
            note.provider_message_id = message_id
            note.status = "accepted"
            note.submitted_at = now()
            note.last_error = None
            apply_reports(db, note)
        else:
            note.status = "uncertain"
            note.last_error = "missing_provider_message_id"
    elif result.outcome in ("dry-run", "blocked"):
        note.status = result.outcome
    elif result.outcome == "permanent":
        note.status = "failed"
        note.last_error = note.last_error or "provider_rejected"
    elif result.outcome == "uncertain" or not retry_temporary:
        note.status = "uncertain"
        note.last_error = note.last_error or "submission_outcome_unknown"
    elif note.attempts >= settings.sms_max_attempts:
        note.status = "failed"
        note.last_error = "retry_exhausted"
    else:
        note.status = "pending"
        note.next_attempt = now() + timedelta(seconds=min(3600, 30 * 2**note.attempts))


def receive_report(db, data):
    db.execute(
        insert(SmsDeliveryReport)
        .values(
            provider_message_id=data.id,
            status=data.status,
            phone=data.phoneNumber,
            failure_reason=safe_code(data.failureReason),
            received_at=now(),
        )
        .on_conflict_do_nothing(index_elements=["provider_message_id", "status"])
    )
    note = db.scalar(
        select(Notification)
        .where(Notification.provider_message_id == data.id)
        .with_for_update()
    )
    if note:
        apply_reports(db, note)
    # Valid early reports remain stored and are applied once the send response commits.
    return {"received": True}


def can_retry(note):
    return bool(
        note.order_id
        and note.status in ("failed", "blocked")
        and not note.provider_message_id
        and note.last_error in RETRYABLE_FAILURES
    )


def retry_notification(db, actor, notification_id):
    require(actor, "admin")
    note = db.scalar(
        select(Notification).where(Notification.id == notification_id).with_for_update()
    )
    if not note:
        raise HTTPException(404, "Notification not found")
    if not can_retry(note):
        raise HTTPException(
            409,
            "This notification cannot be replayed. Delivered, uncertain, opted-out, dry-run and one-message tests require investigation, not automatic resending.",
        )
    from app.sms import readiness

    if settings.sms_mode == "live" and not readiness()["production_ready"]:
        raise HTTPException(
            409, "Complete the transactional sender configuration before retrying"
        )
    note.status = "pending"
    note.next_attempt = now()
    db.add(
        Audit(order_id=note.order_id, actor_id=actor.id, action=f"sms_retry:{note.id}")
    )
    return note


def notification_view(db, note, *, history=False):
    data = {
        "id": note.id,
        "event_key": note.event_key,
        "event_type": note.event_type,
        "order_id": note.order_id,
        "recipient_user_id": note.recipient_user_id,
        "recipient_masked": ("+" + "*" * (len(note.phone) - 5) + note.phone[-4:]),
        "status": note.status,
        "attempts": note.attempts,
        "next_attempt": note.next_attempt,
        "created_at": note.created_at,
        "submitted_at": note.submitted_at,
        "delivered_at": note.delivered_at,
        "provider_message_id": note.provider_message_id,
        "last_error": note.last_error,
        "can_retry": can_retry(note),
    }
    if history:
        data["history"] = [
            {
                "id": a.id,
                "outcome": a.outcome,
                "provider_response": a.provider_response,
                "created_at": a.created_at,
            }
            for a in db.scalars(
                select(NotificationAttempt)
                .where(NotificationAttempt.notification_id == note.id)
                .order_by(NotificationAttempt.id)
            )
        ]
    return data
