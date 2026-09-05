"""Small deterministic safety utilities shared by the controller and audit path."""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any


def normalize_timestamp(value: str | None) -> str | None:
    if not value:
        return value
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except ValueError:
        return value


_PAN = re.compile(r"(?<!\d)\d(?:[ -]?\d){12,18}\d(?!\d)")
_SECRET = re.compile(r"(?i)\b(?:sk|pk)_[A-Za-z0-9_-]{8,}\b|\b(?:api[_-]?key|token|secret)[_-]?[A-Za-z0-9_-]{8,}\b")
_CVV = re.compile(r"(?i)\b(?:cvv|cvc|security code)\s*[:=]?\s*\d{3,4}\b")


def redact_sensitive(value: Any) -> Any:
    """Redact payment credentials from audit/context material without mutating input."""
    if isinstance(value, str):
        value = _PAN.sub("[REDACTED_CARD]", value)
        value = _SECRET.sub("[REDACTED_SECRET]", value)
        return _CVV.sub("[REDACTED_SECURITY_CODE]", value)
    if isinstance(value, dict):
        return {str(key): redact_sensitive(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_sensitive(item) for item in value]
    return value
