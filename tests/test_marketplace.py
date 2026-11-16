from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import Notification, Order, Payment, Product, User, now
from app.schemas import OrderIn
from app.services import expire_orders, place_order


def order_body(users, fulfillment="delivery", quantity="2"):
    return {
        "items": [{"product_id": users["product_id"], "quantity": quantity}],
        "fulfillment": fulfillment,
        "address": "Nairobi, Gate 5" if fulfillment == "delivery" else "",
    }


def place(client, users, key="order-1", **kwargs):
    return client.post(
        "/orders",
        headers={**users["buyer2"]["headers"], "Idempotency-Key": key},
        json=order_body(users, **kwargs),
    )


def advance(client, users, oid, target):
    return client.post(
        f"/orders/{oid}/status",
        headers=users["seller"]["headers"],
        json={"status": target},
    )


def test_full_flow_and_payment(shop):
    c, u = shop
    response = place(c, u)
    assert response.status_code == 201, response.text
    order = response.json()
    oid = order["id"]
    assert Decimal(str(order["total"])) == Decimal("1100.00")
    assert order["payment_status"] == "unpaid"
    assert advance(c, u, oid, "ready").status_code == 409
    for target in ["confirmed", "preparing", "ready"]:
        assert advance(c, u, oid, target).status_code == 200
    assert (
        c.post(
            f"/orders/{oid}/rider",
            headers=u["seller"]["headers"],
            json={"rider_id": u["rider4"]["id"]},
        ).status_code
        == 403
    )
    assert (
        c.post(
            f"/orders/{oid}/rider",
            headers=u["admin"]["headers"],
            json={"rider_id": u["rider4"]["id"]},
        ).status_code
        == 200
    )
    assert (
        len(c.get("/deliveries/assigned", headers=u["rider4"]["headers"]).json()) == 1
    )
    assert (
        c.post(
            f"/orders/{oid}/delivery",
            headers=u["rider5"]["headers"],
            json={"status": "dispatched"},
        ).status_code
        == 403
    )
    for status in ["dispatched", "delivered"]:
        assert (
            c.post(
                f"/orders/{oid}/delivery",
                headers=u["rider4"]["headers"],
                json={"status": status},
            ).status_code
            == 200
        )
    assert advance(c, u, oid, "cancelled").status_code == 409
    payment = {"amount": "1100.00", "receipt": "cash-001"}
    assert (
        c.post(
            f"/orders/{oid}/payments", headers=u["buyer2"]["headers"], json=payment
        ).status_code
        == 403
    )
    assert (
        c.post(
            f"/orders/{oid}/payments",
            headers=u["rider4"]["headers"],
            json={**payment, "amount": "1000.00"},
        ).status_code
        == 409
    )
    for _ in range(2):
        assert (
            c.post(
                f"/orders/{oid}/payments", headers=u["rider4"]["headers"], json=payment
            ).status_code
            == 201
        )
    result = c.get(f"/orders/{oid}", headers=u["buyer2"]["headers"]).json()
    assert result["status"] == "completed" and result["delivery_status"] == "delivered"
    assert result["payment_status"] == "paid" and len(result["payments"]) == 1
    with SessionLocal() as db:
        product = db.get(Product, u["product_id"])
        assert product.stock == 8 and product.reserved == 0
        assert db.scalar(select(func.count()).select_from(Notification)) == 7
        assert db.scalar(select(func.count()).select_from(Payment)) == 1


def test_auth_permissions_and_ownership(shop):
    c, u = shop
    assert (
        c.post(
            "/auth/register",
            json={
                "phone": "0712345678",
                "password": "test-password-123",
                "role": "admin",
            },
        ).status_code
        == 422
    )
    r = c.post(
        "/auth/register", json={"phone": "0712345678", "password": "test-password-123"}
    )
    assert r.status_code == 201 and r.json()["role"] == "buyer"
    assert (
        c.post(
            "/auth/login", json={"phone": "0712345678", "password": "bad"}
        ).status_code
        == 401
    )
    assert (
        c.post(
            "/auth/login", json={"phone": "0712345678", "password": "test-password-123"}
        ).status_code
        == 200
    )
    assert c.get("/orders").status_code == 401
    assert (
        c.post(
            "/admin/users",
            headers=u["buyer2"]["headers"],
            json={
                "phone": "0712222222",
                "password": "test-password-123",
                "role": "admin",
            },
        ).status_code
        == 403
    )
    assert (
        c.post(
            f"/products/{u['product_id']}/stock",
            headers=u["staff"]["headers"],
            json={"quantity": "1", "source": "unauthorized"},
        ).status_code
        == 403
    )
    oid = place(c, u).json()["id"]
    assert c.get(f"/orders/{oid}", headers=u["buyer3"]["headers"]).status_code == 403
    assert c.get("/orders", headers=u["buyer3"]["headers"]).json() == []
    assert (
        c.post(
            f"/orders/{oid}/status",
            headers=u["buyer3"]["headers"],
            json={"status": "cancelled"},
        ).status_code
        == 403
    )
    assert (
        c.post(
            f"/orders/{oid}/status",
            headers=u["buyer2"]["headers"],
            json={"status": "confirmed"},
        ).status_code
        == 403
    )
    assert c.get(f"/orders/{oid}", headers=u["rider5"]["headers"]).status_code == 403


