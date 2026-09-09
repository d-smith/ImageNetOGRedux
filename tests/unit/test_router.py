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


# Register a representative GET route once so there is a "registered path".
# The real route handlers (tasks 12+) are not yet implemented; this stand-in
# lets us exercise the method/version guards in isolation.
def _register_stub_route() -> None:
    resolver = app_module.app
    existing = {r.path for r in resolver._static_routes + resolver._dynamic_routes}  # type: ignore[attr-defined]
    if "/v1/collections" in existing:
        return

    @resolver.get("/v1/collections")
    def _list_collections_stub() -> dict:  # pragma: no cover - routing target
        return {"items": []}


_register_stub_route()


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
        response = _resolve(method, "/v1/collections")
        assert response["statusCode"] == 405
        body = json.loads(response["body"])
        assert body["error"] == "method.not_allowed"

    def test_get_on_registered_path_is_not_405(self) -> None:
        response = _resolve("GET", "/v1/collections")
        assert response["statusCode"] != 405


class TestVersionPrefixEnforcement:
    @pytest.mark.parametrize("path", ["/v2/collections", "/", "/collections"])
    def test_non_v1_path_returns_404(self, path: str) -> None:
        response = _resolve("GET", path)
        assert response["statusCode"] == 404
        body = json.loads(response["body"])
        assert body["error"] == "resource.not_found"

    def test_v1_prefix_not_rejected_by_version_guard(self) -> None:
        # A GET on a /v1/ path that is registered should not be a 404.
        response = _resolve("GET", "/v1/collections")
        assert response["statusCode"] != 404
