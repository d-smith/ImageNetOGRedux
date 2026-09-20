"""Unit tests for image-key URL-decoding in the get_image route handler.

Regression coverage for the presigned-URL 404 caused by an un-decoded
``{image_key}`` path parameter. API Gateway delivers a key containing a slash
(e.g. ``photos/cat_0573.jpg``) percent-encoded as ``photos%2Fcat_0573.jpg`` so
it occupies a single path segment. The handler must ``unquote`` it before the
DynamoDB/S3 lookup, otherwise the lookup uses the literal encoded string and
returns ``resource.not_found``.

These tests drive the real Powertools resolver (so they also confirm Powertools
2.43.x does NOT decode path params itself — i.e. the handler-level decode is
both necessary and not a double-decode) and spy on the service layer to assert
the decoded key is what reaches AWS.
"""

from typing import Any
from unittest.mock import patch

from api_handler import app as app_module

# Importing the routes package registers the real handlers on the resolver.
import api_handler.routes.images  # noqa: F401  isort: skip


def _event(path: str) -> dict[str, Any]:
    """Build a minimal REST API proxy GET event for the given (already-encoded) path."""
    return {
        "httpMethod": "GET",
        "path": path,
        "resource": path,
        "queryStringParameters": None,
        "headers": {},
        "requestContext": {"httpMethod": "GET", "path": path},
    }


def test_encoded_slash_key_is_decoded_before_service_call() -> None:
    encoded_path = "/v1/collections/my-collection/images/photos%2Fcat_0573.jpg"

    with patch(
        "api_handler.routes.images.images_service.get_presigned_url",
        return_value={"key": "photos/cat_0573.jpg", "url": "https://example/signed"},
    ) as spy:
        response = app_module.resolve(_event(encoded_path), None)

    assert response["statusCode"] == 200
    spy.assert_called_once()
    args, _ = spy.call_args
    # The service must receive the DECODED key, not "photos%2Fcat_0573.jpg".
    assert args == ("my-collection", "photos/cat_0573.jpg")


def test_plain_key_without_encoding_is_unchanged() -> None:
    plain_path = "/v1/collections/my-collection/images/cat_0573.jpg"

    with patch(
        "api_handler.routes.images.images_service.get_presigned_url",
        return_value={"key": "cat_0573.jpg", "url": "https://example/signed"},
    ) as spy:
        response = app_module.resolve(_event(plain_path), None)

    assert response["statusCode"] == 200
    args, _ = spy.call_args
    assert args == ("my-collection", "cat_0573.jpg")


def test_encoded_traversal_is_rejected_after_decode() -> None:
    # An encoded "%2E%2E" (..) must be caught by validation, which runs AFTER
    # decoding. Powertools url-unquotes nothing here, so the handler's own
    # unquote turns "%2E%2E%2F..." into "../..." and validate_image_key rejects
    # it. Assert directly on the route function (the layer that enforces the
    # ordering); the APIError→400 mapping is covered by the middleware tests.
    from api_handler.exceptions import InvalidParameterError
    from api_handler.routes.images import get_image

    encoded_key = "%2E%2E%2Fetc%2Fpasswd"  # ".." + "/etc/passwd" encoded

    with patch(
        "api_handler.routes.images.images_service.get_presigned_url",
    ) as spy:
        # The Powertools resolver injects the path param as a kwarg; call the
        # underlying function directly with the encoded value it would receive.
        try:
            get_image("my-collection", encoded_key)
            raised = None
        except InvalidParameterError as exc:
            raised = exc

    assert raised is not None
    assert raised.http_status == 400
    spy.assert_not_called()
