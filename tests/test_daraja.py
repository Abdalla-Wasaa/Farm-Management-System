import base64
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import func, select
from test_marketplace import advance, place

from app import daraja, payments
from app.config import settings
from app.db import SessionLocal
from app.models import MpesaIntent, Notification, Order, Payment, now


@pytest.fixture()
def mpesa_shop(shop, monkeypatch):
    monkeypatch.setattr(settings, "daraja_mode", "sandbox")
    monkeypatch.setattr(settings, "daraja_consumer_key", SecretStr("dummy-key"))
    monkeypatch.setattr(settings, "daraja_consumer_secret", SecretStr("dummy-secret"))
    monkeypatch.setattr(settings, "daraja_passkey", SecretStr("dummy-passkey"))
    monkeypatch.setattr(
        settings,
        "daraja_callback_url",
        "https://callback.example/payments/mpesa/callback",
    )
    c, u = shop
    oid = place(c, u, fulfillment="pickup").json()["id"]
    for status in ["confirmed", "preparing", "ready", "completed"]:
        assert advance(c, u, oid, status).status_code == 200
    return c, u, oid


def request(c, u, oid, key="mpesa-1", phone="0712345678", actor="buyer2"):
    return c.post(
        f"/orders/{oid}/payments/mpesa",
        headers={**u[actor]["headers"], "Idempotency-Key": key},
        json={"phone": phone},
    )


def due():
    with SessionLocal.begin() as db:
        intent = db.scalar(select(MpesaIntent).order_by(MpesaIntent.id.desc()))
        intent.next_check = now() - timedelta(seconds=1)


def accepted(*args):
    return {
        "ResponseCode": "0",
        "CheckoutRequestID": "ws_test_001",
        "MerchantRequestID": "merchant_001",
    }


def result(code=0, checkout="ws_test_001", merchant="merchant_001"):
    return {
        "CheckoutRequestID": checkout,
        "MerchantRequestID": merchant,
        "ResultCode": code,
    }


def test_sandbox_flow_verification_and_no_double_payment(mpesa_shop):
    c, u, oid = mpesa_shop
    r = request(c, u, oid)
    assert r.status_code == 202, r.text
    assert r.json()["environment"] == "sandbox"
    assert request(c, u, oid).json()["id"] == r.json()["id"]
    assert request(c, u, oid, phone="0712345679").status_code == 409
    assert request(c, u, oid, key="another").status_code == 409
    cash = {"amount": "900.00", "receipt": "cash-blocked"}
    assert (
        c.post(
            f"/orders/{oid}/payments", headers=u["admin"]["headers"], json=cash
        ).status_code
        == 409
    )
    assert payments.submit_one(accepted)
    assert not payments.submit_one(lambda *a: pytest.fail("no duplicate STK"))
    callback = {
        "Body": {
            "stkCallback": {
                **result(),
                "ResultCode": 0,
                "CallbackMetadata": {"Item": [{"Name": "Amount", "Value": 900}]},
            }
        }
    }
    assert c.post("/payments/mpesa/callback", json=callback).status_code == 200
    with SessionLocal() as db:
        assert db.get(Order, oid).payment_status == "unpaid"
        assert db.scalar(select(func.count()).select_from(Payment)) == 0
    due()
    assert payments.reconcile_one(lambda i: result())
    assert not payments.reconcile_one(lambda i: pytest.fail("already verified"))
    with SessionLocal() as db:
        intent = db.scalar(select(MpesaIntent))
        assert intent.status == "succeeded"
        payment = db.scalar(select(Payment))
        assert payment.method == "mpesa_sandbox"
        assert payment.amount == Decimal("900.00")
        assert db.get(Order, oid).payment_status == "paid"
        notes = db.scalars(
            select(Notification).where(Notification.event_key.contains(":paid:"))
        ).all()
        assert len(notes) == 1 and "Sandbox" in notes[0].message
    assert c.post("/payments/mpesa/callback", json=callback).status_code == 200
    assert request(c, u, oid, key="already-paid").status_code == 409
    status = c.get(
        f"/orders/{oid}/payments/mpesa", headers=u["buyer2"]["headers"]
    ).json()
    assert status[0]["status"] == "succeeded"


def test_permissions_configuration_and_whole_amount(mpesa_shop, monkeypatch):
    c, u, oid = mpesa_shop
    assert request(c, u, oid, actor="buyer3").status_code == 403
    assert request(c, u, oid, actor="admin").status_code == 403
    monkeypatch.setattr(settings, "daraja_callback_url", "")
    assert request(c, u, oid).status_code == 503
    monkeypatch.setattr(
        settings, "daraja_callback_url", "https://callback.example/path"
    )
    with SessionLocal.begin() as db:
        db.get(Order, oid).total = Decimal("900.50")
    assert request(c, u, oid).status_code == 422
    with SessionLocal.begin() as db:
        db.get(Order, oid).total = Decimal("900.00")
        db.get(Order, oid).status = "ready"
    assert request(c, u, oid).status_code == 409
    assert (
        c.get(
            f"/orders/{oid}/payments/mpesa", headers=u["buyer3"]["headers"]
        ).status_code
        == 403
    )
    monkeypatch.setattr(settings, "daraja_mode", "disabled")
    assert request(c, u, oid).status_code == 503


