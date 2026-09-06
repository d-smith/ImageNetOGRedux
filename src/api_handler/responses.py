"""Response builder helpers for the api_handler Lambda.

All API responses pass through this module so that headers, status codes, and
body serialisation are applied consistently.  The helpers here are intentionally
narrow:

* ``ok(body)``            — 200 JSON response
* ``error_response(...)`` — structured error JSON with no stack trace

The error body shape is always::

    {"error": "<token>", "message": "<human-readable message>"}

No boto3 error details, ARNs, or Python tracebacks ever appear in a response
produced by this module.  The middleware layer (``middleware.py``) is
responsible for mapping ``APIError`` subclasses to ``error_response`` calls and
for logging the full traceback to CloudWatch before calling ``error_response``
for bare ``Exception`` instances.
"""

import json
from typing import Any

# Content-Type header applied to every response
_JSON_CONTENT_TYPE = "application/json"


def ok(body: dict[str, Any]) -> dict[str, Any]:
    """Build a 200 OK response with a JSON body.

    Args:
        body: A JSON-serialisable mapping to use as the response body.

    Returns:
        An API Gateway proxy response dict with ``statusCode=200``,
        ``Content-Type: application/json``, and the serialised body.
    """
    return {
        "statusCode": 200,
        "headers": {"Content-Type": _JSON_CONTENT_TYPE},
        "body": json.dumps(body),
    }


def error_response(status: int, token: str, message: str) -> dict[str, Any]:
    """Build a structured error response with no stack trace.

    The body is always ``{"error": "<token>", "message": "<message>"}``.
    Neither the token nor the message must contain internal resource names,
    table ARNs, or any other infrastructure details.

    Args:
        status: HTTP status code (e.g. 400, 404, 405, 500).
        token: Dot-separated error token (e.g. ``"param.invalid"``).
            Must match the pattern ``^[a-z_]+\\.[a-z_]+$``.
        message: Human-readable description of the error, safe for API
            consumers.  Must not include boto3 exception text, ARNs, or
            Python tracebacks.

    Returns:
        An API Gateway proxy response dict with the given ``statusCode``,
        ``Content-Type: application/json``, and the structured error body.
    """
    body = {"error": token, "message": message}
    return {
        "statusCode": status,
        "headers": {"Content-Type": _JSON_CONTENT_TYPE},
        "body": json.dumps(body),
    }
