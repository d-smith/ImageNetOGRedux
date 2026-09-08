"""Powertools router configuration for the api_handler Lambda.

This module initialises the ``APIGatewayRestResolver``, applies two
cross-cutting guards via an ``app.exception_handler`` and a before-request
hook, and exposes the ``app`` instance for use in ``lambda_function.py``.

Guards applied before any route handler runs:
1. **Method enforcement** — any non-GET request to a known path raises
   ``MethodNotAllowedError`` (→ 405).  Powertools routes on method+path, so
   non-GET requests simply fall through to a 404 by default; we intercept them
   here so callers get the correct 405 semantics.
2. **Version prefix guard** — any request whose path does not start with
   ``/v1/`` returns 404 immediately, before Powertools even attempts routing.

Route handlers are registered by importing the route modules; that import
triggers the ``@app.get(...)`` decorators which attach the handlers to this
resolver instance.  Routes are imported at the bottom of this module (after
``app`` is defined) to avoid circular imports.
"""

from typing import Any

from aws_lambda_powertools import Logger
from aws_lambda_powertools.event_handler import APIGatewayRestResolver
from aws_lambda_powertools.event_handler.exceptions import NotFoundError
from aws_lambda_powertools.utilities.typing import LambdaContext

from api_handler.exceptions import MethodNotAllowedError
from api_handler.responses import error_response

logger = Logger()

app = APIGatewayRestResolver()

# ---------------------------------------------------------------------------
# Version prefix guard
# ---------------------------------------------------------------------------

_V1_PREFIX = "/v1/"


@app.not_found
def _not_found_handler(_exc: NotFoundError) -> dict[str, Any]:
    """Return a plain 404 for all unmatched routes."""
    return error_response(404, "resource.not_found", "The requested resource does not exist.")


# ---------------------------------------------------------------------------
# Method enforcement
# ---------------------------------------------------------------------------

_ALLOWED_METHODS = frozenset({"GET"})


def check_method(event: dict[str, Any]) -> None:
    """Raise ``MethodNotAllowedError`` if the HTTP method is not GET.

    Called from the Lambda handler in ``lambda_function.py`` before
    ``app.resolve(event, context)`` so that non-GET requests always produce a
    405 rather than falling through to 404.

    Args:
        event: The raw API Gateway proxy event dict.

    Raises:
        MethodNotAllowedError: If the ``httpMethod`` field is not ``"GET"``.
    """
    method: str = str(event.get("httpMethod", "")).upper()
    path: str = str(event.get("path", ""))
    if method not in _ALLOWED_METHODS:
        raise MethodNotAllowedError(method, path)


class _VersionPrefixError(Exception):
    """Internal sentinel raised when a path lacks the /v1/ prefix."""

    def __init__(self, path: str) -> None:
        super().__init__(path)
        self.path = path


def _check_version_prefix(event: dict[str, Any]) -> None:
    """Raise ``_VersionPrefixError`` if the request path lacks the /v1/ prefix.

    Args:
        event: The raw API Gateway proxy event dict.

    Raises:
        _VersionPrefixError: If the path does not start with ``/v1/``.
    """
    path: str = str(event.get("path", ""))
    if not path.startswith(_V1_PREFIX):
        raise _VersionPrefixError(path)


@app.exception_handler(MethodNotAllowedError)  # type: ignore[misc]
def _handle_method_not_allowed(exc: MethodNotAllowedError) -> dict[str, Any]:
    """Map ``MethodNotAllowedError`` to a 405 response."""
    return error_response(exc.http_status, exc.error_token, exc.message)


def resolve(event: dict[str, Any], context: LambdaContext) -> dict[str, Any]:
    """Entry-point for route resolution with pre-flight guards applied.

    Applies version-prefix and method checks before delegating to
    ``app.resolve``.  Import and call this from ``lambda_function.py`` instead
    of calling ``app.resolve`` directly.

    Args:
        event: The raw API Gateway proxy event dict.
        context: The Lambda context object.

    Returns:
        An API Gateway proxy response dict.
    """
    try:
        _check_version_prefix(event)
    except _VersionPrefixError as exc:
        logger.info("Request rejected: path lacks /v1/ prefix", path=exc.path)
        return error_response(404, "resource.not_found", "The requested resource does not exist.")

    try:
        check_method(event)
    except MethodNotAllowedError as exc:
        logger.info("Request rejected: method not allowed", method=exc.method, path=exc.path)
        return error_response(exc.http_status, exc.error_token, exc.message)

    result: dict[str, Any] = app.resolve(event, context)
    return result
