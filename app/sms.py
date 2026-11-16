"""Africa's Talking adapter. Never logs request bodies, phones or credentials."""

from dataclasses import dataclass

import httpx

from app.config import settings
from app.schemas import phone_number


@dataclass
class Result:
    outcome: str
    response: dict


def send(phone, message):
    if settings.sms_mode == "dry-run":
        return Result("dry-run", {"mode": "dry-run"})
    try:
        phone = phone_number(phone)
    except ValueError:
        return Result("permanent", {"error": "invalid_recipient"})
    if settings.sms_allowed_recipients and phone not in settings.sms_allowed_recipients:
        return Result("blocked", {"error": "recipient_not_allowlisted"})
    if not settings.at_api_key or (
        settings.sms_mode == "live" and settings.at_username == "sandbox"
    ):
        return Result("permanent", {"error": "provider_configuration"})
    if settings.sms_mode == "sandbox" and settings.at_username != "sandbox":
        return Result("permanent", {"error": "sandbox_username_required"})
    url = (
        "https://api.sandbox.africastalking.com/version1/messaging"
        if settings.sms_mode == "sandbox"
        else "https://api.africastalking.com/version1/messaging"
    )
    data = {"username": settings.at_username, "to": phone, "message": message}
    if settings.at_sender_id:
        data["from"] = settings.at_sender_id
    try:
        response = httpx.post(
            url,
            data=data,
            headers={"apiKey": settings.at_api_key, "Accept": "application/json"},
            timeout=15,
        )
        if response.status_code == 429 or response.status_code >= 500:
            return Result("temporary", {"http_status": response.status_code})
        if response.status_code >= 400:
            return Result("permanent", {"http_status": response.status_code})
        recipients = response.json()["SMSMessageData"]["Recipients"]
        if len(recipients) != 1:
            return Result("temporary", {"error": "invalid_recipient_response"})
        recipient = recipients[0]
        code = int(recipient["statusCode"])
        safe = {"status_code": code, "message_id": recipient.get("messageId", "")}
        if code in (100, 101, 102):
            return Result("accepted", safe)
        return Result("temporary" if code in (500, 501) else "permanent", safe)
    except httpx.TransportError:
        return Result("temporary", {"error": "transport_error"})
    except (ValueError, KeyError, TypeError):
        return Result("temporary", {"error": "malformed_provider_response"})
