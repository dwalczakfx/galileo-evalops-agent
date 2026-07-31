from __future__ import annotations

from typing import Any, NoReturn

from openai import OpenAI

from .config import Settings
from .security import sanitize


class ModelConnectionError(RuntimeError):
    """Raised with a safe, actionable model endpoint error."""


def _exception_chain(error: Exception) -> list[Exception]:
    chain: list[Exception] = []
    current: BaseException | None = error
    seen: set[int] = set()
    while isinstance(current, Exception) and id(current) not in seen:
        chain.append(current)
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return chain


def describe_model_error(error: Exception, settings: Settings) -> str:
    chain = _exception_chain(error)
    combined = " ".join(
        f"{type(item).__name__}: {item}" for item in chain
    ).lower()
    if "authenticationerror" in combined or "incorrect api key" in combined or "401" in combined:
        return (
            f"Model authentication or access failed for {settings.model!r}. Check "
            "OPENAI_API_KEY and confirm EVALOPS_MODEL is permitted by the "
            "configured OPENAI_BASE_URL."
        )
    if "notfounderror" in combined or "model_not_found" in combined or "404" in combined:
        return (
            f"Configured model {settings.model!r} was not found or is not available "
            "to this API key. Check EVALOPS_MODEL and OPENAI_BASE_URL."
        )
    if "permissiondeniederror" in combined or "403" in combined:
        return (
            f"The model endpoint denied access to {settings.model!r}. Check the "
            "API key permissions and model assignment."
        )
    if "apiconnectionerror" in combined or "connection" in combined:
        return (
            "Could not connect to the configured model endpoint. Check "
            "OPENAI_BASE_URL, network access, and proxy settings."
        )
    if "ratelimiterror" in combined or "429" in combined:
        return "The configured model endpoint is rate-limiting requests. Retry later."

    detail = sanitize(str(chain[-1]), settings.secret_values(), 500)
    return f"Model request failed for {settings.model!r}: {detail}"


def raise_model_connection_error(error: Exception, settings: Settings) -> NoReturn:
    raise ModelConnectionError(describe_model_error(error, settings)) from error


def verify_model_connection(settings: Settings) -> dict[str, Any]:
    """Verify auth and exact model access without running a generation."""
    client = OpenAI(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        max_retries=0,
        timeout=30,
    )
    try:
        model = client.models.retrieve(settings.model)
    except Exception as exc:
        raise_model_connection_error(exc, settings)
    return {
        "model": getattr(model, "id", settings.model),
        "generation_calls": 0,
    }
