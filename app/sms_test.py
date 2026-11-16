"""Send one explicitly requested SMS without draining the outbox or running payments.

A committed 'sending' marker and a unique reference prevent accidental replay. Tests
have one attempt only: a transport timeout is uncertain, never automatically resent.
"""

import argparse
import json
import os

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app import sms
from app.config import settings
from app.db import SessionLocal
from app.models import Notification, NotificationAttempt
from app.schemas import phone_number

MESSAGE = "Kuku Farm: SMS connection test. Order and verified payment updates will use this channel."


def send_one_test(phone, reference, *, live=False, sender=None):
    phone = phone_number(phone)
    if not reference or len(reference) > 100:
        raise ValueError("Use a test reference between 1 and 100 characters")
    if live and (
        not settings.at_api_key
        or not settings.at_username
        or settings.at_username == "sandbox"
    ):
        raise ValueError(
            "Set the live AT_API_KEY and AT_USERNAME in backend .env first"
        )
    if (
        live
        and settings.sms_allowed_recipients
        and phone not in settings.sms_allowed_recipients
    ):
        raise ValueError("Test phone is not in SMS_ALLOWED_RECIPIENTS")
    key = "sms-test:" + reference
    with SessionLocal.begin() as db:
        previous = db.scalar(select(Notification).where(Notification.event_key == key))
        if previous:
            if previous.phone != phone:
                raise ValueError("Test reference already belongs to another recipient")
            return {
                "notification_id": previous.id,
                "status": previous.status,
                "reused": True,
            }
        note = Notification(
            event_key=key, phone=phone, message=MESSAGE, status="sending"
        )
        db.add(note)
        db.flush()
        notification_id = note.id
    original_mode = settings.sms_mode
    try:
        # This override affects this dedicated CLI process, not the running API/worker.
        settings.sms_mode = "live" if live else "dry-run"
        result = (sender or sms.send)(phone, MESSAGE)
    except Exception:
        # Never echo exception text: it may contain request data or credentials.
        result = sms.Result("temporary", {"error": "test_outcome_unknown"})
    finally:
        settings.sms_mode = original_mode
    with SessionLocal.begin() as db:
        note = db.get(Notification, notification_id)
        note.attempts = 1
        note.status = {
            "accepted": "accepted",
            "dry-run": "dry-run",
            "blocked": "blocked",
            "permanent": "failed",
        }.get(result.outcome, "uncertain")
        db.add(
            NotificationAttempt(
                notification_id=note.id,
                outcome=result.outcome,
                provider_response=result.response,
            )
        )
        return {
            "notification_id": note.id,
            "status": note.status,
            "provider": result.response,
            "reused": False,
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--phone", help="A Kenyan number you control; defaults to SMS_TEST_PHONE"
    )
    parser.add_argument(
        "--reference",
        required=True,
        help="Reuse exactly this value after an interrupted test",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Explicitly send ONE charged SMS; default is dry-run",
    )
    args = parser.parse_args()
    # Settings has loaded .env but ignores this optional convenience key.
    from dotenv import dotenv_values

    phone = (
        args.phone
        or os.environ.get("SMS_TEST_PHONE")
        or dotenv_values(".env").get("SMS_TEST_PHONE")
    )
    if not phone:
        parser.error("Provide --phone or set SMS_TEST_PHONE in backend .env")
    try:
        result = send_one_test(phone, args.reference, live=args.live)
    except ValueError as exc:
        parser.error(str(exc))
    except IntegrityError:
        parser.error(
            "This reference was claimed concurrently. Reuse it to inspect the existing test; no duplicate request was sent."
        )
    print(json.dumps(result))
    if result["status"] == "accepted":
        print(
            "Provider accepted the submission. Confirm receipt on your handset; acceptance is not proof of delivery."
        )
    elif result["status"] == "uncertain":
        print(
            "Outcome uncertain. Check the provider dashboard before any new test; no automatic retry will occur."
        )
    if result["status"] in ("failed", "uncertain", "blocked", "sending"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
