"""Turning SDK exceptions into something a caller can act on.

The Ark SDK raises its own exception types. Left alone they surface as an
opaque HTTP 500 with no explanation, which hides the actual problem -- most
commonly a key that is inactive or out of quota. ProviderError carries the
upstream status and message through so the API can return a useful error and
the CLI can print one.
"""

from __future__ import annotations

from typing import Any


class ProviderError(RuntimeError):
    """An error returned by (or while reaching) the Ark API."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        code: str | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code
        self.request_id = request_id

    @property
    def http_status(self) -> int:
        """The HTTP status this should surface as.

        401/403 mean *our* credentials are unusable, which is a server-side
        configuration problem rather than something the caller did wrong.
        """
        status = self.status_code
        if status in (401, 403):
            return 503
        if status == 429:
            return 429
        if status in (400, 404, 422):
            return 400
        return 502

    def __str__(self) -> str:
        parts = [self.message]
        if self.request_id:
            parts.append(f"(request id {self.request_id})")
        return " ".join(parts)


# Hints for the errors that are worth explaining rather than just echoing.
_HINTS = {
    "AuthenticationError": (
        "Check the key is active and has access to this model at "
        "https://ai.byteplus.com/ark/region:ap-southeast-1/apikey"
    ),
    "QuotaExceeded": "The account is out of quota for this model.",
    "RateLimitExceeded": "Too many requests; retry shortly.",
    "ModelNotOpen": "This model has not been enabled for the account.",
    "AccessDenied": "The key does not have access to this model.",
}


def translate(exc: Exception) -> Exception:
    """Convert an Ark SDK exception into a ProviderError.

    Anything that is not an SDK error is returned unchanged, so genuine bugs
    still surface as themselves rather than being disguised as API failures.
    """
    try:
        from byteplussdkarkruntime import _exceptions as ark_exc
    except ImportError:
        return exc

    if not isinstance(exc, ark_exc.ArkAPIError):
        return exc

    message: str = getattr(exc, "message", None) or str(exc)
    code: Any = getattr(exc, "code", None)
    status: int | None = getattr(exc, "status_code", None)

    # The SDK stringifies the whole body into `message`; the body itself has
    # the readable text.
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        message = body.get("message") or message
        code = body.get("code") or code

    if isinstance(exc, ark_exc.ArkAPIConnectionError):
        message = f"Could not reach the Ark API: {message}"
    elif code:
        message = f"Ark rejected the request ({code}): {message}"
    else:
        message = f"Ark rejected the request: {message}"

    hint = _HINTS.get(str(code))
    if hint:
        message = f"{message} {hint}"

    return ProviderError(
        message,
        status_code=status,
        code=str(code) if code else None,
        request_id=getattr(exc, "request_id", None),
    )
