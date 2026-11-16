from decimal import Decimal

from test_marketplace import place


def test_product_edit_adjustment_and_scoping(shop):
    c, u = shop
    pid = u["product_id"]
    body = {
        "business_id": u["business_id"],
        "name": "Updated eggs",
        "description": "New description",
        "category": "eggs",
        "unit": "tray",
        "price": "470.00",
    }
    oid = place(c, u).json()["id"]
    assert (
        c.patch(
            f"/products/{pid}", headers=u["buyer2"]["headers"], json=body
        ).status_code
        == 403
    )
    assert (
        c.patch(
            f"/products/{pid}", headers=u["seller"]["headers"], json=body
        ).status_code
        == 200
    )
    assert (
        c.get(f"/orders/{oid}", headers=u["buyer2"]["headers"]).json()["items"][0][
            "price"
        ]
        == "450.00"
    )
    assert (
        c.post(
            f"/products/{pid}/adjustments",
            headers=u["seller"]["headers"],
            json={"quantity": "-9", "source": "loss"},
        ).status_code
        == 409
    )
    for _ in range(2):
        assert (
            c.post(
                f"/products/{pid}/adjustments",
                headers=u["seller"]["headers"],
                json={"quantity": "-1", "source": "loss"},
            ).status_code
            == 200
        )
    assert Decimal(c.get(f"/products/{pid}").json()["stock"]) == 9
    assert (
        c.patch(
            f"/products/{pid}",
            headers=u["seller"]["headers"],
            json={**body, "unit": "egg"},
        ).status_code
        == 409
    )
    cors = c.options(
        f"/products/{pid}",
        headers={
            "Origin": "http://127.0.0.1:5173",
            "Access-Control-Request-Method": "PATCH",
            "Access-Control-Request-Headers": "Authorization,Content-Type",
        },
    )
    assert cors.status_code == 200
    assert cors.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"

    assert (
        c.post(
            f"/products/{pid}/adjustments",
            headers=u["seller"]["headers"],
            json={"quantity": "0", "source": "zero"},
        ).status_code
        == 422
    )
    assert c.get("/businesses/managed/list", headers=u["staff"]["headers"]).json() == []
    assert (
        len(c.get("/businesses/managed/list", headers=u["seller"]["headers"]).json())
        == 1
    )
    assert (
        c.get("/admin/users?role=rider", headers=u["seller"]["headers"]).status_code
        == 403
    )
    riders = c.get("/admin/users?role=rider", headers=u["admin"]["headers"]).json()
    assert len(riders) == 2 and "password_hash" not in riders[0]
    assert c.get("/marketplace/config").json()["delivery_fee"] == "200.00"
    details = c.get(f"/orders/{oid}", headers=u["buyer2"]["headers"]).json()
    assert (
        details["seller_phone"].startswith("+254")
        and details["business_name"] == "Our farm"
    )
