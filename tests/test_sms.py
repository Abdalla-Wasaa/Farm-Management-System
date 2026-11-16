from datetime import timedelta

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import func, select
from test_marketplace import advance, place

from app import sms
from app.config import settings
from app.db import SessionLocal
from app.models import Notification, NotificationAttempt, Order, now
from app.worker import process_one, tick


def test_sms_failure_does_not_rollback_order(shop):
    c, u = shop
    order = place(c, u).json()
    with SessionLocal.begin() as db:
        assert process_one(
            db, lambda *args: sms.Result("temporary", {"http_status": 503})
        )
    with SessionLocal() as db:
        assert db.get(Order, order["id"]) is not None
        n = db.scalar(select(Notification).order_by(Notification.id))
        assert n.status == "pending" and n.attempts == 1
        assert db.scalar(select(func.count()).select_from(NotificationAttempt)) == 1
    with SessionLocal.begin() as db:
        db.scalar(select(Notification).order_by(Notification.id)).next_attempt = (
            now() - timedelta(seconds=1)
        )
    with SessionLocal.begin() as db:
        assert process_one(
            db,
            lambda *args: sms.Result(
                "accepted", {"status_code": 101, "message_id": "test"}
            ),
        )
    with SessionLocal.begin() as db:
        assert process_one(db)  # The independent buyer acknowledgement.
        assert not process_one(db)
        n = db.scalar(select(Notification).order_by(Notification.id))
        assert n.attempts == 2 and n.status == "accepted"


def test_retry_exhaustion_and_permanent_failure(setup_db):
    with SessionLocal.begin() as db:
        db.add(Notification(event_key="retry", phone="+254712345678", message="test"))
    for i in range(5):
        with SessionLocal.begin() as db:
            db.scalar(select(Notification)).next_attempt = now() - timedelta(seconds=1)
        with SessionLocal.begin() as db:
            assert process_one(
                db, lambda *a: sms.Result("temporary", {"error": "transport_error"})
            )
    with SessionLocal() as db:
        n = db.scalar(select(Notification))
        assert n.status == "failed" and n.attempts == 5
    with SessionLocal.begin() as db:
        db.add(
            Notification(event_key="permanent", phone="+254712345678", message="test")
        )
    with SessionLocal.begin() as db:
        assert process_one(db, lambda *a: sms.Result("permanent", {"http_status": 401}))
    with SessionLocal() as db:
        n = db.scalar(select(Notification).where(Notification.event_key == "permanent"))
        assert n.status == "failed" and n.attempts == 1


def test_dry_run_and_duplicate_events(shop, monkeypatch):
    c, u = shop
    monkeypatch.setattr(settings, "sms_mode", "dry-run")
    monkeypatch.setattr(
        httpx, "post", lambda *a, **k: pytest.fail("dry run must not call provider")
    )
    oid = place(c, u).json()["id"]
    for _ in range(2):
        assert advance(c, u, oid, "confirmed").status_code == 200
    tick()
    with SessionLocal() as db:
        notes = db.scalars(select(Notification)).all()
        assert len(notes) == 3 and all(n.status == "dry-run" for n in notes)
        assert not any(":paid:" in n.event_key for n in notes)


@pytest.mark.parametrize(
    "response,expected",
    [
        (
            httpx.Response(
                200,
                json={
                    "SMSMessageData": {
                        "Recipients": [
                            {
                                "statusCode": 101,
                                "messageId": "abc",
                                "number": "+254712345678",
                                "status": "Success",
                            }
                        ]
                    }
                },
            ),
            "accepted",
        ),
        (
            httpx.Response(
                200, json={"SMSMessageData": {"Recipients": [{"statusCode": 500}]}}
            ),
            "temporary",
        ),
        (httpx.Response(503), "temporary"),
        (httpx.Response(429), "temporary"),
        (httpx.Response(401), "permanent"),
        (httpx.Response(200, json={}), "uncertain"),
        (
            httpx.Response(
                200, json={"SMSMessageData": {"Recipients": [{"statusCode": 404}]}}
            ),
            "permanent",
        ),
    ],
)
def test_provider_adapter(monkeypatch, response, expected):
    monkeypatch.setattr(settings, "sms_mode", "sandbox")
    monkeypatch.setattr(settings, "at_api_key", "test-key")

    def post(url, **kwargs):
        assert "sandbox" in url and kwargs["data"]["username"] == "sandbox"
        return response

    monkeypatch.setattr(httpx, "post", post)
    result = sms.send("+254712345678", "private message")
    assert result.outcome == expected
    assert "+254" not in str(result.response) and "private" not in str(result.response)


