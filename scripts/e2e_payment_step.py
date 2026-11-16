"""Advance isolated test payments through the real services with fake providers."""

import os
import sys

from sqlalchemy import make_url, select

url = make_url(os.environ.get("DATABASE_URL", ""))
if not url.database or not url.database.endswith("_e2e_test"):
    raise SystemExit("Refusing to modify a non-browser-test database")
os.environ["DARAJA_MODE"] = "disabled"
os.environ["DARAJA_CONSUMER_KEY"] = "fake-e2e-key"
os.environ["DARAJA_CONSUMER_SECRET"] = "fake-e2e-secret"
os.environ["DARAJA_PASSKEY"] = "fake-e2e-passkey"
from app import daraja, payments
from app.db import SessionLocal
from app.models import MpesaIntent, now

step = sys.argv[1]
if step == "accepted":
    assert payments.submit_one(
        lambda i, r: {
            "ResponseCode": "0",
            "CheckoutRequestID": f"e2e-checkout-{i.id}",
            "MerchantRequestID": f"e2e-merchant-{i.id}",
        }
    )
elif step == "timeout":

    def timeout(*args):
        raise daraja.ProviderError("Mock ambiguous timeout")

    assert payments.submit_one(timeout)
elif step in ("success", "cancelled", "failed"):
    with SessionLocal.begin() as db:
        intent = db.scalar(
            select(MpesaIntent)
            .where(MpesaIntent.status == "pending")
            .order_by(MpesaIntent.id.desc())
        )
        assert intent is not None
        intent.next_check = now()
    assert payments.reconcile_one(
        lambda i: {
            "CheckoutRequestID": i.checkout_id,
            "MerchantRequestID": i.merchant_id,
            "ResultCode": 0
            if step == "success"
            else (1032 if step == "cancelled" else 1),
        }
    )
else:
    raise SystemExit("Unknown test step")
