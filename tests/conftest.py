import os

os.environ.setdefault("JWT_SECRET", "test-secret-at-least-32-characters-long")
os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg://farm:farm@localhost:5432/farm_test"
)
os.environ["DARAJA_MODE"] = "disabled"
# Never inherit live SMS credentials or recipient restrictions from a developer's .env.
for key, value in {
    "SMS_MODE": "dry-run",
    "AT_USERNAME": "sandbox",
    "AT_API_KEY": "",
    "AT_SENDER_ID": "",
    "SMS_ALLOWED_RECIPIENTS": "[]",
}.items():
    os.environ[key] = value
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.auth import create_user, token
from app.db import SessionLocal, engine
from app.main import app
from app.models import Business


@pytest.fixture()
def setup_db():
    # Test DB must be migrated first. Refuse destructive cleanup on a non-test DB.
    assert engine.url.database.endswith("_test"), (
        "DATABASE_URL must point to a *_test database"
    )
    with engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE users, businesses, products, orders, order_items, inventory_movements, payments, audit_events, notifications, notification_attempts, business_members, flocks, daily_records, production_transfers, expenses, mpesa_intents RESTART IDENTITY CASCADE"
            )
        )
    with SessionLocal.begin() as db:
        users = {}
        for i, role in enumerate(
            ["admin", "seller", "buyer", "buyer", "rider", "rider", "staff"]
        ):
            user = create_user(db, f"+2547123456{i:02}", "test-password-123", role)
            users[f"{role}{i}" if role in ("buyer", "rider") else role] = {
                "id": user.id,
                "headers": {"Authorization": f"Bearer {token(user)}"},
            }
        business = Business(name="Our farm", owner_id=users["seller"]["id"])
        db.add(business)
        db.flush()
        users["business_id"] = business.id
    with TestClient(app) as client:
        yield client, users


@pytest.fixture()
def shop(setup_db):
    client, users = setup_db
    response = client.post(
        "/products",
        headers=users["admin"]["headers"],
        json={
            "business_id": users["business_id"],
            "name": "Eggs",
            "description": "Fresh farm eggs",
            "category": "eggs",
            "unit": "tray",
            "price": "450.00",
        },
    )
    assert response.status_code == 201, response.text
    users["product_id"] = response.json()["id"]
    response = client.post(
        f"/products/{users['product_id']}/stock",
        headers=users["seller"]["headers"],
        json={"quantity": "10", "source": "opening"},
    )
    assert response.status_code == 200, response.text
    return client, users
