"""Unit tests for router method/version enforcement (task 10.3).

Verifies:
* 405 for POST/PUT/DELETE/PATCH on a registered route path.
* 404 for paths that do not begin with ``/v1/`` (``/v2/...``, ``/``,
  ``/collections``).

_Requirements: 1.1, 1.2, 1.3, 2.1, 2.2_
"""

import json

import pytest

from api_handler import app as app_module
from api_handler.exceptions import MethodNotAllowedError

# Importing the routes package registers the real handlers on the resolver.
# ``app.py`` already imports them; we import explicitly here to make the
# dependency obvious and independent of import order.
import api_handler.routes.collections  # noqa: F401  isort: skip


def _event(method: str, path: str) -> dict:
    """Build a minimal REST API proxy event."""
    return {
        "httpMethod": method,
        "path": path,
        "resource": path,
        "queryStringParameters": None,
        "headers": {},
        "requestContext": {"httpMethod": method, "path": path},
    }


def _resolve(method: str, path: str) -> dict:
    return app_module.resolve(_event(method, path), None)


class TestMethodEnforcement:
    @pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "PATCH"])
    def test_non_get_on_registered_path_returns_405(self, method: str) -> None:
        # Method guard runs before routing, so no AWS access occurs.
        response = _resolve(method, "/v1/collections")
        assert response["statusCode"] == 405
        body = json.loads(response["body"])
        assert body["error"] == "method.not_allowed"

    def test_get_on_registered_path_passes_method_guard(self) -> None:
        # A GET must NOT trip the method guard. Asserting the guard directly
        # avoids executing the real (AWS-backed) handler in a unit test.
        app_module.check_method(_event("GET", "/v1/collections"))  # must not raise

    @pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "PATCH"])
    def test_non_get_trips_method_guard(self, method: str) -> None:
        with pytest.raises(MethodNotAllowedError):
            app_module.check_method(_event(method, "/v1/collections"))


class TestVersionPrefixEnforcement:
    @pytest.mark.parametrize("path", ["/v2/collections", "/", "/collections"])
    def test_non_v1_path_returns_404(self, path: str) -> None:
        # Version guard runs before routing, so no AWS access occurs.
        response = _resolve("GET", path)
        assert response["statusCode"] == 404
        body = json.loads(response["body"])
        assert body["error"] == "resource.not_found"

    def test_v1_prefix_passes_version_guard(self) -> None:
        # A registered /v1/ path must NOT be rejected by the version guard.
        # Asserting the guard directly avoids running the AWS-backed handler.
        app_module._check_version_prefix(_event("GET", "/v1/collections"))  # must not raise
