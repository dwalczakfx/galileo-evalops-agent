from __future__ import annotations

import json
import re
from typing import Any, Iterable


SENSITIVE_ASSIGNMENT = re.compile(
    r"(?i)\b(api[_-]?key|authorization|password|secret|token)\b"
    r"(\s*[:=]\s*)([\"']?)[^\s,;\"']+"
)
BEARER_TOKEN = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
SENSITIVE_KEY_MARKERS = (
    "api_key",
    "apikey",
    "authorization",
    "password",
    "passwd",
    "secret",
    "access_token",
    "refresh_token",
    "auth_token",
    "bearer_token",
)


def _is_sensitive_key(key: Any) -> bool:
    normalized = str(key).strip().lower().replace("-", "_")
    return normalized == "token" or any(
        marker in normalized
        for marker in SENSITIVE_KEY_MARKERS
    )


def redact_text(text: str, secrets: Iterable[str] = ()) -> str:
    redacted = text
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, "[REDACTED]")
    redacted = BEARER_TOKEN.sub("Bearer [REDACTED]", redacted)
    return SENSITIVE_ASSIGNMENT.sub(r"\1\2[REDACTED]", redacted)


def sanitize(value: Any, secrets: Iterable[str] = (), max_chars: int = 4000) -> Any:
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        text = redact_text(value, secrets)
        return text if len(text) <= max_chars else text[:max_chars] + "…[truncated]"
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            if _is_sensitive_key(key):
                cleaned[str(key)] = "[REDACTED]"
            else:
                cleaned[str(key)] = sanitize(item, secrets, max_chars)
        return cleaned
    if isinstance(value, list | tuple | set):
        return [sanitize(item, secrets, max_chars) for item in list(value)[:100]]
    if hasattr(value, "to_dict"):
        return sanitize(value.to_dict(), secrets, max_chars)
    return sanitize(str(value), secrets, max_chars)


def compact_json(value: Any, secrets: Iterable[str] = (), max_chars: int = 12000) -> str:
    rendered = json.dumps(sanitize(value, secrets, max_chars), ensure_ascii=False, default=str)
    return rendered if len(rendered) <= max_chars else rendered[:max_chars] + "…[truncated]"
