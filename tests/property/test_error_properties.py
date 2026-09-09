"""Property tests for error-response format (task 8.5).

* Property 17: any error condition produces a JSON body with an ``error``
  token matching ``^[a-z_]+\\.[a-z_]+$`` and a non-empty ``message``, with
  ``Content-Type: application/json``.
* Property 18: requests with invalid parameters produce a 400 body that names
  each invalid parameter.

_Requirements: 10.3, 10.5_
"""

import json
import re

from hypothesis import given
from hypothesis import strategies as st

from api_handler.exceptions import (
    CollectionNotFoundError,
    ImageNotFoundError,
    InvalidParameterError,
    MethodNotAllowedError,
)
from api_handler.middleware import exception_handler

_TOKEN_RE = re.compile(r"^[a-z_]+\.[a-z_]+$")

# Reasonable printable text for messages/identifiers (excludes control chars).
_text = st.text(
    alphabet=st.characters(min_codepoint=32, max_codepoint=126),
    min_size=1,
    max_size=40,
)

# Parameter names as they would appear in a query string.
_param_name = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_",
    min_size=1,
    max_size=20,
)


def _error_from(exc: Exception) -> dict:
    """Run the middleware against a handler that raises ``exc``."""

    @exception_handler
    def handler(event: dict, context: object) -> dict:
        raise exc

    return handler({}, None)


@given(name=_text)
def test_collection_not_found_error_shape(name: str) -> None:
    # Feature: aws-deployment-feature, Property 17: Structured error response format
    response = _error_from(CollectionNotFoundError(name))
    _assert_structured_error(response)


@given(name=_text, key=_text)
def test_image_not_found_error_shape(name: str, key: str) -> None:
    # Feature: aws-deployment-feature, Property 17: Structured error response format
    response = _error_from(ImageNotFoundError(name, key))
    _assert_structured_error(response)


@given(param=_param_name, reason=_text)
def test_invalid_parameter_error_shape(param: str, reason: str) -> None:
    # Feature: aws-deployment-feature, Property 17: Structured error response format
    response = _error_from(InvalidParameterError(param, reason))
    _assert_structured_error(response)


@given(method=_text, path=_text)
def test_method_not_allowed_error_shape(method: str, path: str) -> None:
    # Feature: aws-deployment-feature, Property 17: Structured error response format
    response = _error_from(MethodNotAllowedError(method, path))
    _assert_structured_error(response)


@given(exc_message=_text)
def test_bare_exception_error_shape(exc_message: str) -> None:
    # Feature: aws-deployment-feature, Property 17: Structured error response format
    response = _error_from(RuntimeError(exc_message))
    _assert_structured_error(response)
    assert response["statusCode"] == 500


@given(param=_param_name, reason=_text)
def test_invalid_parameter_names_the_param(param: str, reason: str) -> None:
    # Feature: aws-deployment-feature, Property 18: Errors identify invalid params by name
    response = _error_from(InvalidParameterError(param, reason))
    body = json.loads(response["body"])
    assert response["statusCode"] == 400
    # The offending parameter name must appear verbatim in the message.
    assert param in body["message"]


def _assert_structured_error(response: dict) -> None:
    """Assert a proxy response satisfies Property 17."""
    assert response["headers"]["Content-Type"] == "application/json"
    body = json.loads(response["body"])  # must be valid JSON
    assert _TOKEN_RE.match(body["error"]), f"token {body['error']!r} fails pattern"
    assert isinstance(body["message"], str)
    assert len(body["message"]) > 0
    assert 400 <= response["statusCode"] < 600
