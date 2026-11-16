"""Reproducible HTTP buyer-to-delivery flow against a running local API.

Requires an existing admin. Reads credentials interactively; sends only dry-run
notifications unless the server operator explicitly changed SMS_MODE.
"""

import getpass
import os
import uuid
from decimal import Decimal

import httpx

BASE_URL = os.environ.get("API_URL", "http://localhost:8000")


def main():
    phone = input("Existing administrator phone: ")
    password = getpass.getpass("Administrator password: ")
    buyer_phone = input("New buyer Kenyan mobile number: ")
    rider_phone = input("New rider Kenyan mobile number: ")
    buyer_password = getpass.getpass("New buyer password (12+ chars): ")
    rider_password = getpass.getpass("New rider password (12+ chars): ")
    with httpx.Client(base_url=BASE_URL, timeout=20) as c:

        def request(method, path, headers=None, **kwargs):
            response = c.request(method, path, headers=headers, **kwargs)
            if response.is_error:
                # Keep passwords/tokens out of error diagnostics.
                raise SystemExit(
                    f"{method} {path}: HTTP {response.status_code}; consult /docs"
                )
            return response.json()

        def login(number, secret):
            result = request(
                "POST", "/auth/login", json={"phone": number, "password": secret}
            )
            return {"Authorization": "Bearer " + result["access_token"]}

        admin = login(phone, password)
        business = request("GET", "/businesses")[0]
        request(
            "POST",
            "/auth/register",
            json={"phone": buyer_phone, "password": buyer_password},
        )
        buyer = login(buyer_phone, buyer_password)
        rider = request(
            "POST",
            "/admin/users",
            headers=admin,
            json={"phone": rider_phone, "password": rider_password, "role": "rider"},
        )
        rider_auth = login(rider_phone, rider_password)
        product = request(
            "POST",
            "/products",
            headers=admin,
            json={
                "business_id": business["id"],
                "name": "Demo egg tray",
                "description": "30 fresh eggs",
                "category": "eggs",
                "unit": "tray",
                "price": "450.00",
            },
        )
        request(
            "POST",
            f"/products/{product['id']}/stock",
            headers=admin,
            json={"quantity": "5", "source": "demo-" + uuid.uuid4().hex},
        )
        products = request("GET", "/products")
        assert any(p["id"] == product["id"] for p in products)
        key = uuid.uuid4().hex
        body = {
            "items": [{"product_id": product["id"], "quantity": "2"}],
            "fulfillment": "delivery",
            "address": "Nairobi demo collection gate",
        }
        order = request(
            "POST", "/orders", headers={**buyer, "Idempotency-Key": key}, json=body
        )
        replay = request(
            "POST", "/orders", headers={**buyer, "Idempotency-Key": key}, json=body
        )
        assert replay["id"] == order["id"]
        oid = order["id"]
        for status in ["confirmed", "preparing", "ready"]:
            request(
                "POST", f"/orders/{oid}/status", headers=admin, json={"status": status}
            )
        request(
            "POST",
            f"/orders/{oid}/rider",
            headers=admin,
            json={"rider_id": rider["id"]},
        )
        assert any(
            o["id"] == oid
            for o in request("GET", "/deliveries/assigned", headers=rider_auth)
        )
        for status in ["dispatched", "delivered"]:
            request(
                "POST",
                f"/orders/{oid}/delivery",
                headers=rider_auth,
                json={"status": status},
            )
        request(
            "POST",
            f"/orders/{oid}/payments",
            headers=rider_auth,
            json={
                "amount": str(Decimal(str(order["total"]))),
                "receipt": "demo-cash-" + key,
            },
        )
        result = request("GET", f"/orders/{oid}", headers=buyer)
        assert result["status"] == "completed" and result["payment_status"] == "paid"
        print(
            f"{result['reference']}: completed, delivered, cash received KES {result['total']}"
        )
        print(
            "Run python -m app.worker --once to process notifications in configured SMS mode."
        )


if __name__ == "__main__":
    main()