def test_reservations_cancel_expiry_and_idempotency(shop):
    c, u = shop
    first = place(c, u, quantity="8").json()
    assert place(c, u, quantity="8").json()["id"] == first["id"]
    assert place(c, u, quantity="7").status_code == 409
    assert place(c, u, key="second", quantity="3").status_code == 409
    assert (
        c.post(
            f"/orders/{first['id']}/status",
            headers=u["buyer2"]["headers"],
            json={"status": "cancelled"},
        ).status_code
        == 200
    )
    assert (
        c.post(
            f"/orders/{first['id']}/status",
            headers=u["buyer2"]["headers"],
            json={"status": "cancelled"},
        ).status_code
        == 200
    )
    second = place(c, u, key="second", quantity="10").json()
    with SessionLocal.begin() as db:
        db.get(Order, second["id"]).expires_at = now() - timedelta(seconds=1)
    assert advance(c, u, second["id"], "confirmed").status_code == 409
    with SessionLocal.begin() as db:
        assert expire_orders(db) == 1
    with SessionLocal.begin() as db:
        assert expire_orders(db) == 0
        p = db.get(Product, u["product_id"])
        assert p.reserved == 0 and p.stock == 10
        assert db.get(Order, second["id"]).status == "expired"


def test_pickup_snapshot_and_stock_replay(shop):
    c, u = shop
    assert (
        c.post(
            f"/products/{u['product_id']}/stock",
            headers=u["seller"]["headers"],
            json={"quantity": "10", "source": "opening"},
        ).status_code
        == 200
    )
    assert Decimal(str(c.get("/products").json()[0]["stock"])) == 10
    assert place(c, u, quantity="1.5").status_code == 422
    order = place(c, u, fulfillment="pickup").json()
    oid = order["id"]
    with SessionLocal.begin() as db:
        p = db.get(Product, u["product_id"])
        p.price = 999
        p.description = "changed"
    assert (
        c.get(f"/orders/{oid}", headers=u["buyer2"]["headers"]).json()["items"][0][
            "description"
        ]
        == "Fresh farm eggs"
    )
    assert (
        c.post(
            f"/orders/{oid}/payments",
            headers=u["admin"]["headers"],
            json={"amount": "900.00", "receipt": "early"},
        ).status_code
        == 409
    )
    for target in ["confirmed", "preparing", "ready", "completed"]:
        assert advance(c, u, oid, target).status_code == 200
    assert (
        c.post(
            f"/orders/{oid}/payments",
            headers=u["seller"]["headers"],
            json={"amount": "900.00", "receipt": "cash-pickup"},
        ).status_code
        == 201
    )


def test_competing_buyers_cannot_oversell(shop):
    c, u = shop

    def buy(name):
        try:
            with SessionLocal.begin() as db:
                actor = db.get(User, u[name]["id"])
                place_order(db, actor, OrderIn(**order_body(u, quantity="7")), name)
            return 201
        except HTTPException as exc:
            return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(buy, ["buyer2", "buyer3"]))
    assert sorted(results) == [201, 409]
    with SessionLocal() as db:
        assert db.get(Product, u["product_id"]).reserved == 7


def test_parallel_duplicate_order(shop):
    c, u = shop

    def buy(_):
        with SessionLocal.begin() as db:
            return place_order(
                db, db.get(User, u["buyer2"]["id"]), OrderIn(**order_body(u)), "same"
            ).id

    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(buy, range(2)))
    assert ids[0] == ids[1]
    with SessionLocal() as db:
        assert db.get(Product, u["product_id"]).reserved == 2


def test_mixed_seller_and_multi_item_failure_are_atomic(shop):
    c, u = shop
    other = c.post(
        "/businesses",
        headers=u["admin"]["headers"],
        json={"name": "Other seller", "owner_id": u["admin"]["id"]},
    ).json()
    second = c.post(
        "/products",
        headers=u["admin"]["headers"],
        json={
            "business_id": other["id"],
            "name": "Bird",
            "category": "live_broilers",
            "unit": "bird",
            "price": "600.00",
        },
    ).json()
    c.post(
        f"/products/{second['id']}/stock",
        headers=u["admin"]["headers"],
        json={"quantity": "1", "source": "opening"},
    )
    body = order_body(u)
    body["items"].append({"product_id": second["id"], "quantity": "1"})
    assert (
        c.post(
            "/orders",
            headers={**u["buyer2"]["headers"], "Idempotency-Key": "mixed"},
            json=body,
        ).status_code
        == 422
    )
    with SessionLocal.begin() as db:
        db.get(Product, second["id"]).business_id = u["business_id"]
    body["items"][1]["quantity"] = "2"
    assert (
        c.post(
            "/orders",
            headers={**u["buyer2"]["headers"], "Idempotency-Key": "short"},
            json=body,
        ).status_code
        == 409
    )
    with SessionLocal() as db:
        assert db.get(Product, u["product_id"]).reserved == 0
        assert db.get(Product, second["id"]).reserved == 0
        assert db.scalar(select(func.count()).select_from(Order)) == 0


def test_money_is_returned_as_exact_strings(shop):
    c, u = shop
    assert c.get("/products").json()[0]["price"] == "450.00"
    order = place(c, u).json()
    assert order["total"] == "1100.00"
    assert order["items"][0]["price"] == "450.00"
    assert order["items"][0]["line_total"] == "900.00"
