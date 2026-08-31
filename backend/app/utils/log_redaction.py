"""Prevent credentials from leaking through application or vendor loggers."""
from __future__ import annotations

import logging
import re
from typing import Any


_SECRET_KEYS = (
    "X-PrivateKey",
    "x-api-key",
    "api_key",
    "ANGEL_API_KEY",
    "Authorization",
    "x-feed-token",
    "access_token",
    "authToken",
    "feed_token",
    "refreshToken",
    "jwtToken",
)
_KEYS = "|".join(re.escape(key) for key in _SECRET_KEYS)
_QUOTED_VALUE = re.compile(
    rf"(?i)((?:['\"])?(?:{_KEYS})(?:['\"])?\s*[:=]\s*['\"])[^'\"]*(['\"])"
)
_BARE_VALUE = re.compile(
    rf"(?i)((?:{_KEYS})\s*[:=]\s*)(?!['\"])[^,\s}}]+"
)


def redact_secrets(value: Any) -> str:
    text = str(value)
    text = _QUOTED_VALUE.sub(r"\1[REDACTED]\2", text)
    return _BARE_VALUE.sub(r"\1[REDACTED]", text)


class SecretRedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_secrets(record.getMessage())
        record.args = ()
        return True


_FILTER = SecretRedactionFilter()


def install_secret_redaction() -> None:
    """Attach redaction to root handlers and SmartAPI's logzero logger."""
    root = logging.getLogger()
    for handler in root.handlers:
        if _FILTER not in handler.filters:
            handler.addFilter(_FILTER)
    try:
        from logzero import logger as vendor_logger

        if _FILTER not in vendor_logger.filters:
            vendor_logger.addFilter(_FILTER)
        for handler in vendor_logger.handlers:
            if _FILTER not in handler.filters:
                handler.addFilter(_FILTER)
    except ImportError:
        pass