def test_failed_request_allows_explicit_retry(mpesa_shop):
    c, u, oid = mpesa_shop
    assert request(c, u, oid).status_code == 202
    assert payments.submit_one(accepted)
    due()
    assert payments.reconcile_one(lambda i: result(1032))
    with SessionLocal() as db:
        assert db.get(Order, oid).payment_status == "unpaid"
        assert db.scalar(select(MpesaIntent)).status == "failed"
        assert db.scalar(select(func.count()).select_from(Payment)) == 0
    assert request(c, u, oid, key="retry-after-cancel").status_code == 202


def test_timeout_never_repeats_stk_or_accepts_cash(mpesa_shop):
    c, u, oid = mpesa_shop
    request(c, u, oid)

    def timeout(*args):
        raise daraja.ProviderError("ambiguous")

    assert payments.submit_one(timeout)
    assert not payments.submit_one(
        lambda *a: pytest.fail("must not repeat ambiguous STK")
    )
    assert request(c, u, oid, key="unsafe-retry").status_code == 409
    with SessionLocal() as db:
        assert db.scalar(select(MpesaIntent)).status == "uncertain"
    assert (
        c.post(
            f"/orders/{oid}/payments",
            headers=u["admin"]["headers"],
            json={"amount": "900.00", "receipt": "unsafe"},
        ).status_code
        == 409
    )


def test_query_failure_mismatch_and_retry_limit(mpesa_shop):
    c, u, oid = mpesa_shop
    request(c, u, oid)
    payments.submit_one(accepted)
    due()
    payments.reconcile_one(lambda i: result(checkout="spoofed"))
    with SessionLocal() as db:
        assert db.get(Order, oid).payment_status == "unpaid"

    def timeout(i):
        raise daraja.ProviderError("temporary")

    due()
    payments.reconcile_one(timeout)
    with SessionLocal.begin() as db:
        intent = db.scalar(select(MpesaIntent))
        assert intent.status == "pending"
        intent.checks = 19
    due()
    payments.reconcile_one(timeout)
    with SessionLocal() as db:
        assert db.scalar(select(MpesaIntent)).status == "uncertain"


def test_worker_crash_marker_does_not_repeat_request(mpesa_shop):
    c, u, oid = mpesa_shop
    request(c, u, oid)
    with SessionLocal.begin() as db:
        db.scalar(select(MpesaIntent)).status = "submitting"
    due()
    assert payments.reconcile_one(lambda i: pytest.fail("no checkout ID to query"))
    with SessionLocal() as db:
        assert db.scalar(select(MpesaIntent)).status == "uncertain"


def test_transport_payload_and_oauth(mpesa_shop, monkeypatch):
    requests = []

    def handle(req):
        assert req.url.host == "sandbox.safaricom.co.ke"
        requests.append(req)
        if req.url.path == "/oauth/v1/generate":
            assert req.headers["Authorization"].startswith("Basic ")
            return httpx.Response(200, json={"access_token": "dummy-token"})
        assert req.headers["Authorization"] == "Bearer dummy-token"
        return httpx.Response(200, json=accepted())

    original = httpx.Client
    monkeypatch.setattr(
        daraja.httpx,
        "Client",
        lambda **kwargs: original(transport=httpx.MockTransport(handle), **kwargs),
    )
    intent = SimpleNamespace(amount=Decimal("900"), phone="+254712345678")
    assert daraja.initiate(intent, "PF-123456789012")["ResponseCode"] == "0"
    import json

    payload = json.loads(requests[-1].content)
    assert payload["Amount"] == 900 and payload["PhoneNumber"] == "254712345678"
    assert payload["BusinessShortCode"] == "174379" and payload["PartyB"] == "174379"
    assert payload["TransactionType"] == "CustomerPayBillOnline"
    decoded = base64.b64decode(payload["Password"]).decode()
    assert decoded == "174379dummy-passkey" + payload["Timestamp"]


def test_transport_failure_is_sanitized(mpesa_shop, monkeypatch):
    original = httpx.Client
    monkeypatch.setattr(
        daraja.httpx,
        "Client",
        lambda **kwargs: original(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(401, json={"secret": "must not log"})
            ),
            **kwargs,
        ),
    )
    with pytest.raises(daraja.ProviderError) as exc:
        daraja.query(SimpleNamespace(checkout_id="test"))
    assert "must not log" not in str(exc.value) and "dummy-secret" not in str(exc.value)
