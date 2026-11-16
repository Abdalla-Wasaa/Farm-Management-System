"""Isolated Playwright API. Refuses any database not explicitly ending _e2e_test.

Does not run the worker or contact payment/SMS providers.
"""

import json
import os
import secrets
import subprocess
import sys
from pathlib import Path

from sqlalchemy import make_url

url = make_url(os.environ.get("DATABASE_URL", ""))
if not url.database or not url.database.endswith("_e2e_test"):
    raise SystemExit("Browser tests require an isolated DATABASE_URL ending _e2e_test")
os.environ["JWT_SECRET"] = secrets.token_urlsafe(48)
os.environ["DARAJA_MODE"] = "sandbox"
os.environ["DARAJA_CONSUMER_KEY"] = "fake-e2e-key"
os.environ["DARAJA_CONSUMER_SECRET"] = "fake-e2e-secret"
os.environ["DARAJA_PASSKEY"] = "fake-e2e-passkey"
os.environ["DARAJA_CALLBACK_URL"] = (
    "https://fake-callback.example/payments/mpesa/callback"
)
os.environ["SMS_MODE"] = "dry-run"
os.environ["CORS_ORIGINS"] = '["http://127.0.0.1:5174","http://localhost:5174"]'
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True)
from sqlalchemy import inspect, text

from app.auth import create_user
from app.db import SessionLocal, engine
from app.models import Business

with engine.begin() as conn:
    tables = [t for t in inspect(engine).get_table_names() if t != "alembic_version"]
    quoted = ", ".join('"' + t.replace('"', '""') + '"' for t in tables)
    conn.execute(text(f"TRUNCATE {quoted} RESTART IDENTITY CASCADE"))
accounts = {}
with SessionLocal.begin() as db:
    for i, role in enumerate(
        ["admin", "seller", "staff", "rider", "other_buyer", "buyer"]
    ):
        phone = f"+2547169000{i:02}"
        secret = secrets.token_urlsafe(20)
        account = {"phone": phone, "password": secret}
        if role != "buyer":
            user = create_user(
                db, phone, secret, "buyer" if role == "other_buyer" else role
            )
            account["id"] = user.id
        accounts[role] = account
    farm = Business(name="Browser Test Farm", owner_id=accounts["seller"]["id"])
    db.add(farm)
    db.flush()
    accounts["business_id"] = farm.id
path = Path(".local/e2e-accounts.json")
path.parent.mkdir(exist_ok=True)
path.write_text(json.dumps(accounts))
path.chmod(0o600)
print(
    "Isolated browser test accounts generated; no worker or provider calls.", flush=True
)
import uvicorn

uvicorn.run("app.main:app", host="127.0.0.1", port=8012)
