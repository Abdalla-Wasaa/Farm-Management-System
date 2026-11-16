import argparse
import logging
import time
from datetime import timedelta

from sqlalchemy import select

from app import payments, sms
from app.db import SessionLocal
from app.models import Notification, NotificationAttempt, now
from app.services import expire_orders

log = logging.getLogger(__name__)
MAX_ATTEMPTS = 5


def process_one(db, sender=None):
    sender = sender or sms.send
    # Row lock prevents two workers sending the same pending event concurrently.
    notification = db.scalar(
        select(Notification)
        .where(Notification.status == "pending", Notification.next_attempt <= now())
        .order_by(Notification.id)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if notification is None:
        return False
    result = sender(notification.phone, notification.message)
    notification.attempts += 1
    db.add(
        NotificationAttempt(
            notification_id=notification.id,
            outcome=result.outcome,
            provider_response=result.response,
        )
    )
    if result.outcome in ("accepted", "dry-run"):
        notification.status = result.outcome
    elif result.outcome == "permanent" or notification.attempts >= MAX_ATTEMPTS:
        notification.status = "failed"
    else:
        notification.next_attempt = now() + timedelta(
            seconds=min(3600, 30 * 2**notification.attempts)
        )
    return True


def tick():
    payments.tick()
    with SessionLocal.begin() as db:
        expire_orders(db)
    for _ in range(100):
        with SessionLocal.begin() as db:
            if not process_one(db):
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
            # Exception text could contain SQL parameters/message text; log only type.
            log.error("Worker tick failed (%s)", type(exc).__name__)
            if args.once:
                raise SystemExit(1)
        if args.once:
            return
        time.sleep(3)


if __name__ == "__main__":
    main()
