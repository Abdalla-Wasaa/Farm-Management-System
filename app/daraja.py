"""Sandbox-only Daraja transport. No raw provider bodies, secrets or phones in logs."""

import base64
from datetime import datetime
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import httpx
from fastapi import HTTPException

from app.config import settings

BASE_URL = "https://sandbox.safaricom.co.ke"


class ProviderError(Exception):
    pass


def configured():
    if settings.daraja_mode != "sandbox":
        raise HTTPException(503, "Daraja sandbox is disabled")
    if not all(
        v.get_secret_value()
        for v in (
            settings.daraja_consumer_key,
            settings.daraja_consumer_secret,
            settings.daraja_passkey,
        )
    ):
        raise HTTPException(503, "Daraja credentials are missing")
    url = urlsplit(settings.daraja_callback_url)
    if (
        url.scheme != "https"
        or not url.hostname
        or url.hostname in ("localhost", "127.0.0.1", "::1")
        or url.username
        or url.fragment
    ):
        raise HTTPException(503, "Configure a public HTTPS Daraja callback URL")


def token(client):
    try:
        response = client.get(
            BASE_URL + "/oauth/v1/generate",
            params={"grant_type": "client_credentials"},
            auth=(
                settings.daraja_consumer_key.get_secret_value(),
                settings.daraja_consumer_secret.get_secret_value(),
            ),
        )
        response.raise_for_status()
        value = response.json()["access_token"]
        if not isinstance(value, str) or not value:
            raise ValueError()
        return value
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        raise ProviderError("Daraja authentication unavailable") from None


def password_fields():
    timestamp = datetime.now(ZoneInfo("Africa/Nairobi")).strftime("%Y%m%d%H%M%S")
    password = base64.b64encode(
        (
            settings.daraja_shortcode
            + settings.daraja_passkey.get_secret_value()
            + timestamp
        ).encode()
    ).decode()
    return {
        "BusinessShortCode": settings.daraja_shortcode,
        "Password": password,
        "Timestamp": timestamp,
    }


def post(path, payload):
    try:
        with httpx.Client(timeout=20, follow_redirects=False) as client:
            access_token = token(client)
            response = client.post(
                BASE_URL + path,
                json=payload,
                headers={"Authorization": "Bearer " + access_token},
            )
            response.raise_for_status()
            body = response.json()
            if not isinstance(body, dict):
                raise ValueError()
            return body
    except (httpx.HTTPError, ValueError, TypeError):
        raise ProviderError("Daraja request outcome unavailable") from None


def initiate(intent, reference):
    return post(
        "/mpesa/stkpush/v1/processrequest",
        {
            **password_fields(),
            "TransactionType": "CustomerPayBillOnline",
            "Amount": int(intent.amount),
            "PartyA": intent.phone.removeprefix("+"),
            "PartyB": settings.daraja_shortcode,
            "PhoneNumber": intent.phone.removeprefix("+"),
            "CallBackURL": settings.daraja_callback_url,
            "AccountReference": reference[-12:],
            "TransactionDesc": "Poultry order",
        },
    )


def query(intent):
    return post(
        "/mpesa/stkpushquery/v1/query",
        {**password_fields(), "CheckoutRequestID": intent.checkout_id},
    )
