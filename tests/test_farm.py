from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from test_marketplace import advance, place

from app.db import SessionLocal
from app.farm import transfer_production
from app.models import DailyRecord, Flock, Product, ProductionTransfer, User
from app.schemas import TransferIn

DAY = str(date.today())


def new_flock(c, u, kind="layer", birds=100):
    r = c.post(
        "/flocks",
        headers=u["seller"]["headers"],
        json={
            "business_id": u["business_id"],
            "name": "Batch A",
            "kind": kind,
            "initial_birds": birds,
            "started_on": DAY,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def daily(c, u, fid, **overrides):
    return c.post(
        f"/flocks/{fid}/daily-records",
        headers=u["seller"]["headers"],
        json={"day": DAY, "mortality": 2, "eggs": 60, "feed_kg": "12.500", **overrides},
    )


def test_daily_and_egg_stock_traceability(shop):
    c, u = shop
    fid = new_flock(c, u)
    record = daily(c, u, fid).json()
    assert daily(c, u, fid).json()["id"] == record["id"]
    assert daily(c, u, fid, eggs=61).status_code == 409
    assert Decimal(str(c.get("/products").json()[0]["stock"])) == 10
    transfer = {
        "source": "egg-1",
        "product_id": u["product_id"],
        "quantity": "2",
        "daily_record_id": record["id"],
    }
    for _ in range(2):
        r = c.post(
            f"/flocks/{fid}/transfers", headers=u["seller"]["headers"], json=transfer
        )
        assert r.status_code == 201, r.text
    assert (
        c.post(
            f"/flocks/{fid}/transfers",
            headers=u["seller"]["headers"],
            json={**transfer, "source": "egg-2", "quantity": "1"},
        ).status_code
        == 409
    )
    with SessionLocal() as db:
        assert db.get(Flock, fid).live_birds == 98
        assert db.get(Product, u["product_id"]).stock == 12
        assert db.get(DailyRecord, record["id"]).transferred_eggs == 60
        assert db.scalar(select(func.count()).select_from(ProductionTransfer)) == 1
    moves = c.get(
        f"/products/{u['product_id']}/movements", headers=u["seller"]["headers"]
    ).json()
    assert any(
        m["kind"] == "production" and m["source"].startswith("production:")
        for m in moves
    )


def test_broiler_harvest_and_mortality(shop):
    c, u = shop
    fid = new_flock(c, u, "broiler", 10)
    assert daily(c, u, fid).status_code == 422
    assert daily(c, u, fid, eggs=0, mortality=11).status_code == 409
    assert daily(c, u, fid, eggs=0, mortality=2).status_code == 201
    p = c.post(
        "/products",
        headers=u["seller"]["headers"],
        json={
            "business_id": u["business_id"],
            "name": "Dressed chicken",
            "category": "dressed_chicken",
            "unit": "kilogram",
            "price": "500.00",
        },
    ).json()
    data = {
        "source": "harvest-1",
        "product_id": p["id"],
        "quantity": "6.750",
        "birds_removed": 3,
    }
    for _ in range(2):
        assert (
            c.post(
                f"/flocks/{fid}/transfers", headers=u["seller"]["headers"], json=data
            ).status_code
            == 201
        )
    with SessionLocal() as db:
        assert db.get(Flock, fid).live_birds == 5
        assert db.get(Product, p["id"]).stock == Decimal("6.750")
    assert (
        c.post(
            f"/flocks/{fid}/transfers",
            headers=u["seller"]["headers"],
            json={**data, "source": "harvest-2", "birds_removed": 6},
        ).status_code
        == 409
    )
    assert (
        c.post(
            f"/flocks/{fid}/transfers",
            headers=u["seller"]["headers"],
            json={**data, "quantity": "8"},
        ).status_code
        == 409
    )


def test_staff_membership_and_farm_permissions(shop):
    c, u = shop
    fid = new_flock(c, u)
    assert (
        c.get(
            f"/businesses/{u['business_id']}/flocks", headers=u["buyer2"]["headers"]
        ).status_code
        == 403
    )
    assert (
        c.get(f"/flocks/{fid}/daily-records", headers=u["staff"]["headers"]).status_code
        == 403
    )
    assert (
        c.post(
            f"/businesses/{u['business_id']}/members",
            headers=u["seller"]["headers"],
            json={"user_id": u["staff"]["id"]},
        ).status_code
        == 403
    )
    assert (
        c.post(
            f"/businesses/{u['business_id']}/members",
            headers=u["admin"]["headers"],
            json={"user_id": u["staff"]["id"]},
        ).status_code
        == 201
    )
    assert (
        c.post(
            f"/flocks/{fid}/daily-records",
            headers=u["staff"]["headers"],
            json={"day": DAY, "mortality": 1},
        ).status_code
        == 201
    )
    oid = place(c, u).json()["id"]
    assert len(c.get("/orders", headers=u["staff"]["headers"]).json()) == 1
    assert (
        c.post(
            f"/orders/{oid}/status",
            headers=u["staff"]["headers"],
            json={"status": "confirmed"},
        ).status_code
        == 200
    )


def test_summary_and_expense_idempotency(shop):
    c, u = shop
    fid = new_flock(c, u)
    daily(c, u, fid)
    data = {
        "business_id": u["business_id"],
        "flock_id": fid,
        "day": DAY,
        "category": "feed",
        "description": "Feed purchase",
        "amount": "500.00",
        "source": "invoice-1",
    }
    for _ in range(2):
        assert (
            c.post("/expenses", headers=u["seller"]["headers"], json=data).status_code
            == 201
        )
    assert (
        c.post(
            "/expenses",
            headers=u["seller"]["headers"],
            json={**data, "amount": "550.00"},
        ).status_code
        == 409
    )
    oid = place(c, u, fulfillment="pickup").json()["id"]
    for target in ["confirmed", "preparing", "ready", "completed"]:
        assert advance(c, u, oid, target).status_code == 200
    assert (
        c.post(
            f"/orders/{oid}/payments",
            headers=u["seller"]["headers"],
            json={"amount": "900.00", "receipt": "cash-1"},
        ).status_code
        == 201
    )
    r = c.get(
        f"/businesses/{u['business_id']}/summary",
        headers=u["seller"]["headers"],
        params={"start": DAY, "end": DAY},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert (
        Decimal(str(data["cash_received"])) == 900
        and Decimal(str(data["expenses"])) == 500
    )
    assert (
        data["mortality"] == 2
        and data["eggs"] == 60
        and Decimal(str(data["feed_kg"])) == Decimal("12.5")
    )
    assert data["sales_by_unit"][0]["unit"] == "tray"
    assert Decimal(str(data["sales_by_unit"][0]["quantity"])) == 2
    assert (
        c.get(
            f"/businesses/{u['business_id']}/summary",
            headers=u["buyer2"]["headers"],
            params={"start": DAY, "end": DAY},
        ).status_code
        == 403
    )


def test_parallel_production_deduplicates(shop):
    c, u = shop
    fid = new_flock(c, u)
    record = daily(c, u, fid).json()
    data = TransferIn(
        source="production-key",
        product_id=u["product_id"],
        quantity=2,
        daily_record_id=record["id"],
    )

    def transfer(_):
        with SessionLocal.begin() as db:
            return transfer_production(
                db, db.get(User, u["seller"]["id"]), fid, data
            ).id

    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(transfer, range(2)))
    assert ids[0] == ids[1]
    with SessionLocal() as db:
        assert db.get(Product, u["product_id"]).stock == 12
        assert db.get(DailyRecord, record["id"]).transferred_eggs == 60
