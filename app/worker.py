import argparse
import logging
import time
from datetime import timedelta

from sqlalchemy import select

from app import payments, sms
from app.config import settings
from app.db import SessionLocal
from app.models import Notification, NotificationAttempt, now
from app.notifications import apply_reports, record_attempt
from app.services import expire_orders

log = logging.getLogger(__name__)


def pending_query():
    return (
        select(Notification)
        .where(Notification.status == "pending", Notification.next_attempt <= now())
        .order_by(Notification.id)
        .with_for_update(skip_locked=True)
        .limit(1)
    )


def process_one(db, sender=None):
    """Transactional helper for tests/explicit callers; the daemon uses dispatch_one."""
    note = db.scalar(pending_query())
    if note is None:
        return False
    note.attempts += 1
    record_attempt(db, note, (sender or sms.send)(note.phone, note.message))
    return True


def recover_interrupted():
    with SessionLocal.begin() as db:
        notes = db.scalars(
            select(Notification)
            .where(Notification.status == "sending", Notification.next_attempt <= now())
            .with_for_update(skip_locked=True)
        ).all()
        for note in notes:
            note.status = "uncertain"
            note.last_error = "worker_interrupted"
            db.add(
                NotificationAttempt(
                    notification_id=note.id,
                    outcome="uncertain",
                    provider_response={"error": "worker_interrupted"},
                )
            )
        return len(notes)


def dispatch_one(sender=None):
    # Persist the claim before provider I/O. A crash never rolls this back to pending.
    with SessionLocal.begin() as db:
        note = db.scalar(pending_query())
        if note is None:
            return False
        note.status = "sending"
        note.attempts += 1
        note.claimed_at = now()
        note.next_attempt = now() + timedelta(seconds=settings.sms_claim_seconds)
        notification_id, attempt, phone, message = (
            note.id,
            note.attempts,
            note.phone,
            note.message,
        )
    try:
        result = (sender or sms.send)(phone, message)
    except Exception:
        result = sms.Result("uncertain", {"error": "submission_outcome_unknown"})
    with SessionLocal.begin() as db:
        note = db.scalar(
            select(Notification)
            .where(Notification.id == notification_id)
            .with_for_update()
        )
        if (
            note
            and note.attempts == attempt
            and (
                note.status == "sending"
                or (
                    note.status == "uncertain"
                    and note.last_error == "worker_interrupted"
                )
            )
        ):
            record_attempt(db, note, result)
    return True


def tick():
    # Payment provider downtime must not stop order expiry or SMS processing.
    try:
        payments.tick()
    except Exception as exc:
        log.error("Payment tick failed (%s)", type(exc).__name__)
    with SessionLocal.begin() as db:
        expire_orders(db)
    recover_interrupted()
    # Reconcile reports racing with a provider submission transaction.
    with SessionLocal.begin() as db:
        for note in db.scalars(
            select(Notification)
            .where(Notification.status == "accepted")
            .with_for_update(skip_locked=True)
        ):
            apply_reports(db, note)
    for _ in range(100):
        if not dispatch_one():
            break


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    while True:
        try:
            tick()
        except Exception as exc:
            log.error("Worker tick failed (%s)", type(exc).__name__)
            if args.once:
                raise SystemExit(1)
        if args.once:
            return
        time.sleep(3)


if __name__ == "__main__":
    main()
