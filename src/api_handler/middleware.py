"""Exception handler middleware for the api_handler Lambda.

Provides a single ``exception_handler`` decorator factory that wraps a
Powertools ``APIGatewayRestResolver`` handler function and maps every known
``APIError`` subclass to a structured JSON error response.  Bare ``Exception``
instances that escape the handler are caught by a catch-all, logged in full to
CloudWatch Logs (via Powertools Logger), and returned as a safe 500 response
that contains no stack trace, no ARNs, and no boto3 error detail.

Usage::

    from api_handler.middleware import exception_handler

    @exception_handler
    def handler(event: dict, context: object) -> dict:
        ...  # your Powertools app.resolve(event, context) call
"""

import functools
from collections.abc import Callable
from typing import Any

from aws_lambda_powertools import Logger

from api_handler.exceptions import APIError
from api_handler.responses import error_response

logger = Logger()


def exception_handler(func: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
    """Decorator that catches ``APIError`` subclasses and bare exceptions.

    Wraps a Lambda handler (or any callable that receives ``event`` and
    ``context``) and intercepts exceptions before they propagate to the
    Lambda runtime, which would turn them into unstructured 502 responses
    from API Gateway.

    Mapping rules:
    - Any ``APIError`` subclass → ``error_response(status, token, message)``
      using the subclass's own ``http_status`` and ``error_token``.
    - Any other ``Exception`` → logs the full traceback with
      ``logger.exception``, then returns a 500 with token ``"server.error"``
      and a generic message.  The traceback goes to CloudWatch Logs only —
      never to the response body.

    Args:
        func: The Lambda handler callable to wrap.

    Returns:
        A wrapped callable with identical signature that never raises.
    """

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> dict[str, Any]:
        try:
            return func(*args, **kwargs)
        except APIError as exc:
            # Known domain error — no traceback needed, status/token already set.
            logger.warning(
                "API error",
                http_status=exc.http_status,
                error_token=exc.error_token,
                message=exc.message,
            )
            return error_response(exc.http_status, exc.error_token, exc.message)
        except Exception:
            # Unexpected error — log the full traceback, return a safe 500.
            # The traceback must stay in CloudWatch Logs and never reach the
            # response body (security requirement).
            logger.exception("Unhandled exception in Lambda handler")
            return error_response(
                500,
                "server.error",  # noqa: S105 — not a credential
                "An internal error occurred.",
            )

    return wrapper