def test_network_failure(monkeypatch):
    monkeypatch.setattr(settings, "sms_mode", "sandbox")
    monkeypatch.setattr(settings, "at_api_key", "test-key")

    def post(*a, **k):
        raise httpx.ReadTimeout("sensitive request")

    monkeypatch.setattr(httpx, "post", post)
    assert sms.send("+254712345678", "private").outcome == "uncertain"


def test_live_sms_allowlist_blocks_other_numbers(monkeypatch):
    monkeypatch.setattr(settings, "sms_mode", "live")
    monkeypatch.setattr(settings, "at_api_key", "dummy-live-key")
    monkeypatch.setattr(settings, "at_username", "test-app")
    monkeypatch.setattr(settings, "at_sender_id", "Approved")
    monkeypatch.setattr(settings, "sms_transactional_approved", True)
    monkeypatch.setattr(settings, "sms_delivery_token", SecretStr("t" * 40))
    monkeypatch.setattr(settings, "sms_allowed_recipients", ["+254712345678"])
    calls = []

    def post(url, **kwargs):
        calls.append(kwargs)
        assert url == "https://api.africastalking.com/version1/messaging"
        assert kwargs["data"]["to"] == "+254712345678"
        return httpx.Response(
            200,
            json={
                "SMSMessageData": {
                    "Recipients": [{"statusCode": 101, "messageId": "test-only"}]
                }
            },
        )

    monkeypatch.setattr(httpx, "post", post)
    assert sms.send("+254712345679", "private").outcome == "blocked"
    assert not calls
    assert sms.send("0712345678", "private").outcome == "accepted"
    assert len(calls) == 1


def test_blocked_events_are_terminal_without_retry(setup_db):
    with SessionLocal.begin() as db:
        db.add(Notification(event_key="blocked", phone="+254712345678", message="test"))
    with SessionLocal.begin() as db:
        assert process_one(
            db, lambda *a: sms.Result("blocked", {"error": "recipient_not_allowlisted"})
        )
    with SessionLocal.begin() as db:
        assert not process_one(db, lambda *a: pytest.fail("blocked must not retry"))
        assert db.scalar(select(Notification)).status == "blocked"


def test_one_sms_test_does_not_drain_outbox_or_repeat(shop, monkeypatch):
    from app.sms_test import send_one_test

    c, u = shop
    place(c, u)
    monkeypatch.setattr(settings, "at_api_key", "dummy-live-key")
    monkeypatch.setattr(settings, "at_username", "test-app")
    monkeypatch.setattr(settings, "at_sender_id", "Approved")
    monkeypatch.setattr(settings, "sms_transactional_approved", True)
    monkeypatch.setattr(settings, "sms_delivery_token", SecretStr("t" * 40))
    calls = []

    def sender(*args):
        calls.append(args)
        return sms.Result("accepted", {"status_code": 101, "message_id": "test"})

    first = send_one_test("0712345678", "test-reference", live=True, sender=sender)
    second = send_one_test(
        "+254712345678",
        "test-reference",
        live=True,
        sender=lambda *a: pytest.fail("duplicate live SMS"),
    )
    assert first["status"] == "accepted" and second["reused"] and len(calls) == 1
    assert settings.sms_mode == "dry-run"
    with SessionLocal() as db:
        assert (
            db.scalar(
                select(Notification).where(
                    Notification.event_key == f"order:1:new:user:{u['seller']['id']}"
                )
            ).status
            == "pending"
        )
        assert db.scalar(select(func.count()).select_from(NotificationAttempt)) == 1


def test_one_sms_timeout_is_not_automatically_retried(setup_db, monkeypatch):
    from app.sms_test import send_one_test

    monkeypatch.setattr(settings, "at_api_key", "dummy-live-key")
    monkeypatch.setattr(settings, "at_username", "test-app")
    monkeypatch.setattr(settings, "at_sender_id", "Approved")
    monkeypatch.setattr(settings, "sms_transactional_approved", True)
    monkeypatch.setattr(settings, "sms_delivery_token", SecretStr("t" * 40))
    result = send_one_test(
        "0712345678",
        "ambiguous-test",
        live=True,
        sender=lambda *a: sms.Result("temporary", {"error": "transport_error"}),
    )
    assert result["status"] == "uncertain"
    assert send_one_test(
        "0712345678",
        "ambiguous-test",
        live=True,
        sender=lambda *a: pytest.fail("ambiguous test must not repeat"),
    )["reused"]
    with SessionLocal.begin() as db:
        assert not process_one(
            db, lambda *a: pytest.fail("no automatic retry for the one-message test")
        )
