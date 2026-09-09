"""Unit tests for the exception-handler middleware (task 8.4).

Verifies that ``api_handler.middleware.exception_handler``:
* returns the correct JSON body shape ``{"error", "message"}``
* maps each ``APIError`` subclass to its declared status and token
* never leaks a traceback (or any internal detail) in a 500 body
* always sets ``Content-Type: application/json``

_Requirements: 10.3, 10.5, 10.6_
"""

import json

from api_handler.exceptions import (
    CollectionNotFoundError,
    ImageNotFoundError,
    InvalidParameterError,
    MethodNotAllowedError,
)
from api_handler.middleware import exception_handler


def _parse(response: dict) -> dict:
    """Return the parsed JSON body of a proxy response."""
    return json.loads(response["body"])


class TestApiErrorMapping:
    """Each APIError subclass maps to its declared status and token."""

    def test_collection_not_found_maps_to_404(self) -> None:
        @exception_handler
        def handler(event: dict, context: object) -> dict:
            raise CollectionNotFoundError("nature-2024")

        response = handler({}, None)

        assert response["statusCode"] == 404
        body = _parse(response)
        assert body["error"] == "resource.not_found"
        assert "nature-2024" in body["message"]

    def test_image_not_found_maps_to_404(self) -> None:
        @exception_handler
        def handler(event: dict, context: object) -> dict:
            raise ImageNotFoundError("nature-2024", "cat.jpg")

        response = handler({}, None)

        assert response["statusCode"] == 404
        assert _parse(response)["error"] == "resource.not_found"

    def test_invalid_parameter_maps_to_400(self) -> None:
        @exception_handler
        def handler(event: dict, context: object) -> dict:
            raise InvalidParameterError("limit", "must be between 1 and 100")

        response = handler({}, None)

        assert response["statusCode"] == 400
        body = _parse(response)
        assert body["error"] == "param.invalid"
        assert "limit" in body["message"]

    def test_method_not_allowed_maps_to_405(self) -> None:
        @exception_handler
        def handler(event: dict, context: object) -> dict:
            raise MethodNotAllowedError("POST", "/v1/collections")

        response = handler({}, None)

        assert response["statusCode"] == 405
        assert _parse(response)["error"] == "method.not_allowed"


class TestResponseShape:
    """Every error response has the same JSON shape and headers."""

    def test_body_has_exactly_error_and_message(self) -> None:
        @exception_handler
        def handler(event: dict, context: object) -> dict:
            raise InvalidParameterError("sort", "unknown field")

        body = _parse(handler({}, None))
        assert set(body.keys()) == {"error", "message"}

    def test_content_type_is_json(self) -> None:
        @exception_handler
        def handler(event: dict, context: object) -> dict:
            raise CollectionNotFoundError("x")

        response = handler({}, None)
        assert response["headers"]["Content-Type"] == "application/json"

    def test_success_passes_through_unchanged(self) -> None:
        @exception_handler
        def handler(event: dict, context: object) -> dict:
            return {"statusCode": 200, "headers": {}, "body": "{}"}

        response = handler({}, None)
        assert response["statusCode"] == 200


class TestBareExceptionSafety:
    """Bare exceptions become a safe 500 with no leaked internals."""

    def test_bare_exception_returns_500(self) -> None:
        @exception_handler
        def handler(event: dict, context: object) -> dict:
            raise RuntimeError("boto3 ClientError: arn:aws:dynamodb:...:table/prod-secret")

        response = handler({}, None)
        assert response["statusCode"] == 500

    def test_bare_exception_token_is_server_error(self) -> None:
        @exception_handler
        def handler(event: dict, context: object) -> dict:
            raise ValueError("internal detail")

        assert _parse(handler({}, None))["error"] == "server.error"

    def test_500_body_leaks_no_traceback_or_internal_detail(self) -> None:
        internal_arn = "arn:aws:dynamodb:us-east-1:123456789012:table/prod-imagenetog-images"

        @exception_handler
        def handler(event: dict, context: object) -> dict:
            raise RuntimeError(f"ClientError accessing {internal_arn}")

        response = handler({}, None)
        raw_body = response["body"]

        # No ARN, table name, exception class, or traceback markers leak.
        assert internal_arn not in raw_body
        assert "arn:aws" not in raw_body
        assert "Traceback" not in raw_body
        assert "RuntimeError" not in raw_body
        assert _parse(response)["message"] == "An internal error occurred."

    def test_500_content_type_is_json(self) -> None:
        @exception_handler
        def handler(event: dict, context: object) -> dict:
            raise RuntimeError("x")

        response = handler({}, None)
        assert response["headers"]["Content-Type"] == "application/json"
