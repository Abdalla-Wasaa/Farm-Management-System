"""Delivery callback authentication and access-log secret redaction."""

import logging
import secrets

from fastapi import HTTPException

from app.config import settings

PATH = "/webhooks/sms/delivery"


def authenticate(value):
    expected = settings.sms_delivery_token.get_secret_value()
    if len(expected) < 32:
        raise HTTPException(503, "SMS delivery callback is not configured")
    if not secrets.compare_digest(expected.encode(), value.encode()):
        raise HTTPException(403, "Invalid callback authentication")


class CallbackLogFilter(logging.Filter):
    def filter(self, record):
        # Uvicorn arguments: client, method, full_path, http_version, status.
        if (
            isinstance(record.args, tuple)
            and len(record.args) >= 3
            and isinstance(record.args[2], str)
            and record.args[2].startswith(PATH)
        ):
            args = list(record.args)
            args[2] = PATH
            record.args = tuple(args)
        return True


def install_log_filter():
    logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, CallbackLogFilter) for f in logger.filters):
        logger.addFilter(CallbackLogFilter())
