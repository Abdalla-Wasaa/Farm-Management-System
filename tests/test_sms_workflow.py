"""Buyer routing, durable submissions, authenticated receipts and recovery."""

import logging
from datetime import timedelta

import pytest
from pydantic import SecretStr
from sqlalchemy import select
from test_marketplace import advance, place

from app import sms
from app.config import settings
from app.db import SessionLocal
from app.models import Notification, Order, SmsDeliveryReport, User, now
from app.notifications import record_attempt
from app.sms_callbacks import CallbackLogFilter
from app.worker import dispatch_one, recover_interrupted

TOKEN = "test-delivery-token-with-at-least-32-characters"


@pytest.fixture
def delivery(monkeypatch):
    monkeypatch.setattr(settings, "sms_delivery_token", SecretStr(TOKEN))
    return "/webhooks/sms/delivery?key=" + TOKEN


def test_buyer_saved_phone_and_idempotent_order(shop):
    c, u = shop
    order = place(c, u).json()
    assert place(c, u).json()["id"] == order["id"]
    notes = c.get(
        f"/orders/{order['id']}/notifications", headers=u["buyer2"]["headers"]
    ).json()
    assert len(notes) == 1 and notes[0]["event_type"] == "placed"
    assert notes[0]["recipient_user_id"] == u["buyer2"]["id"]
    assert notes[0]["recipient_masked"].endswith("5602")
    assert "message" not in notes[0] and "phone" not in notes[0]
    assert (
        c.get(
            f"/orders/{order['id']}/notifications", headers=u["buyer3"]["headers"]
        ).status_code
        == 403
    )
    assert advance(c, u, order["id"], "confirmed").status_code == 200
    with SessionLocal() as db:
        buyer = db.get(User, u["buyer2"]["id"])
        notes = db.scalars(
            select(Notification).where(Notification.recipient_user_id == buyer.id)
        ).all()
        assert {n.event_type for n in notes} == {"placed", "confirmed"}
        assert all(n.phone == buyer.phone and n.order_id == order["id"] for n in notes)


def test_live_requires_transactional_approval_and_tracking(monkeypatch):
    monkeypatch.setattr(settings, "sms_mode", "live")
    monkeypatch.setattr(settings, "at_username", "live-app")
    monkeypatch.setattr(settings, "at_api_key", "dummy")
    monkeypatch.setattr(
        sms.httpx, "post", lambda *a, **k: pytest.fail("unapproved sender")
    )
    assert not sms.readiness()["production_ready"]
    assert sms.send("+254712345678", "private").outcome == "permanent"
    assert "dummy" not in str(sms.readiness())


def test_claim_is_committed_and_ambiguous_send_not_repeated(setup_db):
    with SessionLocal.begin() as db:
        db.add(
            Notification(event_key="durable", phone="+254712345678", message="private")
        )

    def sender(*args):
        with SessionLocal() as db:
            assert db.scalar(select(Notification)).status == "sending"
        assert not dispatch_one(lambda *a: pytest.fail("duplicate dispatcher"))
        return sms.Result("uncertain", {"error": "submission_outcome_unknown"})

    assert dispatch_one(sender)
    assert not dispatch_one(lambda *a: pytest.fail("automatic ambiguous retry"))
    with SessionLocal() as db:
        assert db.scalar(select(Notification)).status == "uncertain"


def test_interrupted_claim_becomes_uncertain(setup_db):
    with SessionLocal.begin() as db:
        db.add(
            Notification(
                event_key="crash",
                phone="+254712345678",
                message="private",
                status="sending",
                attempts=1,
                next_attempt=now() - timedelta(seconds=1),
            )
        )
    assert recover_interrupted() == 1
    assert not dispatch_one(
        lambda *a: pytest.fail("interrupted submission must not resend")
    )


def test_delivery_reports_early_duplicate_and_out_of_order(shop, delivery):
    c, u = shop
    oid = place(c, u).json()["id"]
    assert (
        c.post(
            "/webhooks/sms/delivery?key=wrong",
            json={"id": "provider-1", "status": "Success"},
        ).status_code
        == 403
    )
    # Receipt can beat the HTTP submission response; retain it until linked.
    assert (
        c.post(delivery, data={"id": "provider-1", "status": "Success"}).status_code
        == 200
    )
    with SessionLocal.begin() as db:
        note = db.scalar(
            select(Notification).where(Notification.event_type == "placed")
        )
        note.attempts = 1
        record_attempt(db, note, sms.Result("accepted", {"message_id": "provider-1"}))
        assert note.status == "delivered"
    for status in ["Success", "Submitted", "Failed"]:
        assert (
            c.post(delivery, json={"id": "provider-1", "status": status}).status_code
            == 200
        )
    with SessionLocal() as db:
        note = db.scalar(
            select(Notification).where(Notification.event_type == "placed")
        )
        assert note.status == "delivered" and note.delivered_at
        assert db.get(Order, oid).payment_status == "unpaid"
        assert len(db.scalars(select(SmsDeliveryReport)).all()) == 3
    view = c.get(f"/orders/{oid}/notifications", headers=u["buyer2"]["headers"]).json()
    assert view[0]["status"] == "delivered"


def test_delivery_phone_mismatch_and_validation(shop, delivery):
    c, u = shop
    place(c, u)
    with SessionLocal.begin() as db:
        note = db.scalar(
            select(Notification).where(Notification.event_type == "placed")
        )
        record_attempt(db, note, sms.Result("accepted", {"message_id": "phone-check"}))
    assert (
        c.post(
            delivery,
            json={
                "id": "phone-check",
                "status": "Success",
                "phoneNumber": "+254712345699",
            },
        ).status_code
        == 200
    )
    with SessionLocal() as db:
        assert (
            db.scalar(
                select(Notification).where(Notification.event_type == "placed")
            ).status
            == "accepted"
        )
    assert c.post(delivery, json={"status": "Success"}).status_code == 422
    assert (
        c.post(
            delivery, content="x" * 4097, headers={"Content-Type": "application/json"}
        ).status_code
        == 413
    )


def test_admin_recovery_is_limited_and_audited(shop):
    c, u = shop
    place(c, u)
    with SessionLocal.begin() as db:
        note = db.scalar(
            select(Notification).where(Notification.event_type == "placed")
        )
        note.status, note.last_error = "failed", "insufficient_balance"
        nid = note.id
    path = f"/admin/notifications/{nid}/retry"
    assert c.post(path, headers=u["buyer2"]["headers"]).status_code == 403
    assert c.post(path, headers=u["admin"]["headers"]).status_code == 200
    assert c.post(path, headers=u["admin"]["headers"]).status_code == 409
    with SessionLocal.begin() as db:
        note = db.get(Notification, nid)
        note.status, note.last_error = "failed", "recipient_opted_out"
    assert c.post(path, headers=u["admin"]["headers"]).status_code == 409
    assert (
        c.get(
            "/admin/notifications/readiness", headers=u["buyer2"]["headers"]
        ).status_code
        == 403
    )
    assert (
        "api_key"
        not in c.get(
            "/admin/notifications/readiness", headers=u["admin"]["headers"]
        ).text
    )


def test_delivery_secret_redacted_from_access_logs():
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        "",
        0,
        "%s %s %s %s %s",
        ("client", "POST", "/webhooks/sms/delivery?key=private-secret", "1.1", 200),
        None,
    )
    assert CallbackLogFilter().filter(record)
    assert "private-secret" not in record.getMessage()
