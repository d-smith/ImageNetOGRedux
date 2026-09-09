"""Lambda entry-point for the ImageNetOG Redux ``api_handler`` function.

This module is the ``handler`` referenced by the Terraform Lambda
configuration (``lambda_function.handler``). It is intentionally thin:

1. Importing this module imports the ``api_handler`` package, whose
   ``__init__`` runs the Python 3.12 runtime guard at cold start (before any
   request is handled) — satisfying Requirement 1.3.
2. It wires the Powertools ``APIGatewayRestResolver`` app (with its version
   and method guards) and wraps invocation in the exception-handler
   middleware so that every error becomes a structured JSON response.

All routing and business logic live in ``app.py`` and the ``routes`` /
``services`` packages; this file only adapts the Lambda signature.
"""

from typing import Any

from aws_lambda_powertools import Logger
from aws_lambda_powertools.logging import correlation_paths
from aws_lambda_powertools.utilities.typing import LambdaContext

# Importing the package triggers the runtime version guard in
# ``api_handler/__init__.py`` at module load (cold start).
from api_handler import app as app_module
from api_handler.middleware import exception_handler

logger = Logger()


@exception_handler
@logger.inject_lambda_context(correlation_id_path=correlation_paths.API_GATEWAY_REST)
def handler(event: dict[str, Any], context: LambdaContext) -> dict[str, Any]:
    """AWS Lambda entry-point for the REST API.

    Applies the version-prefix and HTTP-method guards, then delegates to the
    Powertools resolver. Any raised ``APIError`` (or bare ``Exception``) is
    converted to a structured JSON response by the ``exception_handler``
    middleware — no traceback ever reaches the response body.

    Args:
        event: The API Gateway proxy integration event.
        context: The Lambda context object.

    Returns:
        An API Gateway proxy response dict.
    """
    return app_module.resolve(event, context)
